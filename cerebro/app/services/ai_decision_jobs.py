import threading
import time
import uuid
from copy import deepcopy

from app.services.ai_decision import ai_decision
from app.services.ai_execution import ai_execution
from app.services.ai_memory import ai_memory
from app.services.ai_run_context import ai_run_context
from app.services.latest_ai_decision import latest_ai_decision
from app.services.latest_quant import latest_quant
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

    def start(self, *, run_type="MANUAL", enrich_research=None):
        if enrich_research is None:
            enrich_research = settings.get_bool("ai.research.enabled")

        with self._lock:
            active = next(
                (
                    job for job in self._jobs.values()
                    if job.get("status") in {"QUEUED", "RUNNING"}
                ),
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
                "research_ready": 0,
                "research_errors": 0,
                "message": "Not started",
            },
            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[run_id] = job

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
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return
            quant = job.setdefault("quant", {})
            quant.update(values)
            processed = int(quant.get("processed") or 0)
            total = int(quant.get("total") or 0)
            if total > 0:
                quant["percent"] = round(min(99.0, processed / total * 100.0), 1)
            job["percent"] = round(float(quant.get("percent") or 0) * 0.55, 1)
            job["message"] = quant.get("message") or job.get("message")

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

            try:
                quant_result = quant_screener.run(
                    progress_callback=lambda **kwargs: self._quant_progress(run_id, **kwargs)
                )
                latest_quant.save(run_id=run_id, result=quant_result)

                self.update(
                    run_id,
                    stage="RESEARCH_AND_CONTEXT",
                    percent=60.0,
                    message=(
                        "Building portfolio context and researching candidates"
                        if enrich_research
                        else "Building portfolio decision context"
                    ),
                    ai={
                        "stage": "RESEARCH_AND_CONTEXT",
                        "candidate_count": len(quant_result.get("candidates") or []),
                        "research_request_count": 0,
                        "research_ready": 0,
                        "research_errors": 0,
                        "message": "Preparing AI decision context",
                    },
                )

                context = ai_run_context.build(
                    run_type=run_type,
                    enrich_research=enrich_research,
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

                self.update(
                    run_id,
                    stage="DECISION_MODEL",
                    percent=82.0,
                    message="Generating structured portfolio decisions",
                    ai={
                        "stage": "DECISION_MODEL",
                        "candidate_count": len(context.get("candidates") or []),
                        "research_request_count": context.get("run", {}).get("research_request_count", 0),
                        "research_ready": research_ready,
                        "research_errors": research_errors,
                        "message": "Research/context complete; decision model running",
                    },
                )

                decision_bundle = ai_decision.run(
                    run_type=run_type,
                    enrich_research=enrich_research,
                    context=context,
                )

                self.update(
                    run_id,
                    stage="RISK_PROPOSALS",
                    percent=88.0,
                    message="Converting AI intents into deterministic order proposals",
                    ai={
                        "stage": "DECISION_COMPLETE",
                        "candidate_count": len(context.get("candidates") or []),
                        "research_request_count": context.get("run", {}).get("research_request_count", 0),
                        "research_ready": research_ready,
                        "research_errors": research_errors,
                        "message": "Decision model complete",
                    },
                )

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
                        message="Auto-execution enabled: submitting risk-approved paper proposals",
                    )
                    executed = []
                    for proposal in proposal_bundle.get("proposals") or []:
                        if proposal.get("status") == "PENDING_APPROVAL":
                            try:
                                executed.append(ai_execution.execute(proposal))
                            except Exception as exc:
                                executed.append(self._execution_failed(proposal, exc))
                        else:
                            executed.append(proposal)
                    result["execution"]["proposals"] = executed
                    result["execution"]["approval_mode"] = "AUTO"
                else:
                    result["execution"]["approval_mode"] = "MANUAL"

                latest_ai_decision.save(run_id=run_id, result=result)

                self.update(
                    run_id,
                    status="COMPLETE",
                    stage=(
                        "AWAITING_APPROVAL"
                        if not proposal_bundle.get("auto_execute")
                        else "COMPLETE"
                    ),
                    percent=100.0,
                    finished_at=self._now(),
                    message=(
                        "AI decision complete — review and approve or reject actionable proposals"
                        if not proposal_bundle.get("auto_execute")
                        else "AI decision and automatic paper execution complete"
                    ),
                    result=result,
                )

            except Exception as exc:
                self.update(
                    run_id,
                    status="FAILED",
                    stage="FAILED",
                    finished_at=self._now(),
                    message="AI portfolio workflow failed",
                    error=str(exc),
                )

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
            data = deepcopy(job)
        data.pop("result", None)
        started = data.get("started_at")
        finished = data.get("finished_at")
        data["elapsed_seconds"] = (
            round((finished or self._now()) - started, 1)
            if started
            else 0.0
        )
        return data

    def result(self, run_id):
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                return {
                    "run_id": run_id,
                    "status": job["status"],
                    "stage": job["stage"],
                    "error": job["error"],
                    "result": deepcopy(job["result"]),
                }

        persisted = latest_ai_decision.load()
        if persisted and persisted.get("run_id") == run_id:
            return {
                "run_id": run_id,
                "status": "COMPLETE",
                "stage": "PERSISTED",
                "error": None,
                "result": deepcopy(persisted.get("result")),
            }
        return None

    def latest(self):
        return latest_ai_decision.load()

    def clear_latest(self):
        latest_ai_decision.delete()
        return {"cleared": True}

    def approve(self, run_id):
        payload = self.result(run_id)
        if not payload or not payload.get("result"):
            raise RuntimeError("AI run result not found")

        result = deepcopy(payload["result"])
        execution = result.get("execution") or {}
        if execution.get("approval_mode") != "MANUAL":
            raise RuntimeError("This AI run is not awaiting manual approval")

        updated = []
        failures = 0
        for proposal in execution.get("proposals") or []:
            if proposal.get("status") == "PENDING_APPROVAL":
                try:
                    updated.append(ai_execution.execute(proposal))
                except Exception as exc:
                    failures += 1
                    updated.append(self._execution_failed(proposal, exc))
            else:
                updated.append(proposal)

        execution["proposals"] = updated
        execution["approval_mode"] = "MANUAL_APPROVED"
        execution["execution_failures"] = failures
        result["execution"] = execution
        latest_ai_decision.save(run_id=run_id, result=result)
        self.update(
            run_id,
            stage="COMPLETE",
            message=(
                "AI decision approved; eligible paper orders submitted"
                if failures == 0
                else f"AI decision approved with {failures} broker execution failure(s)"
            ),
            result=result,
        )
        return result

    def reject(self, run_id):
        payload = self.result(run_id)
        if not payload or not payload.get("result"):
            raise RuntimeError("AI run result not found")

        result = deepcopy(payload["result"])
        execution = result.get("execution") or {}
        if execution.get("approval_mode") != "MANUAL":
            raise RuntimeError("This AI run is not awaiting manual approval")

        updated = []
        for proposal in execution.get("proposals") or []:
            if proposal.get("status") == "PENDING_APPROVAL":
                updated.append(ai_execution.reject(proposal))
            else:
                updated.append(proposal)

        execution["proposals"] = updated
        execution["approval_mode"] = "MANUAL_REJECTED"
        result["execution"] = execution
        latest_ai_decision.save(run_id=run_id, result=result)
        self.update(
            run_id,
            stage="COMPLETE",
            message="AI decision rejected — no pending proposals were executed",
            result=result,
        )
        return result


ai_decision_jobs = AIDecisionJobManager()
