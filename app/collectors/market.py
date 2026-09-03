"""行情数据：K 线与 24 小时行情。

Binance 公开行情镜像（data-api.binance.vision，无需 key）为主源，
OKX 为备源，按 config.KLINE_SOURCES 顺序尝试。输出统一为内部格式。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from .. import config

log = logging.getLogger(__name__)

# 部分数据源（如 cointelegraph）会拦截默认 UA，统一伪装成浏览器
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

BINANCE_HOSTS = [
    "https://data-api.binance.vision",  # 公开行情镜像，多数网络可达
    "https://api.binance.com",
    "https://api1.binance.com",
]

# 统一 K 线: {ts(ms), open, high, low, close, volume, quote_volume}
Kline = dict


def _norm_symbol(symbol: str) -> str:
    """BTC / btcusdt / BTC-USDT → (binance: BTCUSDT, okx: BTC-USDT)"""
    s = symbol.strip().upper().replace("-", "").replace("/", "").replace("_", "")
    if not s.endswith("USDT"):
        s = s + "USDT"
    return s


def pair(symbol: str) -> tuple[str, str]:
    s = _norm_symbol(symbol)
    return s, f"{s[:-4]}-{s[-4:]}"  # BTCUSDT, BTC-USDT


async def _try_binance_klines(client: httpx.AsyncClient, bn_sym: str,
                              interval: str, limit: int) -> list[Kline]:
    mapping = {"1d": "1d", "4h": "4h", "1h": "1h", "1w": "1w"}
    bi = mapping[interval]
    last_err: Optional[Exception] = None
    for host in BINANCE_HOSTS:
        try:
            r = await client.get(
                f"{host}/api/v3/klines",
                params={"symbol": bn_sym, "interval": bi, "limit": limit},
            )
            r.raise_for_status()
            rows = r.json()
            return [{
                "ts": row[0], "open": float(row[1]), "high": float(row[2]),
                "low": float(row[3]), "close": float(row[4]),
                "volume": float(row[5]), "quote_volume": float(row[7]),
            } for row in rows]
        except Exception as e:  # 单域名失败换下一个
            last_err = e
    raise RuntimeError(f"binance klines 不可达: {last_err}")


async def _try_okx_klines(client: httpx.AsyncClient, okx_inst: str,
                          interval: str, limit: int) -> list[Kline]:
    mapping = {"1d": "1D", "4h": "4H", "1h": "1H", "1w": "1W"}
    bar = mapping[interval]
    r = await client.get(
        "https://www.okx.com/api/v5/market/candles",
        params={"instId": okx_inst, "bar": bar, "limit": str(min(limit, 300))},
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    rows = [{
        "ts": int(row[0]), "open": float(row[1]), "high": float(row[2]),
        "low": float(row[3]), "close": float(row[4]),
        "volume": float(row[5]), "quote_volume": float(row[7] if len(row) > 7 else 0),
    } for row in data]
    return list(reversed(rows))  # OKX 新的在前，统一为时间升序


async def fetch_klines(symbol: str, interval: str = "1d", limit: int = 120) -> tuple[list[Kline], str]:
    """返回 (K线列表(时间升序), 数据源名)。至少一个源成功即返回。"""
    bn_sym, okx_inst = pair(symbol)
    errors = []
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, headers=BROWSER_HEADERS) as client:
        for source in config.KLINE_SOURCES:
            try:
                if source == "binance":
                    rows = await _try_binance_klines(client, bn_sym, interval, limit)
                elif source == "okx":
                    rows = await _try_okx_klines(client, okx_inst, interval, limit)
                else:
                    continue
                if rows:
                    return rows, source
            except Exception as e:
                errors.append(f"{source}: {e}")
                log.warning("kline 源 %s 失败: %s", source, e)
    raise RuntimeError("所有 K 线数据源均失败: " + "; ".join(errors))


async def _try_binance_ticker(client: httpx.AsyncClient, bn_sym: str) -> dict:
    last_err = None
    for host in BINANCE_HOSTS:
        try:
            r = await client.get(f"{host}/api/v3/ticker/24hr", params={"symbol": bn_sym})
            r.raise_for_status()
            d = r.json()
            return {
                "last": float(d["lastPrice"]),
                "change_pct_24h": float(d["priceChangePercent"]),
                "high_24h": float(d["highPrice"]),
                "low_24h": float(d["lowPrice"]),
                "quote_volume_24h": float(d["quoteVolume"]),
            }
        except Exception as e:
            last_err = e
    raise RuntimeError(f"binance ticker 不可达: {last_err}")


async def _try_okx_ticker(client: httpx.AsyncClient, okx_inst: str) -> dict:
    r = await client.get(
        "https://www.okx.com/api/v5/market/ticker",
        params={"instId": okx_inst},
    )
    r.raise_for_status()
    rows = r.json().get("data", [])
    if not rows:
        raise RuntimeError("okx ticker 返回空")
    d = rows[0]
    last, open24h = float(d["last"]), float(d["open24h"])
    return {
        "last": last,
        "change_pct_24h": (last - open24h) / open24h * 100 if open24h else 0.0,
        "high_24h": float(d["high24h"]),
        "low_24h": float(d["low24h"]),
        "quote_volume_24h": float(d["volCcy24h"]),
    }


async def fetch_ticker(symbol: str) -> tuple[dict, str]:
    bn_sym, okx_inst = pair(symbol)
    errors = []
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, headers=BROWSER_HEADERS) as client:
        for source in config.KLINE_SOURCES:
            try:
                if source == "binance":
                    return await _try_binance_ticker(client, bn_sym), "binance"
                if source == "okx":
                    return await _try_okx_ticker(client, okx_inst), "okx"
            except Exception as e:
                errors.append(f"{source}: {e}")
                log.warning("ticker 源 %s 失败: %s", source, e)
    raise RuntimeError("所有行情源均失败: " + "; ".join(errors))


async def fetch_all(symbol: str) -> dict:
    """并行拉取多周期 K 线 + 24h 行情。"""
    results = await asyncio.gather(
        fetch_klines(symbol, "1d", 120),
        fetch_klines(symbol, "4h", 60),
        fetch_ticker(symbol),
        return_exceptions=True,
    )
    kline_d, kline_4h, ticker_r = results
    if isinstance(kline_d, Exception):
        raise RuntimeError(f"日 K 获取失败，无法继续: {kline_d}")
    return {
        "daily": kline_d[0], "daily_source": kline_d[1],
        "h4": None if isinstance(kline_4h, Exception) else kline_4h[0],
        "h4_source": None if isinstance(kline_4h, Exception) else kline_4h[1],
        "ticker": None if isinstance(ticker_r, Exception) else ticker_r[0],
        "ticker_source": None if isinstance(ticker_r, Exception) else ticker_r[1],
    }
