"""报告持久化：JSON 文件存储于 data/reports/。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def save(report: dict) -> Path:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / f"{report['id']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("报告已保存: %s", path.name)
    return path


def get(report_id: str) -> dict | None:
    path = config.REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_reports(limit: int = 100) -> list[dict]:
    if not config.REPORTS_DIR.exists():
        return []
    items = []
    for p in sorted(config.REPORTS_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            items.append({
                "id": r["id"], "symbol": r["symbol"],
                "generated_at": r["generated_at"],
                "bias": (r.get("synthesis") or {}).get("bias"),
                "headline": (r.get("synthesis") or {}).get("headline"),
                "last": (r.get("ticker") or {}).get("last"),
            })
        except Exception:
            log.warning("跳过损坏的报告文件: %s", p.name)
    return items
