"""市场情绪：恐惧与贪婪指数（alternative.me，无需 key）。"""
from __future__ import annotations

import datetime as dt
import logging

import httpx

from .. import config
from .market import BROWSER_HEADERS

log = logging.getLogger(__name__)


async def fetch_fear_greed(limit: int = 30) -> dict:
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, headers=BROWSER_HEADERS) as client:
        r = await client.get("https://api.alternative.me/fng/", params={"limit": str(limit)})
        r.raise_for_status()
        rows = r.json().get("data", [])
    if not rows:
        raise RuntimeError("恐贪指数返回空")
    series = [{
        "date": dt.datetime.fromtimestamp(int(x["timestamp"]), dt.UTC).strftime("%m-%d"),
        "value": int(x["value"]),
        "label": x["value_classification"],
    } for x in rows]
    series.reverse()  # 时间升序
    vals = [s["value"] for s in series]
    return {
        "current": series[-1],
        "avg_7d": sum(vals[-7:]) / min(7, len(vals)),
        "series": series,
        "source": "alternative.me",
    }
