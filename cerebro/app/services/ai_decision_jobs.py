import threading
import time
import uuid
from copy import deepcopy

from app.services.ai_decision import ai_decision
from app.services.ai_execution import ai_execution
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
            # Quant occupies the first 55% of the end-to-end progress bar.
            job["percent"] = round(float(quant.get("percent") or 0) * 0.55, 1)
            job["message"] = quant.get("message") or job.get("message")

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
                    progress_callback=lambda **kwargs: self._quant_progress(
                        run_id, **kwargs
                    )
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
                )

                decision_bundle = ai_decision.run(
                    run_type=run_type,
                    enrich_research=enrich_research,
                )

                self.update(
                    run_id,
                    stage="RISK_PROPOSALS",
                    percent=88.0,
                    message="Converting AI intents into deterministic order proposals",
                )

                proposal_bundle = ai_execution.build(
                    context=decision_bundle["context"],
                    decision_result=decision_bundle["decision"],
                    memory_run_id=None,
                )

                result = {
                    "run_id": run_id,
                    "run_type": str(run_type).upper(),
                    "quant": {
                        "run_id": run_id,
                        "result": quant_result,
                    },
                    "ai": decision_bundle,
                    "execution": proposal_bundle,
                }

                if proposal_bundle.get("auto_execute"):
                    self.update(
                        run_id,
                        stage="AUTO_EXECUTION",
                        percent=94.0,
                        message="Auto-execution enabled: submitting approved paper proposals",
                    )
                    executed = []
                    for proposal in proposal_bundle.get("proposals") or []:
                        if proposal.get("status") == "PENDING_APPROVAL":
                            try:
                                executed.append(ai_execution.execute(proposal))
                            except Exception as exc:
                                failed = deepcopy(proposal)
                                failed["status"] = "EXECUTION_FAILED"
                                failed["message"] = str(exc)
                                executed.append(failed)
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
                    stage="AWAITING_APPROVAL" if not proposal_bundle.get("auto_execute") else "COMPLETE",
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
        if execution.get("approval_mode") == "AUTO":
            raise RuntimeError("This run used automatic execution and no approval is pending")

        updated = []
        for proposal in execution.get("proposals") or []:
            if proposal.get("status") == "PENDING_APPROVAL":
                updated.append(ai_execution.execute(proposal))
            else:
                updated.append(proposal)

        execution["proposals"] = updated
        execution["approval_mode"] = "MANUAL_APPROVED"
        result["execution"] = execution
        latest_ai_decision.save(run_id=run_id, result=result)
        self.update(
            run_id,
            stage="COMPLETE",
            message="AI decision approved and executable paper orders submitted",
            result=result,
        )
        return result

    def reject(self, run_id):
        payload = self.result(run_id)
        if not payload or not payload.get("result"):
            raise RuntimeError("AI run result not found")

        result = deepcopy(payload["result"])
        execution = result.get("execution") or {}
        if execution.get("approval_mode") == "AUTO":
            raise RuntimeError("This run used automatic execution and can no longer be rejected")

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
