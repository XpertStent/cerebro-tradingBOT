import threading
import time
import uuid
from copy import deepcopy

from app.services.ai_decision import ai_decision


class AIDecisionJobManager:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()

    def _now(self):
        return time.time()

    def start(
        self,
        *,
        run_type="MANUAL",
        enrich_research=True,
    ):
        run_id = "ai_" + uuid.uuid4().hex[:12]
        now = self._now()

        job = {
            "run_id": run_id,
            "status": "QUEUED",
            "stage": "QUEUED",
            "message": "Waiting to start",
            "run_type": str(run_type).upper(),
            "enrich_research": bool(enrich_research),
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[run_id] = job

        thread = threading.Thread(
            target=self._worker,
            kwargs={
                "run_id": run_id,
                "run_type": run_type,
                "enrich_research": enrich_research,
            },
            daemon=True,
        )
        thread.start()
        return self.progress(run_id)

    def _worker(
        self,
        *,
        run_id,
        run_type,
        enrich_research,
    ):
        # Avoid overlapping full portfolio-decision cycles. Research itself is
        # parallelized internally, but two entire decision runs should not race.
        with self._run_lock:
            self.update(
                run_id,
                status="RUNNING",
                stage="BUILDING_CONTEXT",
                started_at=self._now(),
                message=(
                    "Building decision context and research"
                    if enrich_research
                    else "Building decision context"
                ),
            )

            try:
                self.update(
                    run_id,
                    stage="DECIDING",
                    message="Generating structured portfolio intents",
                )

                result = ai_decision.run(
                    run_type=run_type,
                    enrich_research=enrich_research,
                )

                self.update(
                    run_id,
                    status="COMPLETE",
                    stage="COMPLETE",
                    finished_at=self._now(),
                    message="AI portfolio decision run complete",
                    result=result,
                )

            except Exception as exc:
                self.update(
                    run_id,
                    status="FAILED",
                    stage="FAILED",
                    finished_at=self._now(),
                    message="AI portfolio decision run failed",
                    error=str(exc),
                )

    def update(self, run_id, **values):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return
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
        if started:
            data["elapsed_seconds"] = round(
                (finished or self._now()) - started,
                1,
            )
        else:
            data["elapsed_seconds"] = 0.0

        return data

    def result(self, run_id):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job:
                return None

            return {
                "run_id": run_id,
                "status": job["status"],
                "stage": job["stage"],
                "error": job["error"],
                "result": deepcopy(job["result"]),
            }


ai_decision_jobs = AIDecisionJobManager()
