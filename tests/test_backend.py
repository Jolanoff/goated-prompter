import importlib
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch


# Import backend modules without running ComfyUI node/route registration.
PACKAGE = "_goated_backend_tests"
package = ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "goated_prompter")]
sys.modules[PACKAGE] = package
backends = ModuleType(f"{PACKAGE}.backends")
backends.__path__ = [str(Path(package.__path__[0]) / "backends")]
sys.modules[backends.__name__] = backends
llama = importlib.import_module(f"{PACKAGE}.backends.llama_cpp_process")
openai = importlib.import_module(f"{PACKAGE}.backends.openai_compatible")


class ProcessManagerTests(unittest.TestCase):
    def setUp(self):
        self.config = llama.LlamaCppLaunchConfig(
            executable=Path("llama-server"), model_path=Path("model.gguf"),
            mmproj_path=Path("mmproj.gguf"), host="127.0.0.1", port=8189,
            context_size=8192, image_min_tokens=1024, gpu_layers="auto",
            reasoning="off", keep_model_loaded=True, max_tokens=768,
            timeout=180, startup_timeout=180, temperature=0.3,
            alias="test", requested_model="Display label",
        )
        self.manager = llama.LlamaCppProcessManager()
        self.process = Mock()
        self.process.poll.return_value = None
        self.process.wait.side_effect = lambda **kwargs: setattr(self.process.poll, "return_value", 0)
        for name, kwargs in (
            ("_runtime_config", {"side_effect": lambda config: config}),
            ("_start_process", {"return_value": self.process}),
            ("_wait_until_ready", {}),
        ):
            patcher = patch.object(self.manager, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(llama, "_log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_latest_acquire_retention_wins_in_both_directions(self):
        for first, latest in ((True, False), (False, True)):
            with self.subTest(first=first):
                self.manager._owned = None
                self.process.reset_mock()
                self.process.poll.return_value = None
                owned = self.manager.acquire(replace(self.config, keep_model_loaded=first))
                reused = self.manager.acquire(replace(self.config, keep_model_loaded=latest))
                self.assertIs(reused, owned)
                self.assertEqual(owned.keep_model_loaded, latest)
                self.manager.release(owned)
                self.process.terminate.assert_not_called()
                self.manager.release(reused)
                self.assertEqual(self.manager.owned_process_count, int(latest))
                self.assertEqual(self.process.terminate.call_count, int(not latest))

    def test_idle_retained_server_uses_new_retention(self):
        owned = self.manager.acquire(self.config)
        self.manager.release(owned)
        self.assertIs(self.manager.acquire(replace(self.config, keep_model_loaded=False)), owned)
        self.manager.release(owned)
        self.assertEqual(self.manager.owned_process_count, 0)

    def test_pending_unload_overrides_latest_retention(self):
        owned = self.manager.acquire(self.config)
        self.assertEqual(self.manager.request_unload(), "pending")
        self.manager.acquire(replace(self.config, keep_model_loaded=True))
        self.manager.release(owned)
        self.process.terminate.assert_not_called()
        self.manager.release(owned)
        self.assertEqual(self.manager.owned_process_count, 0)

    def test_interrupt_active_stops_the_owned_server(self):
        self.manager.acquire(self.config)
        self.assertEqual(self.manager.interrupt_active(), "stopped")
        self.process.terminate.assert_called_once()
        self.assertIsNone(self.manager._owned)

    def test_display_label_does_not_restart(self):
        renamed = replace(self.config, requested_model="Another label")
        self.assertEqual(self.config.command(), renamed.command())
        self.assertEqual(self.config.key, renamed.key)
        self.assertEqual(self.config.compatibility_key, renamed.compatibility_key)
        self.assertFalse(self.manager._model_changed(self.config, renamed))
        owned = self.manager.acquire(self.config)
        self.assertIs(self.manager.acquire(renamed), owned)
        self.manager._start_process.assert_called_once()
        self.process.terminate.assert_not_called()

    def test_cli_changes_still_require_restart(self):
        owned = self.manager.acquire(self.config)
        for name, value in (("alias", "other"), ("model_path", Path("other.gguf")),
                            ("context_size", 4096), ("port", 8190)):
            with self.subTest(name=name):
                changed = replace(self.config, **{name: value})
                self.assertNotEqual(self.config.key, changed.key)
                self.assertFalse(self.manager._compatible(owned, changed))

    def test_failed_termination_retains_ownership_at_each_call_site(self):
        for operation in ("release", "unload", "cleanup", "restart", "startup"):
            for failure in ("terminate", "kill", "post_kill_timeout"):
                with self.subTest(operation=operation, failure=failure):
                    self.manager._owned = None
                    self.process.poll.return_value = None
                    self.process.terminate.side_effect = OSError("denied") if failure == "terminate" else None
                    self.process.kill.side_effect = OSError("denied") if failure == "kill" else None
                    self.process.wait.side_effect = subprocess.TimeoutExpired("llama-server", 5)
                    self.manager._wait_until_ready.side_effect = None
                    owned = self.manager.acquire(self.config)
                    self.manager._start_process.reset_mock()
                    if operation == "release":
                        owned.keep_model_loaded = False
                        action = lambda: self.manager.release(owned)
                    elif operation == "startup":
                        self.manager._owned = None
                        self.manager._wait_until_ready.side_effect = llama.BackendGenerationError("not ready")
                        action = lambda: self.manager.acquire(self.config)
                    else:
                        owned.references = 0
                        action = {
                            "unload": self.manager.request_unload,
                            "cleanup": self.manager.cleanup_all,
                            "restart": lambda: self.manager.acquire(replace(self.config, alias="other")),
                        }[operation]
                    with self.assertRaisesRegex(llama.BackendGenerationError, "Could not stop"):
                        action()
                    retained = self.manager._owned
                    self.assertIs(retained.process, self.process)
                    self.assertEqual(retained.references, 0)
                    self.assertTrue(retained.pending_unload)
                    self.assertEqual(self.manager.owned_process_count, 1)
                    if operation != "startup":
                        self.assertIs(retained, owned)
                        self.manager._start_process.assert_not_called()
                    self.process.terminate.side_effect = None
                    self.process.wait.side_effect = lambda **kwargs: setattr(self.process.poll, "return_value", 0)
                    self.assertEqual(self.manager.request_unload(), "unloaded")
                    self.assertIsNone(self.manager._owned)

    def test_kill_escalation_and_exit_race(self):
        for exit_race in (False, True):
            with self.subTest(exit_race=exit_race):
                self.manager._owned = None
                self.process.reset_mock()
                self.process.poll.return_value = None
                owned = self.manager.acquire(replace(self.config, keep_model_loaded=False))
                if exit_race:
                    def terminate():
                        self.process.poll.return_value = 0
                        raise OSError("already exited")
                    self.process.terminate.side_effect = terminate
                else:
                    self.process.wait.side_effect = subprocess.TimeoutExpired("llama-server", 5)
                    self.process.kill.side_effect = lambda: setattr(self.process.poll, "return_value", 0)
                self.manager.release(owned)
                self.assertIsNone(self.manager._owned)
                if not exit_race:
                    self.process.kill.assert_called_once()


class OpenAITimeoutTests(unittest.TestCase):
    def test_timeout_is_passed_to_http_without_shortening_slow_requests(self):
        for requested, expected in ((None, 90), (600, 600), (1800, 1800),
                                    (3600, 3600), (7200, 3600), (0, 1)):
            with self.subTest(timeout=requested):
                settings = {"base_url": "http://127.0.0.1:8189/v1", "model": "test"}
                if requested is not None:
                    settings["timeout"] = requested
                backend = openai.OpenAICompatibleBackend(settings)
                instruction = Mock(image=None, image_2=None)
                instruction.to_messages.return_value = [{"role": "user", "content": "test"}]
                response = MagicMock()
                response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"result"}}]}'
                with patch.object(openai, "urlopen", return_value=response) as request, \
                     patch.object(openai, "log_request"), patch.object(openai, "log_response"), \
                     patch.object(openai, "_log_multimodal_messages"):
                    self.assertEqual(backend.generate(instruction), "result")
                self.assertEqual(request.call_args.kwargs["timeout"], expected)


