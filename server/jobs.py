from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config_loader import resolve_config
from core.runner import run_generation

from server.paths import default_output_path, project_root

logger = logging.getLogger("white_generator.jobs")


@dataclass
class Job:
    job_id: str
    status: str = "queued"
    progress_done: int = 0
    progress_total: int = 0
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result_paths: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._persist_path = default_output_path() / ".ui_runs.json"
        self._max_persist = 30

    def create(self) -> Job:
        jid = uuid.uuid4().hex
        job = Job(job_id=jid)
        with self._lock:
            self._jobs[jid] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _append_log(self, job: Job, line: str) -> None:
        with self._lock:
            job.logs.append(line)
            if len(job.logs) > 500:
                job.logs = job.logs[-400:]

    def run_generate(self, job: Job, payload: dict[str, Any]) -> None:
        def worker() -> None:
            try:
                with self._lock:
                    job.status = "running"
                logger.info("job_started: job_id=%s payload=%s", job.job_id, payload)
                root = project_root()
                out_path = default_output_path()
                out_path.mkdir(parents=True, exist_ok=True)

                # Output path is fixed to project_root/output for UI jobs.
                overrides = {k: v for k, v in payload.items() if k != "output_dir"}

                cfg = resolve_config(None, overrides, root)
                cfg["output_path"] = out_path

                count = int(cfg.get("count") or 1)
                job.progress_total = count

                def on_progress(done: int, total: int, site_path: Path) -> None:
                    with self._lock:
                        job.progress_done = done
                    self._append_log(job, f"[{done}/{total}] {site_path.name}")

                paths = run_generation(cfg, on_progress=on_progress)
                job.result_paths = [str(p.resolve()) for p in paths]
                job.status = "done"
                logger.info("job_done: job_id=%s results=%s", job.job_id, len(job.result_paths))
                self._persist_snapshot(job, payload)
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                self._append_log(job, f"ERROR: {e}")
                logger.exception("job_error: job_id=%s error=%s", job.job_id, e)

        threading.Thread(target=worker, daemon=True).start()

    def _persist_snapshot(self, job: Job, payload: dict[str, Any]) -> None:
        try:
            default_output_path().mkdir(parents=True, exist_ok=True)
            entry = {
                "at": time.time(),
                "job_id": job.job_id,
                "payload": payload,
                "result_paths": job.result_paths,
            }
            rows: list[dict[str, Any]] = []
            if self._persist_path.is_file():
                with self._persist_path.open(encoding="utf-8") as f:
                    rows = json.load(f)
                if not isinstance(rows, list):
                    rows = []
            rows.insert(0, entry)
            rows = rows[: self._max_persist]
            with self._persist_path.open("w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def list_history(self) -> list[dict[str, Any]]:
        if not self._persist_path.is_file():
            return []
        try:
            with self._persist_path.open(encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []


store = JobStore()
