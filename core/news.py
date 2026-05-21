"""News fetcher for A-share stocks. Tencent news API, with graceful degradation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List

import requests

from core.market_data import _detect_market, get_realtime_quote


@dataclass
class NewsItem:
    title: str
    summary: str
    time: str
    source: str

    def to_line(self) -> str:
        return f"【{self.time}】{self.title}\n  {self.summary}（来源：{self.source}）"


@dataclass
class NewsBundle:
    code: str
    name: str
    items: List[NewsItem] = field(default_factory=list)
    source: str = ""

    def format(self) -> str:
        if not self.items:
            return f"{self.name}({self.code}) 暂无相关新闻数据。\n数据来源受限，请稍后重试或设置 USE_AKSHARE=1。"

        lines = [f"{self.name}({self.code}) 近期相关新闻（来源：{self.source}）：\n"]
        for item in self.items[:5]:
            lines.append(item.to_line())
        lines.append("\n⚠️ 新闻仅供参考，注意辨别信息真伪。")
        return "\n".join(lines)


def _fetch_tencent_news(code: str, limit: int = 5) -> List[NewsItem]:
    """Fetch news from Tencent stock page."""
    m = _detect_market(code)
    tc = f"{'sh' if m == 'SH' else 'sz'}{code}"
    url = f"https://qt.gtimg.cn/q={tc}"
    items: List[NewsItem] = []
    try:
        s = requests.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        # Try Tencent news API
        news_url = (
            f"https://proxy.finance.qq.com/ifzqgtimg/appstock/news/info/search"
            f"?symbol={tc}&limit={limit}"
        )
        r = s.get(news_url, timeout=8)
        if r.status_code != 200:
            return items
        data = r.json()
        news_list = data.get("data", {}).get("data", [])
        for n in news_list[:limit]:
            items.append(NewsItem(
                title=n.get("title", ""),
                summary=n.get("summary", "") or n.get("title", ""),
                time=n.get("time", "") or n.get("publish_time", ""),
                source=n.get("src", "腾讯财经"),
            ))
    except Exception:
        pass
    return items


def fetch_news(code: str, keyword: str = "", limit: int = 5) -> NewsBundle:
    # If code doesn't look like a stock code, treat it as a keyword search
    if not (len(code) == 6 and code.isdigit()):
        if not keyword:
            keyword = code
        code = ""
    q = get_realtime_quote(code) if code else None
    name = q.name if q else (code or keyword)

    # Try AKShare first if env is set
    import os

    if os.environ.get("USE_AKSHARE", "").lower() in ("1", "true", "yes") and code:
        try:
            import akshare as ak

            df = ak.stock_news_em(stock=code)
            if not df.empty:
                items = []
                for _, row in df.head(limit).iterrows():
                    items.append(NewsItem(
                        title=str(row.get("新闻标题", "")),
                        summary=str(row.get("新闻内容", ""))[:100],
                        time=str(row.get("发布时间", "")),
                        source="东方财富",
                    ))
                return NewsBundle(code=code, name=name, items=items, source="东方财富/AKShare")
        except Exception:
            pass

    # Fallback: Tencent (only if we have a valid code)
    if code:
        items = _fetch_tencent_news(code, limit=limit)
        if items:
            return NewsBundle(code=code, name=name, items=items, source="腾讯财经")

    return NewsBundle(code=code or keyword, name=name, items=[], source="无可用数据源")
