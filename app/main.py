"""CoinLens 币透 — AI 加密货币研究台：FastAPI 入口。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, jobs, report as report_store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("coinlens")

app = FastAPI(title="CoinLens 币透", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class ResearchRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=20)
    question: str = Field(default="", max_length=500)


@app.post("/api/research")
async def start_research(req: ResearchRequest):
    symbol = req.symbol.strip().upper()
    job_id = jobs.create_job(symbol, req.question.strip())
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@app.get("/api/reports")
async def list_reports(limit: int = 100):
    return report_store.list_reports(min(limit, 500))


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    rep = report_store.get(report_id)
    if not rep:
        raise HTTPException(404, "报告不存在")
    return rep


@app.get("/api/status")
async def status():
    return {"llm": config.llm_status(),
            "kline_sources": config.KLINE_SOURCES,
            "deriv_sources": config.DERIV_SOURCES,
            "news": "cryptopanic" if config.CRYPTOPANIC_TOKEN else "cointelegraph-rss"}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8389, log_level="info")
