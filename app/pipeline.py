"""研究流水线：数据采集 → 指标计算 → 四维分析(LLM) → 综合研判 → 结构化报告。

设计原则：
- 每个数据源独立容错，缺源不缺报告（数据状态如实标注）；
- 客观指标全部本地算好再喂给模型，模型只做解读，不做“心算”；
- 未配置 LLM 时退化为“数据简报”模式，流水线仍然可用。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import uuid

from . import config
from . import indicators
from .collectors import derivatives, market, news, sentiment
from .llm import LLMNotConfigured, chat, parse_json
from . import report as report_store

log = logging.getLogger(__name__)

STAGES = [
    ("collect", "数据采集"),
    ("indicators", "指标计算"),
    ("roles", "多维分析（技术/资金/情绪/消息）"),
    ("synthesis", "综合研判"),
    ("report", "生成报告"),
]

ROLE_DEFS = [
    ("technical", "技术面分析师"),
    ("capital", "资金面分析师"),
    ("sentiment", "情绪面分析师"),
    ("news", "消息面分析师"),
]

_SYSTEM_PROMPT = (
    "你是严谨的加密货币研究员。只依据用户提供的数据做分析，"
    "数据中没有的事实不要臆造；所有数字引用必须来自数据。"
    "严格按要求的 JSON 格式输出，不要输出 JSON 以外的内容。"
)


def _fmt(v, nd=2, suffix=""):
    if v is None:
        return "无数据"
    if isinstance(v, float):
        return f"{v:.{nd}f}{suffix}"
    return f"{v}{suffix}"


def build_data_pack(symbol: str, data: dict, ind: dict, fng: dict | None,
                    deriv: dict | None, news_data: dict | None, question: str) -> str:
    t = data.get("ticker") or {}
    lines = [
        f"# 研究对象：{symbol.upper()}（现货 USDT 交易对）",
        f"数据时间：{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 行情速览",
        f"- 最新价：{_fmt(t.get('last'), t.get('last', 0) < 10 and 4 or 2)}",
        f"- 24h 涨跌：{_fmt(t.get('change_pct_24h'))}%，24h 高低：{_fmt(t.get('high_24h'))} / {_fmt(t.get('low_24h'))}",
        f"- 24h 成交额：{_fmt((t.get('quote_volume_24h') or 0) / 1e6)} 百万 USDT",
        f"- 7日/30日/90日涨跌：{_fmt(ind['change_pct'].get('7d'))}% / {_fmt(ind['change_pct'].get('30d'))}% / {_fmt(ind['change_pct'].get('90d'))}%",
        "",
        "## 技术指标（日线，本地计算）",
        f"- 趋势判断：{ind['trend_label']}",
        f"- 均线：MA7={_fmt(ind['ma']['ma7'])}，MA25={_fmt(ind['ma']['ma25'])}，MA99={_fmt(ind['ma']['ma99'])}",
        f"- RSI(14)：{_fmt(ind['rsi14'], 1)}（日线）｜4小时线 RSI：{_fmt(ind.get('rsi14_h4'), 1)}",
        f"- MACD：DIFF={_fmt(ind['macd'] and ind['macd']['diff'], 4)}，DEA={_fmt(ind['macd'] and ind['macd']['dea'], 4)}，柱={_fmt(ind['macd'] and ind['macd']['hist'], 4)}（前值 {_fmt(ind['macd'] and ind['macd']['hist_prev'], 4)}）" if ind["macd"] else "- MACD：样本不足",
        f"- 布林带：上轨 {_fmt(ind['bollinger'] and ind['bollinger']['upper'])}，中轨 {_fmt(ind['bollinger'] and ind['bollinger']['mid'])}，下轨 {_fmt(ind['bollinger'] and ind['bollinger']['lower'])}，带宽 {_fmt(ind['bollinger'] and ind['bollinger']['bandwidth_pct'], 1)}%" if ind["bollinger"] else "- 布林带：样本不足",
        f"- ATR(14)：{_fmt(ind['atr14'])}（占价格 {_fmt(ind['atr_pct'])}%）",
        f"- 30日年化波动率：{_fmt(ind['realized_vol_30d_annualized_pct'], 1)}%",
        f"- 量能：近7日成交额/近30日均值 = {_fmt(ind['volume_ratio_7d_vs_30d'])}",
        f"- 摆动阻力位：{', '.join(_fmt(x) for x in ind['levels']['resistances']) or '无明显摆动高点'}",
        f"- 摆动支撑位：{', '.join(_fmt(x) for x in ind['levels']['supports']) or '无明显摆动低点'}",
    ]

    if fng:
        cur = fng["current"]
        lines += ["", "## 市场情绪（恐惧贪婪指数）",
                  f"- 当前：{cur['value']}（{cur['label']}），7日均值 {_fmt(fng['avg_7d'], 0)}",
                  f"- 近30日走势：{' → '.join(str(s['value']) for s in fng['series'])}"]
    if deriv:
        base = symbol.upper().replace("USDT", "")
        oi_usd_b = (deriv.get("open_interest_usd") or 0) / 1e9
        lines += ["", "## 衍生品 / 资金面",
                  f"- 当前资金费率(8h)：{_fmt(deriv.get('funding_current_pct'), 4)}%",
                  f"- 近期资金费率均值：{_fmt(deriv.get('funding_avg_recent_pct'), 4)}%",
                  f"- 费率序列(最近20期,%)：{[round(x, 4) for x in deriv.get('funding_history_pct', [])]}",
                  f"- 永续合约持仓量：{_fmt(deriv.get('open_interest_base'), 0)} {base}"
                  + (f"（约 {oi_usd_b:.2f} 十亿 USD）" if deriv.get("open_interest_usd") else "")]
    if news_data:
        lines += ["", f"## 近期新闻标题（来源 {news_data['source']}）"]
        lines += [f"- [{n['published']}] {n['title']}" for n in news_data["items"]]

    if question:
        lines += ["", f"## 用户特别关注的问题\n{question}"]
    lines += ["", "注意：以上支撑/阻力、指标数值均为程序计算的事实，分析时直接引用。"]
    return "\n".join(lines)


_ROLE_INSTRUCTIONS = {
    "technical": "从技术面角度分析：趋势结构、均线系统、动量指标（RSI/MACD）、波动率与布林带位置、量价配合、关键支撑阻力。给出技术结论。",
    "capital": "从资金面角度分析：资金费率水平与趋势（多头/空头付费、是否过热）、永续合约持仓量含义、成交额变化（放量/缩量）、衍生品杠杆情绪。",
    "sentiment": "从情绪面角度分析：恐惧贪婪指数当前位置与近30日变化、极端程度、与价格走势的背离或共振。",
    "news": "从消息面角度分析：近期新闻标题的利好/利空倾向、宏观线索、事件驱动风险。标题信息有限，推断要保守。",
}

_ROLE_PROMPT = """{inst}

