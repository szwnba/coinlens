"""内存任务管理：研究任务后台执行，前端轮询进度。"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from . import pipeline

log = logging.getLogger(__name__)

_jobs: dict[str, dict] = {}
_tasks: set[asyncio.Task] = set()

STAGE_LABELS = dict((k, label) for k, label in pipeline.STAGES)


def create_job(symbol: str, question: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "symbol": symbol,
        "question": question,
        "status": "running",
        "stage": "collect",
        "stage_detail": "",
        "stages_done": [],
        "created_at": time.time(),
        "report_id": None,
        "error": None,
    }
    task = asyncio.get_running_loop().create_task(_run_job(job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_id


async def _run_job(job_id: str) -> None:
    job = _jobs[job_id]

    async def progress(stage: str, detail: str = "") -> None:
        job["stages_done"].append(stage)
        job["stage"] = stage
        job["stage_detail"] = detail

    try:
        rep = await pipeline.run_research(job["symbol"], job["question"] or "",
                                          progress=progress)
        job["stages_done"] = [k for k, _ in pipeline.STAGES]
        job["report_id"] = rep["id"]
        job["status"] = "done"
    except Exception as e:
        log.exception("研究任务 %s 失败", job_id)
        job["status"] = "error"
        job["error"] = str(e)[:500]


def get_job(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if not job:
        return None
    out = dict(job)
    out["stage_label"] = STAGE_LABELS.get(job["stage"], job["stage"])
    out["stages"] = [
        {"key": k, "label": label, "done": k in job["stages_done"]}
        for k, label in pipeline.STAGES
    ]
    return out