class FinalBudgetTests(unittest.TestCase):
    def instruction(self, max_tokens=None):
        core = importlib.import_module(f"{PACKAGE}.core")
        return core.PromptInstruction("system", "user", max_tokens=max_tokens)

    def outgoing(self, backend, instruction, finish_reason="stop"):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "result"}, "finish_reason": finish_reason}],
        }).encode()
        with patch.object(openai, "urlopen", return_value=response) as send, \
             patch.object(openai, "log_request"), patch.object(openai, "log_response"):
            self.assertEqual(backend.generate(instruction), "result")
        return json.loads(send.call_args.args[0].data)

    def backend(self, **settings):
        return openai.OpenAICompatibleBackend({"base_url": "http://localhost:8189/v1", "model": "test", **settings})

    def test_maximum_final_floor_and_larger_config_budget(self):
        for configured in (768, 4096):
            backend = self.backend(max_tokens=configured)
            self.assertEqual(self.outgoing(backend, self.instruction(3072))["max_tokens"], max(configured, 3072))
            self.assertEqual(self.outgoing(backend, self.instruction())["max_tokens"], configured)

    def test_analysis_budget_unchanged_and_alias_guidance_equal(self):
        core = importlib.import_module(f"{PACKAGE}.core")
        backend = self.backend()
        instructions = [core.assemble_instruction(core.GoatedPrompterRequest.from_mapping({
            "idea": "portrait", "prompt_length": length,
        })) for length in ("Maximum", "Maximum Detail")]
        self.assertEqual(instructions[0], instructions[1])
        for instruction in instructions:
            self.assertEqual(self.outgoing(backend, instruction)["max_tokens"], 3072)
        analysis = replace(self.instruction(), diagnostic_stage="evidence:image_4")
        self.assertEqual(self.outgoing(backend, analysis)["max_tokens"], 768)
        for length in ("Short", "Medium", "Detailed"):
            instruction = core.assemble_instruction(core.GoatedPrompterRequest(idea="portrait", prompt_length=length))
            self.assertEqual(self.outgoing(backend, instruction)["max_tokens"], 768)

    def test_context_cap_reserve_and_actionable_failure(self):
        backend = self.backend(context_size=8192, max_tokens=10000, context_reserve_tokens=2048)
        budget = self.outgoing(backend, self.instruction(3072))["max_tokens"]
        self.assertEqual(budget, 8192 - 2048 - 3)
        for context, text in ((4096, "user"), (8192, "x" * 20000)):
            with self.subTest(context=context):
                instruction = replace(self.instruction(3072), user_message=text)
                with patch.object(openai, "urlopen") as send:
                    with self.assertRaisesRegex(openai.BackendConfigurationError, "coarse input estimate.*Increase context size"):
                        self.backend(context_size=context).generate(instruction)
                send.assert_not_called()

    def test_local_session_uses_actual_transport_override_and_releases(self):
        local = importlib.import_module(f"{PACKAGE}.backends.local_llama_cpp")
        config = llama.LlamaCppLaunchConfig(
            executable=Path("llama-server"), model_path=Path("model.gguf"),
            mmproj_path=Path("mmproj.gguf"), host="127.0.0.1", port=8189,
            context_size=8192, image_min_tokens=1024, gpu_layers="auto",
            reasoning="off", keep_model_loaded=True, max_tokens=768,
            timeout=180, startup_timeout=180, temperature=0.3,
            alias="test", requested_model="Display label",
        )
        manager = Mock()
        owned = SimpleNamespace(config=replace(config, port=8190), process=SimpleNamespace(pid=42))
        manager.acquire.return_value = owned, {"reused": True, "restarted": False}
        with patch.object(llama.LlamaCppLaunchConfig, "from_mapping", return_value=config):
            backend = local.LocalLlamaCppBackend({}, process_manager=manager)
        with backend.generation_session() as client:
            self.assertIn(":8190/", client.url)
            self.assertEqual(client.context_size, 8192)
            self.assertEqual(self.outgoing(client, self.instruction())["max_tokens"], 768)
            self.assertEqual(self.outgoing(client, self.instruction(3072))["max_tokens"], 3072)
            core = importlib.import_module(f"{PACKAGE}.core")
            references = importlib.import_module(f"{PACKAGE}.reference_map")
            evidence = importlib.import_module(f"{PACKAGE}.evidence")
            request = core.GoatedPrompterRequest(
                idea="cinematic portrait wearing a coat", linked_references=True,
                prompt_length="Maximum Detail", image_4=object(),
                reference_map={key: "Image 4" for key, _label in references.REFERENCE_ATTRIBUTES},
            )
            resolved = references.resolve_reference_map(request)
            observed = evidence.parse_image_evidence(json.dumps({
                key: "Observed visual detail for " + label for key, label in references.REFERENCE_ATTRIBUTES
            }), "test")
            scene = evidence.build_resolved_scene(resolved, evidence_by_source={"Image 4": observed})
            instruction = core.assemble_instruction(request, resolved_scene=scene)
            self.assertEqual(self.outgoing(client, instruction)["max_tokens"], 3072)
        manager.release.assert_called_once_with(owned)

    def test_finish_reason_length_never_returns_partial_success(self):
        for tokens in (None, 3072):
            with self.assertRaisesRegex(openai.BackendGenerationError, "truncated.*Increase max_tokens and context size"):
                self.outgoing(self.backend(), self.instruction(tokens), finish_reason="length")

    def test_base_validates_third_and_fourth_images(self):
        base = importlib.import_module(f"{PACKAGE}.backends.base")
        class TextBackend(base.GoatedPrompterBackend):
            def generate(self, instruction):
                return "unused"
        for field in ("image_3", "image_4"):
            with self.assertRaises(base.BackendCapabilityError):
                TextBackend().validate_instruction(replace(self.instruction(), **{field: object()}))


if __name__ == "__main__":
    unittest.main()
