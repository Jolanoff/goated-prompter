"""Opt-in, operation-scoped runaway recovery; transports and their detectors never retry."""

from dataclasses import replace

from .base import BackendGenerationError, BackendRunawayError

MAX_ATTEMPTS = 3
RECOVERY_RULE = ("\n\nREPETITION RECOVERY (attempt {attempt} of {maximum}): The previous generation was interrupted. "
                 "Start a fresh, finite answer in the required format. Write each field or fact once and finish. "
                 "Preserve all approved requirements, character identities, explicit anatomy, scene constraints, "
                 "and fixed staging. Do not quote this correction or continue the interrupted text.")


class RunawayRecoveryError(BackendRunawayError):
    """A stage exhausted its shared call budget; incomplete output was discarded."""

    def __init__(self, stage, items, attempts, reason):
        self.stage, self.items, self.attempts, self.reason = stage, list(items), attempts, reason
        super().__init__(f"{stage} failed after {attempts} generation attempts ({reason}); interrupted output was discarded.")


def detection_reason(error):
    """Content-free reason: never copy the detected phrase or partial output to recovery logs."""
    if error.completion_state == "token_limit":
        return "token_limit"
    return "repetition_loop" if "repetition loop" in str(error).casefold() else "runaway_output_limit"


class GenerationRecovery:
    """One budget shared by all generation/validation attempts for a logical stage or item."""

    def __init__(self, stage, items=(), *, report=lambda detail: None, progress=lambda message: None):
        self.stage, self.items = stage, tuple(items)
        self.report, self.progress = report, progress
        self.attempts, self.loops = 0, 0
        self.reason = None
        self._finished = False
        self._children = {}

    @property
    def exhausted(self):
        return self.attempts >= MAX_ATTEMPTS

    @property
    def had_runaway(self):
        return bool(self.loops or any(child.had_runaway for child in self._children.values()))

    def invalid_output(self):
        self.finish("failed")
        return RunawayRecoveryError(self.stage, self.items, self.attempts, "invalid_output_after_recovery")

    def _record(self, outcome):
        self.report({"stage": self.stage, "items": list(self.items), "attempts": self.attempts,
                     "max_attempts": MAX_ATTEMPTS, "loop_detections": self.loops,
                     "reason": self.reason, "outcome": outcome})

    def finish(self, outcome):
        for child in self._children.values():
            child.finish(outcome)
        if self.loops and not self._finished:
            self._record(outcome)
            self._finished = True

    def generate(self, session, instruction, checkpoint=lambda: None):
        checkpoint = checkpoint or (lambda: None)
        while not self.exhausted:
            prompt = instruction
            if self.loops:
                seed = instruction.seed if type(instruction.seed) is int and instruction.seed >= 0 else 0
                prompt = replace(instruction,
                    system_message=instruction.system_message + RECOVERY_RULE.format(attempt=self.attempts + 1, maximum=MAX_ATTEMPTS),
                    seed=(seed + self.loops) % (2**32), temperature=.5 + .1 * self.loops, top_p=.9,
                    repeat_penalty=1.1 if instruction.model_family == "gemma" else instruction.repeat_penalty)
            try:
                checkpoint()
                self.attempts += 1
                session.validate_instruction(prompt)
                raw = session.generate(prompt)
                checkpoint()
                return raw
            except BackendRunawayError as error:
                # Cancellation/shutdown wins over a simultaneous loop signal, before any retry.
                try:
                    checkpoint()
                except Exception:
                    self.finish("aborted")
                    raise
                self.loops += 1
                self.reason = detection_reason(error)
                if not self.exhausted:
                    self._record("retrying")
                    self.progress(f"{self.stage} {list(self.items)}: {self.reason}; retrying generation "
                                  f"({self.attempts + 1}/{MAX_ATTEMPTS}).")
            except Exception:
                self.finish("aborted")
                raise
        if self.loops:
            self.finish("failed")
            raise RunawayRecoveryError(self.stage, self.items, self.attempts, self.reason)
        raise BackendGenerationError(f"{self.stage} exhausted its {MAX_ATTEMPTS}-attempt validation budget; no valid output was accepted.")

    def review_session(self, session, checkpoint):
        """Builder audits have their own stage budget, not a retry of the successful writer."""
        owner = self

        class ReviewSession:
            def __getattr__(self, name):
                return getattr(session, name)

            def generate(self, instruction):
                stage = instruction.diagnostic_stage.removesuffix(":format_retry")
                if stage not in owner._children:
                    owner._children[stage] = GenerationRecovery(stage, owner.items, report=owner.report, progress=owner.progress)
                return owner._children[stage].generate(session, instruction, checkpoint)

        return ReviewSession()