基于以下数据（只依据数据，不臆造）：

{data_pack}

输出 JSON（中文）：
{{
  "summary": "150字以内的本维度结论",
  "bullish": ["看多因素1", "..."],
  "bearish": ["看空因素1", "..."],
  "confidence": 0到100的整数，表示本维度信号的明确程度
}}"""

_SYNTH_PROMPT = """你是研究主管。综合四位分析师的结论与原始数据，给出最终研判。

# 原始数据
{data_pack}

# 四位分析师结论
{roles_json}

{question_block}

输出 JSON（中文）：
{{
  "headline": "一句话结论（30字内）",
  "bias": "偏多" | "偏空" | "震荡" | "观望" 四选一,
  "summary": "综合研判，300字以内，说明多空力量对比和关键依据",
  "plan": {{
    "entry_range": [入场区间下沿, 上沿]（价格数字）,
    "stop_loss": 止损价（数字）,
    "take_profit": [第一目标, 第二目标],
    "position_advice": "仓位建议（保守表述，如『轻仓试探，不超过 X%』）",
    "invalidation": "该研判失效的条件"
  }},
  "scenarios": {{
    "bull": "乐观情景及触发条件（60字内）",
    "base": "中性情景（60字内）",
    "bear": "悲观情景及触发条件（60字内）"
  }},
  "key_risks": ["风险1", "风险2", "风险3"],
  "confidence": 0到100整数
}}"""


def _question_block(question: str) -> str:
    return f"# 用户特别关注的问题\n{question}" if question else ""


def _fallback_role(role_key: str, role_name: str, err: str) -> dict:
    return {"summary": f"（{role_name}分析失败：{err}）", "bullish": [],
            "bearish": [], "confidence": 0, "error": True}


async def run_research(symbol: str, question: str = "", progress=None) -> dict:
    """执行完整研究流水线。progress: 可选的 async 回调 (stage_key, detail)。"""
    async def report_progress(stage, detail=""):
        if progress:
            await progress(stage, detail)

    # ---- 1. 数据采集（各源并行，独立容错）----
    await report_progress("collect", f"采集 {symbol.upper()} 行情/衍生品/情绪/新闻")
    tasks = {
        "market": market.fetch_all(symbol),
        "deriv": derivatives.fetch_derivatives(symbol),
        "fng": sentiment.fetch_fear_greed(30),
        "news": news.fetch_news(symbol),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    raw = dict(zip(tasks.keys(), results))

    data_status = {}
    for k, v in raw.items():
        data_status[k] = "ok" if not isinstance(v, Exception) else f"失败: {v}"
        if isinstance(v, Exception):
            log.warning("数据源 %s 失败: %s", k, v)
    if isinstance(raw["market"], Exception):
        raise RuntimeError(f"行情数据获取失败，无法研究: {raw['market']}")

    mkt, deriv, fng, news_data = raw["market"], raw.get("deriv"), raw.get("fng"), raw.get("news")
    if isinstance(deriv, Exception): deriv = None
    if isinstance(fng, Exception): fng = None
    if isinstance(news_data, Exception): news_data = None

    # ---- 2. 指标计算 ----
    await report_progress("indicators", "计算 MA/RSI/MACD/布林/ATR/支撑阻力")
    ind = indicators.analyze(mkt["daily"], mkt.get("h4"))
    data_pack = build_data_pack(symbol, mkt, ind, fng, deriv, news_data, question)

    # ---- 3. 四维分析（无 LLM 时降级为数据简报）----
    await report_progress("roles", "技术/资金/情绪/消息 四维分析")
    if not config.LLM_CONFIGURED:
        await report_progress("synthesis", "未配置 LLM，生成数据简报")
        roles = {k: {"summary": "（未配置 LLM_API_KEY，跳过模型分析）",
                     "bullish": [], "bearish": [], "confidence": 0, "error": True}
                 for k, _ in ROLE_DEFS}
        synthesis = None
    else:
        role_jobs = []
        for key, name in ROLE_DEFS:
            prompt = _ROLE_PROMPT.format(inst=_ROLE_INSTRUCTIONS[key], data_pack=data_pack)
            role_jobs.append(_run_role(key, name, prompt))
        role_results = await asyncio.gather(*role_jobs)
        roles = {key: res for (key, _), res in zip(ROLE_DEFS, role_results)}

        # ---- 4. 综合研判 ----
        await report_progress("synthesis", "研究主管综合研判")
        roles_for_prompt = {k: v for k, v in roles.items() if not v.get("error")}
        synth_prompt = _SYNTH_PROMPT.format(
            data_pack=data_pack,
            roles_json=json.dumps(roles_for_prompt, ensure_ascii=False, indent=1),
            question_block=_question_block(question),
        )
        try:
            content = await chat(
                [{"role": "system", "content": _SYSTEM_PROMPT},
                 {"role": "user", "content": synth_prompt}],
                temperature=0.2, max_tokens=2500)
            synthesis = parse_json(content)
        except Exception as e:
            log.error("综合研判失败: %s", e)
            synthesis = None

    # ---- 5. 组装报告 ----
    await report_progress("report", "保存报告")
    rep = {
        "id": dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
        "symbol": symbol.upper(),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "question": question or None,
        "ticker": mkt.get("ticker"),
        "indicators": ind,
        "fear_greed": fng,
        "derivatives": deriv,
        "news": news_data,
        "data_status": {
            "klines": f"ok ({mkt['daily_source']})",
            "klines_4h": (f"ok ({mkt['h4_source']})" if mkt.get("h4") else "失败/跳过"),
            "ticker": "ok" if mkt.get("ticker") else "失败",
            "derivatives": data_status["deriv"],
            "fear_greed": data_status["fng"],
            "news": data_status["news"],
        },
        "roles": {name: roles[key] for key, name in ROLE_DEFS},
        "synthesis": synthesis,
        "llm": config.llm_status(),
        "disclaimer": "本报告由程序聚合公开数据并经大模型解读生成，仅供研究参考，"
                      "不构成任何投资建议。加密货币波动剧烈，决策风险自负。",
    }
    report_store.save(rep)
    return rep


async def _run_role(key: str, name: str, prompt: str) -> dict:
    try:
        content = await chat(
            [{"role": "system", "content": _SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=1500)
        data = parse_json(content)
        return {"summary": str(data.get("summary", ""))[:500],
                "bullish": [str(x) for x in data.get("bullish", [])][:6],
                "bearish": [str(x) for x in data.get("bearish", [])][:6],
                "confidence": int(data.get("confidence", 0))}
    except Exception as e:
        return _fallback_role(key, name, str(e)[:120])
