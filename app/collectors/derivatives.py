"""衍生品数据：资金费率与持仓量（OKX 主源 / Bybit 备源，均无需 key）。"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .. import config
from .market import BROWSER_HEADERS, pair

log = logging.getLogger(__name__)


async def _okx(symbol: str, client: httpx.AsyncClient) -> dict:
    _, okx_inst = pair(symbol)
    swap = okx_inst + "-SWAP"  # BTC-USDT-SWAP

    fund_cur, fund_hist, oi = await _gather_okx(client, swap)
    fund_cur, fund_hist, oi = _okx_json(fund_cur), _okx_json(fund_hist), _okx_json(oi)

    rates = []
    if fund_hist:
        rows = fund_hist.get("data", [])
        rates = [float(r["fundingRate"]) * 100 for r in rows]  # → 百分比
    cur_rate = None
    if fund_cur and fund_cur.get("data"):
        cur_rate = float(fund_cur["data"][0]["fundingRate"]) * 100
    if cur_rate is not None:
        rates = [cur_rate] + rates

    oi_val, oi_base, oi_usd = None, None, None
    if oi and oi.get("data"):
        d = oi["data"][0]
        oi_val = float(d.get("oi", 0)) or None          # 合约张数
        oi_base = float(d.get("oiCcy", 0)) or None      # 币本位持仓量
        oi_usd = float(d.get("oiUsd", 0)) or None       # USD 价值

    return {
        "funding_current_pct": cur_rate,
        "funding_avg_recent_pct": sum(rates) / len(rates) if rates else None,
        "funding_history_pct": rates[:20],
        "open_interest_contracts": oi_val,
        "open_interest_base": oi_base,
        "open_interest_usd": oi_usd,
        "source": "okx",
    }


async def _gather_okx(client, swap):
    import asyncio
    return await asyncio.gather(
        client.get("https://www.okx.com/api/v5/public/funding-rate",
                   params={"instId": swap}),
        client.get("https://www.okx.com/api/v5/public/funding-rate-history",
                   params={"instId": swap, "limit": "30"}),
        client.get("https://www.okx.com/api/v5/public/open-interest",
                   params={"instId": swap}),
    )


def _okx_json(resp) -> dict:
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("code")) != "0":
        raise RuntimeError(f"okx 业务错误: {data.get('msg')}")
    return data


async def _bybit(symbol: str, client: httpx.AsyncClient) -> dict:
    bn_sym, _ = pair(symbol)
    r = await client.get(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "linear", "symbol": bn_sym},
    )
    r.raise_for_status()
    rows = r.json().get("result", {}).get("list", [])
    if not rows:
        raise RuntimeError("bybit 返回空")
    d = rows[0]
    cur = float(d.get("fundingRate", 0)) * 100
    next_ts = d.get("nextFundingTime")
    oi_base = float(d.get("openInterest", 0)) or None
    return {
        "funding_current_pct": cur,
        "funding_avg_recent_pct": None,
        "funding_history_pct": [],
        "open_interest_contracts": None,
        "open_interest_base": oi_base,
        "open_interest_usd": None,
        "next_funding_ts": int(next_ts) if next_ts else None,
        "source": "bybit",
    }


async def fetch_derivatives(symbol: str) -> dict:
    errors = []
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, headers=BROWSER_HEADERS) as client:
        for source in config.DERIV_SOURCES:
            try:
                if source == "okx":
                    return await _okx(symbol, client)
                if source == "bybit":
                    return await _bybit(symbol, client)
            except Exception as e:
                errors.append(f"{source}: {e}")
                log.warning("衍生品源 %s 失败: %s", source, e)
    raise RuntimeError("衍生品数据源均失败: " + "; ".join(errors))
