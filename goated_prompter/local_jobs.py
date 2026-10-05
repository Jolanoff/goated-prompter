"""Cooperative local jobs, transport activity, and cancellable result delivery.

This module has no HTTP or workflow dependencies. Job state is shared by the
event loop and generation worker, so mutations remain protected by an RLock.
"""

import copy
import threading
import time
import uuid

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
        """Capture the exact text exposed by the model transport for the live inspector."""
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        with self.lock:
            if self.released:
                return
            now = time.time()
            if event_type == "request":
                self._llm_request_sequence += 1
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
                    self.llm_trace["status"] = "receiving"
                    self.llm_trace["first_token_at"] = self.llm_trace["first_token_at"] or now
                    self.llm_trace["updated_at"] = now
                    if first:
                        self._append_event(
                            f"LLM request {self.llm_trace['request_number']} started returning text.",
                            "response",
                        )
            elif self.llm_trace is not None and event_type == "response_complete":
                self.llm_trace["status"] = "complete" if event.get("finish_reason") == "stop" else "interrupted"
                self.llm_trace["completion_state"] = "completed" if event.get("finish_reason") == "stop" else "interrupted"
                self.llm_trace["finish_reason"] = event.get("finish_reason")
                self.llm_trace["updated_at"] = now
                self.llm_trace["finished_at"] = now
                self._append_event(
                    f"LLM request {self.llm_trace['request_number']} completed with finish reason "
                    f"'{self.llm_trace['finish_reason']}'.",
                    "response",
                )
            elif event_type == "planning":
                self.progress = str(event.get("message") or "Planning scene…")
                self.progress_at = now
                self._append_event(self.progress, "planning")
            elif event_type == "error":
                message = str(event.get("message") or "The model transport failed.")
                if self.llm_trace is not None:
                    self.llm_trace["status"] = "error"
                    self.llm_trace["completion_state"] = event.get("completion_state", "provider_error")
                    self.llm_trace["partial_text"] = event.get("partial_text", self.llm_trace["output"])
                    self.llm_trace["finish_reason"] = event.get("finish_reason")
                    self.llm_trace["issue"] = message
                    self.llm_trace["updated_at"] = now
                    self.llm_trace["finished_at"] = now
                    if self.llm_trace["partial_text"]:
                        diagnostic = {key: self.llm_trace.get(key) for key in
                            ("request_number", "stage", "completion_state", "finish_reason", "partial_text", "issue")}
                        self.partial_responses = [row for row in self.partial_responses if row["request_number"] != diagnostic["request_number"]]
                        self.partial_responses.append(diagnostic)
                        del self.partial_responses[:-5]
                self._append_event(message, "error")
            else:
                return
            self.revision += 1

    def snapshot(self):
        with self.lock:
            return {"id": self.id, "status": self.status, "completion_state": self.completion_state, "revision": self.revision, "created_at": self.created_at,
                    "finished_at": self.finished_at, "result": copy.deepcopy(self.result), "error": self.error,
                    "kind": self.kind, "progress": self.progress, "progress_at": self.progress_at,
                    "status_reason": self.status_reason, "events": list(self.events),
                    "llm_trace": copy.deepcopy(self.llm_trace),
                    "partial_responses": copy.deepcopy(self.partial_responses),
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

    def deliver(self, result):
        """Deliver a result (or a durable-result factory) at a cancellable checkpoint."""
        while True:
            self.checkpoint()
            with self.lock:
                if not self.gate.is_set():
                    continue
                self.checkpoint()
                self.result = result() if callable(result) else result
                self.status = "succeeded"
                self.completion_state = "completed"
                self.status_reason = "Generation completed successfully."
                self._append_event(self.status_reason, "success")
                self.finished_at = time.time()
                self.revision += 1
                return

    def commit(self, operation, finish=False):
        """Serialize a durable result with cancellation, without waiting under the lock."""
        if finish:
            return self.deliver(operation)
        while True:
            self.checkpoint()
            with self.lock:
                if not self.gate.is_set():
                    continue
                self.checkpoint()
                return operation()


class JobCancelled(Exception):
    """A local generation was explicitly ended by the user."""
