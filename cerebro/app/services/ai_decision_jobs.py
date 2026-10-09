import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from app.services.ai_decision import ai_decision
from app.services.ai_execution import ai_execution
from app.services.ai_memory import ai_memory
from app.services.ai_run_context import ai_run_context
from app.services.latest_ai_decision import latest_ai_decision, latest_decision_input
from app.services.latest_quant import latest_quant
from app.services.proposal_review import resolution_lock
from app.services.quant_screener import quant_screener
from app.services.settings import settings


class AIDecisionJobManager:
    """Own the complete quant -> research -> decision -> approval workflow."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()

    def _now(self):
        return time.time()

    def _iso_now(self):
        return datetime.now(timezone.utc).isoformat()

    def _event(self, run_id, stage, message, kind="INFO", symbol=None):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return
            events = job.setdefault("events", [])
            events.append({
                "id": uuid.uuid4().hex,
                "at": self._iso_now(),
                "stage": stage,
                "kind": kind,
                "message": message,
                "symbol": symbol,
            })
            if len(events) > 250:
                del events[:-250]

    def start(self, *, run_type="MANUAL", enrich_research=None):
        if enrich_research is None:
            enrich_research = settings.get_bool("ai.research.enabled")

        with self._lock:
            active = next(
                (job for job in self._jobs.values() if job.get("status") in {"QUEUED", "RUNNING"}),
                None,
            )
            if active:
                raise RuntimeError(
                    f"AI workflow {active['run_id']} is already {active['status'].lower()}"
                )

        run_id = "ai_" + uuid.uuid4().hex[:12]
        now = self._now()
        job = {
            "run_id": run_id,
            "status": "QUEUED",
            "stage": "QUEUED",
            "percent": 0.0,
            "message": "Waiting to start",
            "run_type": str(run_type).upper(),
            "enrich_research": bool(enrich_research),
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "events": [],
            "decision_input_available": False,
            "quant": {
                "stage": "QUEUED",
                "percent": 0.0,
                "processed": 0,
                "total": 0,
                "current_symbol": None,
                "message": "Not started",
            },
            "ai": {
                "stage": "QUEUED",
                "candidate_count": 0,
                "research_request_count": 0,
                "research_complete": 0,
                "research_ready": 0,
                "research_errors": 0,
                "research_current_symbol": None,
                "research_in_flight": 0,
                "research_symbols": {},
                "research_details": {},
                "model_started_at": None,
                "decision_web_research": None,
                "message": "Not started",
            },
            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[run_id] = job

        self._event(run_id, "QUEUED", "Manual AI workflow queued")

        threading.Thread(
            target=self._worker,
            kwargs={
                "run_id": run_id,
                "run_type": run_type,
                "enrich_research": bool(enrich_research),
            },
            daemon=True,
        ).start()
        return self.progress(run_id)

    def _quant_progress(self, run_id, **values):
        history = values.pop("history_analysis", None)
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return
            quant = job.setdefault("quant", {})
            previous_symbol = quant.get("current_symbol")
            quant.update(values)
            processed = int(quant.get("processed") or 0)
            total = int(quant.get("total") or 0)
            if total > 0:
                quant["percent"] = round(min(99.0, processed / total * 100.0), 1)
            job["percent"] = round(float(quant.get("percent") or 0) * 0.55, 1)
            job["message"] = quant.get("message") or job.get("message")
            current_symbol = quant.get("current_symbol")
            if history:
                # Update the same row so an open inspector survives live polling.
                event_id = f"history:{history['role']}:{history['symbol']}"
                events = job.setdefault("events", [])
                event = next((item for item in events if item.get("id") == event_id), None)
                if event is None:
                    event = {"id": event_id, "at": self._iso_now(), "stage": "QUANT", "symbol": history["symbol"]}
                    events.append(event)
                    if len(events) > 250:
                        del events[:-250]
                status = history["status"]
                event.update(
                    kind="ERROR" if status == "ERROR" else "SUCCESS" if status == "ANALYSED" else "INFO",
                    message=f"{'Benchmark' if history['role'] == 'BENCHMARK' else 'Historical'} analysis: {history['symbol']}",
                    details=deepcopy(history),
                )

        if not history and current_symbol and current_symbol != previous_symbol:
            self._event(run_id, "QUANT", f"Historical analysis: {current_symbol}", symbol=current_symbol)

    def _research_progress(self, run_id, **values):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return
            ai = job.setdefault("ai", {})
            total = int(values.get("total") or ai.get("research_request_count") or 0)
            complete = int(values.get("complete") or 0)
            ready = int(values.get("ready") or 0)
            errors = int(values.get("errors") or 0)
            symbol = values.get("current_symbol")
            status = values.get("status")

            ai.update({
                "stage": values.get("stage") or "RESEARCH",
                "research_request_count": total,
                "research_complete": complete,
                "research_ready": ready,
                "research_errors": errors,
                "research_current_symbol": symbol,
                "research_in_flight": int(values.get("in_flight") or 0),
                "message": (
                    f"Researching candidates: {complete}/{total} complete"
                    if total else "Preparing research"
                ),
            })
            details = ai.setdefault("research_details", {})
            if symbol:
                research_output = values.get("research_output")
                if isinstance(research_output, dict) and research_output.get("symbol") == symbol:
                    job.setdefault("research_outputs", {})[symbol] = deepcopy(research_output)
                ai.setdefault("research_symbols", {})[symbol] = status or "COMPLETE"
                details[symbol] = {
                    "symbol": symbol,
                    "status": status or "COMPLETE",
                    "cache": values.get("cache"),
                    "batch_number": values.get("batch_number"),
                    "error": values.get("error"),
                    "output_available": symbol in job.get("research_outputs", {}),
                }
            elif status == "RETRY":
                for batch_symbol in values.get("batch_symbols") or []:
                    ai.setdefault("research_symbols", {})[batch_symbol] = "RETRY"
                    details[batch_symbol] = {
                        "symbol": batch_symbol,
                        "status": "RETRY",
                        "batch_number": values.get("batch_number"),
                        "attempt": values.get("attempt"),
                        "max_attempts": values.get("max_attempts"),
                        "delay_seconds": values.get("delay_seconds"),
                        "retry_source": values.get("retry_source"),
                        "error": values.get("error"),
                    }

            research_fraction = (complete / total) if total else 0.0
            job["percent"] = round(60.0 + research_fraction * 20.0, 1)
            job["message"] = ai["message"]

        if symbol:
            self._event(
                run_id,
                "RESEARCH",
                f"{symbol}: {status or 'complete'} ({complete}/{total})",
                kind="ERROR" if status == "ERROR" else "INFO",
                symbol=symbol,
            )
        elif status == "RETRY":
            self._event(
                run_id,
                "RESEARCH_RETRY",
                f"Research batch retry {values.get('attempt')}/{values.get('max_attempts')} in {values.get('delay_seconds')}s",
                kind="INFO",
            )

    def _capture_decision_input(self, run_id, snapshot):
        # Only the JSON request body is captured; client credentials stay outside it.
        latest_decision_input.save(run_id=run_id, result=snapshot)
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job["decision_input"] = deepcopy(snapshot)
                job["decision_input_available"] = True

    def decision_input(self, run_id):
        with self._lock:
            job = self._jobs.get(run_id)
            if job and job.get("decision_input"):
                return {"run_id": run_id, "snapshot": deepcopy(job["decision_input"])}
        captured = latest_decision_input.load()
        if captured and captured.get("run_id") == run_id:
            return {"run_id": run_id, "snapshot": captured["result"]}
        stored = latest_ai_decision.load()
        if stored and stored.get("run_id") == run_id:
            snapshot = ((stored.get("result") or {}).get("ai") or {}).get("request_snapshot")
            if snapshot:
                return {"run_id": run_id, "snapshot": snapshot}
        return None

    def _decision_retry_progress(self, run_id, **values):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return
            ai = job.setdefault("ai", {})
            ai["stage"] = "DECISION_RETRY"
            ai["decision_retry"] = deepcopy(values)
            ai["message"] = (
                f"Decision request rate-limited/transiently failed; retrying in "
                f"{values.get('delay_seconds')}s"
            )
            job["message"] = ai["message"]
        self._event(
            run_id,
            "DECISION_RETRY",
            f"Retrying final decision request in {values.get('delay_seconds')}s",
            kind="INFO",
        )

    def _execution_failed(self, proposal, exc):
        failed = deepcopy(proposal)
        failed["status"] = "EXECUTION_FAILED"
        failed["message"] = str(exc)
        decision_id = failed.get("decision_id")
        if decision_id:
            try:
                ai_memory.set_execution_result(
                    decision_id,
                    status="DEFERRED",
                    broker_status=f"EXECUTION_ERROR: {exc}",
                )
            except Exception:
                pass
        return failed

    def _worker(self, *, run_id, run_type, enrich_research):
        with self._run_lock:
            self.update(
                run_id,
                status="RUNNING",
                stage="QUANT",
                percent=1.0,
                started_at=self._now(),
                message="Running fresh quant discovery and historical analysis",
            )
            self._event(run_id, "QUANT", "Fresh quant discovery started")

            try:
                quant_result = quant_screener.run(
                    progress_callback=lambda **kwargs: self._quant_progress(run_id, **kwargs)
                )
                latest_quant.save(run_id=run_id, result=quant_result)

                with self._lock:
                    job = self._jobs.get(run_id)
                    if job:
                        quant = job.setdefault("quant", {})
                        quant.update({
                            "stage": "COMPLETE",
                            "percent": 100.0,
                            "processed": int(quant.get("total") or quant.get("processed") or 0),
                            "current_symbol": None,
                            "message": f"Quant complete: {len(quant_result.get('candidates') or [])} candidates",
                        })
                self._event(
                    run_id,
                    "QUANT",
                    f"Quant complete with {len(quant_result.get('candidates') or [])} final candidates",
                )

                self.update(
                    run_id,
                    stage="RESEARCH_AND_CONTEXT",
                    percent=60.0,
                    message=(
                        "Building portfolio context and researching candidates"
                        if enrich_research else "Building portfolio decision context"
                    ),
                    ai={
                        "stage": "RESEARCH_AND_CONTEXT",
                        "candidate_count": len(quant_result.get("candidates") or []),
                        "research_request_count": 0,
                        "research_complete": 0,
                        "research_ready": 0,
                        "research_errors": 0,
                        "research_current_symbol": None,
                        "research_in_flight": 0,
                        "research_symbols": {},
                        "research_details": {},
                        "model_started_at": None,
                        "decision_web_research": None,
                        "message": "Preparing AI decision context",
                    },
                )
                self._event(run_id, "RESEARCH_AND_CONTEXT", "Building portfolio and memory context")

                context = ai_run_context.build(
                    run_type=run_type,
                    enrich_research=enrich_research,
                    research_progress_callback=(
                        (lambda **kwargs: self._research_progress(run_id, **kwargs))
                        if enrich_research else None
                    ),
                )

                research_candidates = [
                    item for item in (context.get("candidates") or [])
                    if item.get("research_context") is not None
                ]
                research_ready = sum(
                    1 for item in research_candidates
                    if (item.get("research_context") or {}).get("status") == "READY"
                )
                research_errors = sum(
                    1 for item in research_candidates
                    if (item.get("research_context") or {}).get("status") == "ERROR"
                )
                research_request_count = context.get("run", {}).get("research_request_count", 0)
                research_symbols = {
                    item.get("symbol"): (item.get("research_context") or {}).get("status", "UNKNOWN")
                    for item in research_candidates if item.get("symbol")
                }
                research_details = {
                    item.get("symbol"): deepcopy(item.get("research_context") or {})
                    for item in research_candidates if item.get("symbol")
                }

                model_started_at = self._now()
                decision_web_enabled = settings.get_bool("ai.decision.web_search_enabled")
                self.update(
                    run_id,
                    stage="DECISION_MODEL",
                    percent=82.0,
                    message=(
                        "Decision model + independent web verification active — generating structured portfolio decisions"
                        if decision_web_enabled
                        else "Decision model request active — generating structured portfolio decisions"
                    ),
                    ai={
                        "stage": "DECISION_MODEL",
                        "candidate_count": len(context.get("candidates") or []),
                        "research_request_count": research_request_count,
                        "research_complete": len(research_candidates),
                        "research_ready": research_ready,
                        "research_errors": research_errors,
                        "research_current_symbol": None,
                        "research_in_flight": 0,
                        "research_symbols": research_symbols,
                        "research_details": research_details,
                        "model_started_at": model_started_at,
                        "decision_web_research": {
                            "enabled": decision_web_enabled,
                            "status": "RUNNING" if decision_web_enabled else "DISABLED",
                        },
                        "message": "Research/context complete; decision model request is running",
                    },
                )
                self._event(
                    run_id,
                    "DECISION_MODEL",
                    (
                        f"Decision model started for {len(context.get('candidates') or [])} candidates "
                        f"with {'live web verification' if decision_web_enabled else 'web search disabled'}"
                    ),
                )

                decision_bundle = ai_decision.run(
                    run_type=run_type,
                    enrich_research=enrich_research,
                    context=context,
                    retry_callback=lambda **kwargs: self._decision_retry_progress(run_id, **kwargs),
                    request_callback=lambda snapshot: self._capture_decision_input(run_id, snapshot),
                )
                self._event(
                    run_id,
                    "DECISION_MODEL",
                    f"Decision model complete with {len(decision_bundle.get('decision', {}).get('decisions') or [])} decisions",
                )

                self.update(
                    run_id,
                    stage="RISK_PROPOSALS",
                    percent=88.0,
                    message="Converting AI intents into deterministic decision proposals",
                    ai={
                        "stage": "DECISION_COMPLETE",
                        "candidate_count": len(context.get("candidates") or []),
                        "research_request_count": research_request_count,
                        "research_complete": len(research_candidates),
                        "research_ready": research_ready,
                        "research_errors": research_errors,
                        "research_current_symbol": None,
                        "research_in_flight": 0,
                        "research_symbols": research_symbols,
                        "research_details": research_details,
                        "model_started_at": model_started_at,
                        "decision_web_research": decision_bundle.get("decision_web_research"),
                        "message": "Decision model complete",
                    },
                )
                self._event(run_id, "RISK_PROPOSALS", "Deterministic sizing and risk evaluation started")

                proposal_bundle = ai_execution.build(
                    context=context,
                    decision_result=decision_bundle["decision"],
                    memory_run_id=None,
                )

                result = {
                    "run_id": run_id,
                    "run_type": str(run_type).upper(),
                    "quant": {"run_id": run_id, "result": quant_result},
                    "ai": decision_bundle,
                    "execution": proposal_bundle,
                }

                if proposal_bundle.get("auto_execute"):
                    self.update(
                        run_id,
                        stage="AUTO_EXECUTION",
                        percent=94.0,
                        message="Auto-execution enabled: applying approved AI decisions",
                    )
                    self._event(run_id, "AUTO_EXECUTION", "Automatic AI decision application enabled for this run")
                    executed = []
                    for proposal in proposal_bundle.get("proposals") or []:
                        if proposal.get("status") == "PENDING_APPROVAL":
                            try:
                                executed.append(ai_execution.approve(proposal))
                            except Exception as exc:
                                executed.append(self._execution_failed(proposal, exc))
                        else:
                            executed.append(proposal)
                    result["execution"]["proposals"] = executed
                    result["execution"]["approval_mode"] = "AUTO"
                else:
                    result["execution"]["approval_mode"] = "MANUAL"

                with resolution_lock():
                    latest_ai_decision.save(run_id=run_id, result=result)

                final_stage = "AWAITING_APPROVAL" if not proposal_bundle.get("auto_execute") else "COMPLETE"
                final_message = (
                    "AI decision complete — review and approve or reject actionable decisions"
                    if not proposal_bundle.get("auto_execute")
                    else "AI decisions and automatic PAPER/watchlist actions complete"
                )
                self.update(
                    run_id,
                    status="COMPLETE",
                    stage=final_stage,
                    percent=100.0,
                    finished_at=self._now(),
                    message=final_message,
                    result=result,
                )
                self._event(run_id, final_stage, final_message, kind="SUCCESS")

            except Exception as exc:
                self.update(
                    run_id,
                    status="FAILED",
                    stage="FAILED",
                    finished_at=self._now(),
                    message="AI portfolio workflow failed",
                    error=str(exc),
                )
                self._event(run_id, "FAILED", str(exc), kind="ERROR")

    def update(self, run_id, **values):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                job.update(values)

    def progress(self, run_id):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return None
            data = deepcopy({k: v for k, v in job.items() if k not in {"result", "decision_input", "research_outputs"}})
        started = data.get("started_at")
        finished = data.get("finished_at")
        data["elapsed_seconds"] = round((finished or self._now()) - started, 1) if started else 0.0
        model_started = (data.get("ai") or {}).get("model_started_at")
        if model_started:
            data["ai"]["model_elapsed_seconds"] = round((finished or self._now()) - model_started, 1)
        else:
            data["ai"]["model_elapsed_seconds"] = 0.0
        return data

    def research_output(self, run_id, symbol):
        symbol = str(symbol).upper()
        with self._lock:
            output = (self._jobs.get(run_id, {}).get("research_outputs") or {}).get(symbol)
            if output is not None:
                return {"run_id": run_id, "symbol": symbol, "output": deepcopy(output)}
        # Completed results and captured decision inputs survive worker restarts.
        stored = latest_ai_decision.load()
        context = ((stored.get("result") or {}).get("ai") or {}).get("context") if stored and stored.get("run_id") == run_id else None
        if context is None:
            captured = latest_decision_input.load()
            context = (captured.get("result") or {}).get("context") if captured and captured.get("run_id") == run_id else None
        for candidate in (context or {}).get("candidates") or []:
            if candidate.get("symbol") == symbol and candidate.get("research_context") is not None:
                return {"run_id": run_id, "symbol": symbol, "output": deepcopy(candidate["research_context"])}
        return None

    def result(self, run_id):
        # The atomic persisted result is authoritative across API workers.
        persisted = latest_ai_decision.load()
        if persisted and persisted.get("run_id") == run_id:
            return {"run_id": run_id, "status": "COMPLETE", "stage": "PERSISTED",
                    "error": None, "result": deepcopy(persisted.get("result"))}
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                return {"run_id": run_id, "status": job["status"], "stage": job["stage"],
                        "error": job["error"], "result": deepcopy(job["result"])}
        return None

    def latest(self):
        with self._lock:
            active = [
                job for job in self._jobs.values()
                if job.get("status") in {"QUEUED", "RUNNING"}
            ]
            if active:
                newest = max(active, key=lambda item: float(item.get("created_at") or 0))
                data = deepcopy({k: v for k, v in newest.items() if k not in {"result", "decision_input", "research_outputs"}})
                started = data.get("started_at")
                if started:
                    data["elapsed_seconds"] = round(self._now() - started, 1)
                return data
        stored = latest_ai_decision.load()
        captured = latest_decision_input.load()
        if captured and (not stored or captured.get("run_id") != stored.get("run_id")):
            # A failed/interrupted request remains inspectable after reload/restart.
            run_id = captured["run_id"]
            progress = self.progress(run_id)
            return progress or {
                "run_id": run_id,
                "status": "INPUT_CAPTURED",
                "stage": "REQUEST_CAPTURED",
                "decision_input_available": True,
                "message": "Decision input captured; no completed result is available for this run.",
            }
        return stored

    def clear_latest(self):
        with resolution_lock():
            latest_ai_decision.delete()
            latest_decision_input.delete()
            self.clear_decision_inputs()
        return {"cleared": True}

    def clear_decision_inputs(self):
        with self._lock:
            for job in self._jobs.values():
                job.pop("decision_input", None)
                job.pop("research_outputs", None)
                for detail in (job.get("ai", {}).get("research_details") or {}).values():
                    detail["output_available"] = False
                job["decision_input_available"] = False
                ai = (job.get("result") or {}).get("ai") or {}
                ai.pop("request_snapshot", None)

    def approve(self, run_id):
        from app.api.ai_decision import _legacy_batch
        return _legacy_batch(run_id, "approve")

    def reject(self, run_id, reason=None):
        from app.api.ai_decision import _legacy_batch
        return _legacy_batch(run_id, "reject", reason)


ai_decision_jobs = AIDecisionJobManager()
