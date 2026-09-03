"""本地技术指标计算（纯 Python，无 pandas 依赖）。

预先把客观数值算好再喂给 LLM，降低模型“心算”出错和幻觉的空间。
"""
from __future__ import annotations

from typing import Optional


def sma(values: list[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema_series(values: list[float], n: int) -> list[float]:
    if not values:
        return []
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[dict]:
    if len(closes) < slow + signal:
        return None
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    diff = [a - b for a, b in zip(ef, es)]
    dea = ema_series(diff, signal)
    hist = [a - b for a, b in zip(diff, dea)]
    return {"diff": diff[-1], "dea": dea[-1], "hist": hist[-1],
            "hist_prev": hist[-2] if len(hist) > 1 else 0.0}


def bollinger(closes: list[float], n: int = 20, k: float = 2.0) -> Optional[dict]:
    if len(closes) < n:
        return None
    win = closes[-n:]
    mid = sum(win) / n
    var = sum((x - mid) ** 2 for x in win) / n
    std = var ** 0.5
    return {"mid": mid, "upper": mid + k * std, "lower": mid - k * std,
            "bandwidth_pct": (4 * k * std / mid * 100) if mid else None}


def atr(klines: list[dict], n: int = 14) -> Optional[float]:
    if len(klines) < n + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i]["high"], klines[i]["low"], klines[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    val = sum(trs[:n]) / n
    for t in trs[n:]:
        val = (val * (n - 1) + t) / n
    return val


def swing_levels(klines: list[dict], lookback: int = 90, k: int = 3) -> dict:
    """分形摆动高低点：左右各 k 根都更低/更高则视为摆动点，取最近的阻力/支撑。"""
    data = klines[-lookback:]
    highs, lows = [], []
    for i in range(k, len(data) - k):
        window_h = [data[j]["high"] for j in range(i - k, i + k + 1) if j != i]
        window_l = [data[j]["low"] for j in range(i - k, i + k + 1) if j != i]
        if data[i]["high"] > max(window_h):
            highs.append(data[i]["high"])
        if data[i]["low"] < min(window_l):
            lows.append(data[i]["low"])
    last = data[-1]["close"]
    resistances = sorted([h for h in highs if h > last])[:3]
    supports = sorted([l for l in lows if l < last], reverse=True)[:3]
    return {"resistances": resistances, "supports": supports}


def realized_vol_pct(closes: list[float], n: int = 30) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(len(closes) - n, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return (var ** 0.5) * (365 ** 0.5) * 100  # 年化百分比


def analyze(klines: list[dict], h4: Optional[list[dict]] = None) -> dict:
    closes = [k["close"] for k in klines]
    vols = [k["quote_volume"] for k in klines]
    last = closes[-1]

    ma7, ma25, ma99 = sma(closes, 7), sma(closes, 25), sma(closes, 99)
    r14 = rsi(closes, 14)
    m = macd(closes)
    bb = bollinger(closes)
    a14 = atr(klines, 14)
    rv = realized_vol_pct(closes, 30)

    chg = {
        "7d": (last / closes[-8] - 1) * 100 if len(closes) > 8 else None,
        "30d": (last / closes[-31] - 1) * 100 if len(closes) > 31 else None,
        "90d": (last / closes[-91] - 1) * 100 if len(closes) > 91 else None,
    }

    if ma7 and ma25 and ma99:
        if last > ma7 > ma25 > ma99:
            trend = "多头排列（强势）"
        elif last < ma7 < ma25 < ma99:
            trend = "空头排列（弱势）"
        elif last > ma99:
            trend = "中线偏多，均线纠缠"
        else:
            trend = "震荡 / 方向不明"
    else:
        trend = "样本不足"

    vol_ratio = (sum(vols[-7:]) / 7) / (sum(vols[-30:]) / 30) if sum(vols[-30:]) else None

    h4_rsi = rsi([k["close"] for k in h4], 14) if h4 else None

    return {
        "last_close": last,
        "ma": {"ma7": ma7, "ma25": ma25, "ma99": ma99},
        "trend_label": trend,
        "rsi14": r14,
        "rsi14_h4": h4_rsi,
        "macd": m,
        "bollinger": bb,
        "atr14": a14,
        "atr_pct": (a14 / last * 100) if a14 else None,
        "realized_vol_30d_annualized_pct": rv,
        "change_pct": chg,
        "volume_ratio_7d_vs_30d": vol_ratio,
        "levels": swing_levels(klines),
    }
