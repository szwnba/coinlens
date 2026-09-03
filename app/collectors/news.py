"""新闻舆情：CryptoPanic（可选，需免费 token）→ Cointelegraph RSS（备，无需 key）。"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from .. import config
from .market import BROWSER_HEADERS, _norm_symbol

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 160) -> str:
    text = TAG_RE.sub("", text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


async def _cryptopanic(base: str, client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(
        "https://cryptopanic.com/api/free/v1/posts/",
        params={"auth_token": config.CRYPTOPANIC_TOKEN,
                "currencies": base, "public": "true", "filter": "hot"},
    )
    r.raise_for_status()
    posts = r.json().get("results", [])[:20]
    return [{
        "title": p.get("title", ""),
        "published": (p.get("published_at") or "")[:10],
        "source": "cryptopanic",
    } for p in posts]


async def _cointelegraph(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("https://cointelegraph.com/rss")
    r.raise_for_status()
    root = ET.fromstring(r.text)
    items = root.findall(".//item")
    out = []
    for it in items[:40]:
        title = (it.findtext("title") or "").strip()
        pub = (it.findtext("pubDate") or "")[:16]
        out.append({"title": title, "published": pub, "source": "cointelegraph"})
    return out


_KEYWORDS = {
    "BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana", "sol"], "BNB": ["bnb"], "XRP": ["xrp", "ripple"],
    "DOGE": ["dogecoin", "doge"], "ADA": ["cardano", "ada"],
    "AVAX": ["avalanche", "avax"], "LINK": ["chainlink", "link"],
}


async def fetch_news(symbol: str, max_items: int = 12) -> dict:
    base = _norm_symbol(symbol)[:-4]
    kw = [k.lower() for k in _KEYWORDS.get(base, [base, base.lower()])]
    errors = []
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, headers=BROWSER_HEADERS,
                                 follow_redirects=True) as client:
        items: list[dict] = []
        source = None
        if config.CRYPTOPANIC_TOKEN:
            try:
                items = await _cryptopanic(base, client)
                source = "cryptopanic"
            except Exception as e:
                errors.append(f"cryptopanic: {e}")
        if not items:
            try:
                all_items = await _cointelegraph(client)
                items = [x for x in all_items
                         if any(k in x["title"].lower() for k in kw)][:max_items]
                source = "cointelegraph"
                if not items:  # 没有该币的专属新闻就带几条头条，保持消息面上下文
                    items = all_items[:6]
            except Exception as e:
                errors.append(f"cointelegraph: {e}")
    if not items:
        raise RuntimeError("新闻源均失败: " + "; ".join(errors))
    return {"items": items[:max_items], "source": source,
            "filtered": source == "cointelegraph"}
