"""Cooperative local jobs, transport activity, and cancellable result delivery.

This module has no HTTP or workflow dependencies. Job state is shared by the
event loop and generation worker, so mutations remain protected by an RLock.
"""

import copy
import re
import threading
import time
import uuid
from .diagnostics import diagnostic_finish_reason, private_error_message

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.status = "running"
        self.completion_state = None
        self.revision = 0
        self.created_at = time.time()
        self.finished_at = None
        self.result = None
        self.error = None
        self.lock = threading.RLock()
        self._commit_lock = threading.RLock()
        self.gate = threading.Event()
        self.gate.set()
        self.stopping = False
        self.cancel_requested = False
        self.interrupt = None
        self.transport_interrupts = set()
        self.kind = "builder"
        self.progress = ""
        self.progress_at = self.created_at
        self.status_reason = "The job was accepted and is waiting for the generation worker."
        self.events = []
        self._event_sequence = 0
        self._llm_request_sequence = 0
        self.llm_trace = None
        self.partial_responses = []
        # Content-free per-stage accounting: calls, retries, errors, seconds and output size.
        self.llm_stages = {}
        self._llm_stage = None
        self.released = False
        self.workflow_revision = None
        self.input_signature = None
        self._append_event(self.status_reason, "status")

    def _append_event(self, message, event_type="info"):
        self._event_sequence += 1
        self.events.append({
            "id": self._event_sequence,
            "timestamp": time.time(),
            "type": event_type,
            "message": str(message),
        })
        del self.events[:-200]

    def record_event(self, message, event_type="info", *, revise=True):
        """Record bounded, user-safe runtime activity without exposing prompt contents."""
        with self.lock:
            self._append_event(message, event_type)
            if revise:
                self.revision += 1

    def set_progress(self, message):
        with self.lock:
            self.progress = message
            self.progress_at = time.time()
            self.status_reason = message
            self._append_event(message, "stage")
            self.revision += 1

    def record_llm_activity(self, event):
        """Capture the model transport for the live inspector.

        The trace stays in memory for the local UI. Private requests are flagged so exports omit their
        text, and checkpointed event messages never carry engine text that may echo private content.
        """
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        with self.lock:
            if self.released:
                return
            now = time.time()
            if event_type == "request":
                private_content = event.get("private_content") is True
                self._llm_request_sequence += 1
                stage, retry = _stage_key(event.get("stage"))
                stats = self.llm_stages.setdefault(stage, {"calls": 0, "retries": 0, "errors": 0, "seconds": 0.0,
                                                           "output_chars": 0, "reasoning_chars": 0})
                stats["calls"] += 1
                stats["retries"] += retry
                self._llm_stage = (stage, now)
                self.llm_trace = {
                    "request_number": self._llm_request_sequence,
                    "status": "waiting_first_token",
                    "model": str(event.get("model") or "unknown"),
                    "stage": event.get("stage"),
                    "messages": copy.deepcopy(event.get("messages") or []),
                    "parameters": copy.deepcopy(event.get("parameters") or {}),
                    "timeout_seconds": event.get("timeout_seconds"),
                    "output": "",
                    "reasoning": "",
                    "issue": "",
                    "started_at": now,
                    "first_token_at": None,
                    "updated_at": now,
                    "finished_at": None,
                    "finish_reason": None,
                }
                if private_content:
                    self.llm_trace["private_content"] = True
                self._append_event(
                    f"LLM request {self._llm_request_sequence} sent; waiting for the first response text.",
                    "request",
                )
            elif self.llm_trace is not None and event_type in {"response_delta", "reasoning_delta"}:
                field = "reasoning" if event_type == "reasoning_delta" else "output"
                text = str(event.get("text") or "")
                if text:
                    first = self.llm_trace["first_token_at"] is None
                    self.llm_trace[field] += text
                    if self._llm_stage:
                        self.llm_stages[self._llm_stage[0]][field + "_chars"] += len(text)
                    self.llm_trace["status"] = "receiving"
                    self.llm_trace["first_token_at"] = self.llm_trace["first_token_at"] or now
                    self.llm_trace["updated_at"] = now
                    if first:
                        self._append_event(
                            f"LLM request {self.llm_trace['request_number']} started returning text.",
                            "response",
                        )
            elif self.llm_trace is not None and event_type == "response_complete":
                self._finish_stage(now)
                finish_reason = diagnostic_finish_reason(event.get("finish_reason"), private_content=self.llm_trace.get("private_content"))
                self.llm_trace["status"] = "complete" if finish_reason == "stop" else "interrupted"
                self.llm_trace["completion_state"] = "completed" if finish_reason == "stop" else "interrupted"
                self.llm_trace["finish_reason"] = finish_reason
                self.llm_trace["updated_at"] = now
                self.llm_trace["finished_at"] = now
                self._append_event(
                    f"LLM request {self.llm_trace['request_number']} completed with finish reason "
                    f"'{finish_reason}'.",
                    "response",
                )
            elif event_type == "planning":
                self.progress = str(event.get("message") or "Planning scene…")
                self.progress_at = now
                self._append_event(self.progress, "planning")
            elif event_type == "error":
                self._finish_stage(now, error=True)
                message = str(event.get("message") or "The model transport failed.")
                private_content = self.llm_trace is not None and self.llm_trace.get("private_content") is True
                if private_content:
                    message = private_error_message(message)
                if self.llm_trace is not None:
                    self.llm_trace["status"] = "error"
                    self.llm_trace["completion_state"] = event.get("completion_state", "provider_error")
                    self.llm_trace["partial_text"] = event.get("partial_text", self.llm_trace["output"])
                    self.llm_trace["finish_reason"] = diagnostic_finish_reason(event.get("finish_reason"), private_content=private_content)
                    self.llm_trace["issue"] = message
                    self.llm_trace["updated_at"] = now
                    self.llm_trace["finished_at"] = now
                    if self.llm_trace["partial_text"]:
                        diagnostic = {key: self.llm_trace.get(key) for key in
                            ("request_number", "stage", "completion_state", "finish_reason", "partial_text", "issue")}
                        if private_content:
                            diagnostic["private_content"] = True
                        self.partial_responses = [row for row in self.partial_responses if row["request_number"] != diagnostic["request_number"]]
                        self.partial_responses.append(diagnostic)
                        del self.partial_responses[:-5]
                self._append_event(message, "error")
            else:
                return
            self.revision += 1

    def _finish_stage(self, now, *, error=False):
        if self._llm_stage:
            stage, started = self._llm_stage
            self.llm_stages[stage]["seconds"] = round(self.llm_stages[stage]["seconds"] + now - started, 3)
            self.llm_stages[stage]["errors"] += error
            self._llm_stage = None

    def _append_stage_summary(self):
        if self.llm_stages:
            self._append_event("Model calls by stage: " + "; ".join(
                f"{stage} {stats['calls']}" + (f" ({stats['retries']} retries)" if stats["retries"] else "")
                + (f" ({stats['errors']} errors)" if stats["errors"] else "") + f" {stats['seconds']:.1f}s"
                for stage, stats in self.llm_stages.items()), "summary")

    def snapshot(self):
        with self.lock:
            return {"id": self.id, "status": self.status, "completion_state": self.completion_state, "revision": self.revision, "created_at": self.created_at,
                    "finished_at": self.finished_at, "result": copy.deepcopy(self.result), "error": self.error,
                    "kind": self.kind, "progress": self.progress, "progress_at": self.progress_at,
                    "status_reason": self.status_reason, "events": list(self.events),
                    "llm_trace": copy.deepcopy(self.llm_trace),
                    "partial_responses": copy.deepcopy(self.partial_responses),
                    "llm_stages": copy.deepcopy(self.llm_stages),
                    "workflow_revision": self.workflow_revision, "input_signature": self.input_signature}

    def clear_private_data(self):
        """Release our references; this is not a secure RAM-erasure guarantee."""
        with self.lock:
            self.released = True
            self.result = self.llm_trace = self.error = self.interrupt = None
            self.events.clear()
            self.partial_responses.clear()
            self.transport_interrupts.clear()
            self.progress = self.status_reason = ""

    def checkpoint(self):
        while True:
            with self.lock:
                if self.cancel_requested:
                    raise JobCancelled()
                if self.stopping:
                    raise ValueError("Server is shutting down. Restart it and generate again.")
                if self.gate.is_set():
                    return
                if self.status != "paused":
                    self.status = "paused"
                    self.status_reason = "Paused at a safe checkpoint because a pause was requested. Resume the job to continue."
                    self._append_event(self.status_reason, "pause")
                    self.revision += 1
            self.gate.wait()

    def set_interrupt(self, interrupt):
        with self.lock:
            self.interrupt = interrupt
            cancelled = self.cancel_requested
        if cancelled:
            interrupt()

    def register_interrupt(self, interrupt):
        with self.lock:
            self.transport_interrupts.add(interrupt)
            stopped = self.cancel_requested or self.stopping
        if stopped:
            interrupt()

    def unregister_interrupt(self, interrupt):
        with self.lock:
            self.transport_interrupts.discard(interrupt)

    def interrupt_requests(self):
        with self.lock:
            interrupts = list(self.transport_interrupts)
            if not interrupts and self.interrupt is not None:
                interrupts.append(self.interrupt)
        for interrupt in interrupts:
            interrupt()

    def cancel(self):
        with self.lock:
            if self.status in TERMINAL:
                return self.snapshot()
            self.cancel_requested = True
            self.status = "cancelling"
            self.status_reason = (
                "Cancellation was requested. Waiting for the active model call to stop or reach a safe checkpoint."
            )
            self._append_event(self.status_reason, "cancel")
            self.gate.set()
            self.revision += 1
            snapshot = self.snapshot()
        self.interrupt_requests()
        return snapshot

    def request_pause(self):
        with self.lock:
            self.gate.clear()
            if self.status != "paused":
                self.status = "pause_requested"
                self.status_reason = (
                    "Pause requested. Live response text may continue to appear, but the active model call must "
                    "end before the job can pause at its next safe checkpoint."
                )
                self._append_event(self.status_reason, "pause")
            self.revision += 1

    def resume(self):
        with self.lock:
            self.status = "running"
            self.gate.set()
            self.status_reason = "Generation resumed and is continuing from the last safe checkpoint."
            self._append_event(self.status_reason, "status")
            self.revision += 1

    def mark_cancelled(self):
        """Record that the worker stopped because the user ended the job."""
        with self.lock:
            self.status = "cancelled"
            self.completion_state = "cancelled"
            self.status_reason = "Generation stopped because cancellation was requested."
            self._append_stage_summary()
            self._append_event(self.status_reason, "cancel")
            self.finished_at = time.time()
            self.revision += 1

    def mark_failed(self, error, completion_state="provider_error"):
        """Record a user-presentable failure; an interrupted completion keeps that status."""
        with self.lock:
            self.error = error
            self.completion_state = completion_state
            self.status = "interrupted" if completion_state == "interrupted" else "failed"
            self.status_reason = error
            self._append_stage_summary()
            self._append_event(error, "error")
            self.finished_at = time.time()
            self.revision += 1

    def mark_abandoned(self, error):
        """Final state for a worker that did not stop before server shutdown.

        The server is exiting, so no event or revision is published to pollers.
        """
        with self.lock:
            if self.status in TERMINAL:
                return
            self.status = "interrupted"
            self.completion_state = "interrupted"
            self.error = error
            self.finished_at = time.time()

    def deliver(self, result, reason=None):
        """Deliver a result (or a durable-result factory) at a cancellable checkpoint. reason replaces the default
        success message, e.g. to say that only part of the requested work was produced."""
        with self._commit_lock:
            self.checkpoint()
            # Persistence may finish after cancellation; never publish success then.
            # Keep its result across a pause without repeating durable side effects.
            value = result() if callable(result) else result
            while True:
                self.checkpoint()
                with self.lock:
                    if not self.gate.is_set():
                        continue
                    self.checkpoint()
                    self.result = value
                    self.status = "succeeded"
                    self.completion_state = "completed"
                    self.status_reason = reason or "Generation completed successfully."
                    self._append_stage_summary()
                    self._append_event(self.status_reason, "success")
                    self.finished_at = time.time()
                    self.revision += 1
                    return

    def commit(self, operation, finish=False, reason=None):
        """Serialize a durable result with cancellation, without waiting under the lock."""
        if finish:
            return self.deliver(operation, reason) if reason else self.deliver(operation)
        with self._commit_lock:
            self.checkpoint()
            value = operation()
            self.checkpoint()
            return value


_RETRY_SUFFIX = re.compile(r":(?:(?:output|loop|transport)_retry_\d+|(?:format|variety|loop|cast)_retry)$")


def _stage_key(stage):
    """Group retries under their stage and every numbered Dataset writer under one stage."""
    key, retry = str(stage or "final"), False
    while match := _RETRY_SUFFIX.search(key):
        key, retry = key[:match.start()], True
    return re.sub(r"^dataset:\d+$", "dataset:write", key), retry


class JobCancelled(Exception):
    """A local generation was explicitly ended by the user."""
