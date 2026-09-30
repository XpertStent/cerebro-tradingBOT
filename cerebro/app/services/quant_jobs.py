import threading
import time
import uuid
from copy import deepcopy

from app.services.quant_screener import (
    quant_screener
)
from app.services.latest_quant import (
    latest_quant
)


class QuantJobManager:

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()

    def _now(self):
        return time.time()

    def start(
        self,
        final_limit=25,
        per_screen=40,
        deep_limit=60
    ):
        run_id = (
            "q_"
            + uuid.uuid4().hex[:12]
        )

        now = self._now()

        job = {
            "run_id": run_id,
            "status": "QUEUED",
            "stage": "QUEUED",

            "percent": 0.0,

            "discovered": 0,

            "processed": 0,
            "total": 0,

            "current_symbol": None,

            "snapshot_success": 0,
            "snapshot_failed": 0,

            "cache_hits": 0,
            "history_fetched": 0,

            "analysis_success": 0,
            "analysis_failures": 0,

            "rate_limit_waits": 0,

            "message":
                "Waiting to start",

            "created_at": now,
            "started_at": None,
            "finished_at": None,

            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[
                run_id
            ] = job

        thread = threading.Thread(
            target=self._worker,
            kwargs={
                "run_id": run_id,
                "final_limit":
                    final_limit,
                "per_screen":
                    per_screen,
                "deep_limit":
                    deep_limit,
            },
            daemon=True
        )

        thread.start()

        return self.progress(
            run_id
        )

    def _worker(
        self,
        run_id,
        final_limit,
        per_screen,
        deep_limit
    ):
        #
        # Prevent two full quant scans from
        # consuming Moomoo quota simultaneously.
        #
        with self._run_lock:

            self.update(
                run_id,
                status="RUNNING",
                stage="DISCOVERY",
                started_at=self._now(),
                message=(
                    "Running discovery screens"
                )
            )

            try:
                result = quant_screener.run(
                    final_limit=final_limit,
                    per_screen=per_screen,
                    deep_limit=deep_limit,
                    progress_callback=(
                        lambda **kwargs:
                        self.update(
                            run_id,
                            **kwargs
                        )
                    )
                )

                #
                # Persist the most recent successful
                # quant result for AI/context use.
                #
                latest_quant.save(
                    run_id=run_id,
                    result=result
                )

                self.update(
                    run_id,
                    status="COMPLETE",
                    stage="COMPLETE",
                    percent=100.0,
                    current_symbol=None,
                    finished_at=self._now(),
                    message="Quant scan complete",
                    result=result
                )

            except Exception as exc:

                self.update(
                    run_id,
                    status="FAILED",
                    stage="FAILED",
                    current_symbol=None,
                    finished_at=self._now(),
                    message="Quant scan failed",
                    error=str(exc)
                )

    def update(
        self,
        run_id,
        **values
    ):
        with self._lock:

            job = self._jobs.get(
                run_id
            )

            if not job:
                return

            job.update(
                values
            )

    def progress(
        self,
        run_id
    ):
        with self._lock:

            job = self._jobs.get(
                run_id
            )

            if not job:
                return None

            data = deepcopy(
                job
            )

        #
        # Don't return the potentially
        # huge final result from /progress.
        #
        data.pop(
            "result",
            None
        )

        started = data.get(
            "started_at"
        )

        finished = data.get(
            "finished_at"
        )

        if started:
            end = (
                finished
                or self._now()
            )

            data[
                "elapsed_seconds"
            ] = round(
                end - started,
                1
            )

        else:
            data[
                "elapsed_seconds"
            ] = 0.0

        processed = (
            data.get("processed")
            or 0
        )

        total = (
            data.get("total")
            or 0
        )

        if (
            total > 0
            and data.get("status")
            not in {
                "COMPLETE",
                "FAILED"
            }
        ):
            data["percent"] = round(
                min(
                    99.0,
                    (
                        processed
                        / total
                    ) * 100
                ),
                1
            )

        return data

    def result(
        self,
        run_id
    ):
        with self._lock:

            job = self._jobs.get(
                run_id
            )

            if not job:
                return None

            return {
                "run_id":
                    run_id,

                "status":
                    job["status"],

                "stage":
                    job["stage"],

                "error":
                    job["error"],

                "result":
                    deepcopy(
                        job["result"]
                    ),
            }


quant_jobs = QuantJobManager()
