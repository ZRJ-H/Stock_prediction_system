"""
新闻舆情获取模块（News Fetcher）
================================
获取 A 股近期相关新闻和公告。

数据源（按优先级）：
  1. 东方财富新闻（需 USE_AKSHARE=1）
  2. 腾讯财经新闻（免费，无需 API key）

设计原则：
  - 多源降级：腾讯不可用时不会报错，返回空列表
  - 支持代码查询和关键词查询两种模式
  - 获取失败不抛异常 → 返回空 NewsBundle
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

import requests

from core.market_data import _detect_market, get_realtime_quote

logger = logging.getLogger("stock_app.news")


@dataclass
class NewsItem:
    """单条新闻实体。"""
    title: str     # 新闻标题
    summary: str   # 新闻摘要
    time: str      # 发布时间
    source: str    # 来源媒体

    def to_line(self) -> str:
        """格式化为单行展示文本。"""
        return f"【{self.time}】{self.title}\n  {self.summary}（来源：{self.source}）"


@dataclass
class NewsBundle:
    """新闻查询结果包。"""
    code: str
    name: str
    items: List[NewsItem] = field(default_factory=list)
    source: str = ""

    def format(self) -> str:
        """格式化为可读的多行新闻列表。"""
        if not self.items:
            return (
                f"{self.name}({self.code}) 暂无相关新闻数据。\n"
                "数据来源受限，请稍后重试或设置 USE_AKSHARE=1。"
            )

        lines = [f"{self.name}({self.code}) 近期相关新闻（来源：{self.source}）：\n"]
        for item in self.items[:5]:  # 最多展示 5 条
            lines.append(item.to_line())
        lines.append("\n⚠️ 新闻仅供参考，注意辨别信息真伪。")
        return "\n".join(lines)


def _fetch_tencent_news(code: str, limit: int = 5) -> List[NewsItem]:
    """从腾讯财经 API 获取股票相关新闻。

    Args:
        code:  6 位股票代码
        limit: 最大条数

    Returns:
        NewsItem 列表（获取失败返回空列表）
    """
    m = _detect_market(code)
    tc = f"{'sh' if m == 'SH' else 'sz'}{code}"
    items: List[NewsItem] = []
    try:
        s = requests.Session()
        s.trust_env = False  # 关闭系统代理（避免某些环境网络问题）
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        # 腾讯财经新闻搜索接口
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
        logger.warning("腾讯新闻获取失败 code=%s", code, exc_info=True)
    return items


def fetch_news(code: str, keyword: str = "", limit: int = 5) -> NewsBundle:
    """获取股票新闻（支持代码查询和关键词查询）。

    Args:
        code:    6 位股票代码（非数字代码会被认为是关键词）
        keyword: 额外的搜索关键词（可选）
        limit:   最大新闻条数

    Returns:
        NewsBundle
    """
    # 智能判断：非数字代码 → 当作关键词
    if not (len(code) == 6 and code.isdigit()):
        if not keyword:
            keyword = code
        code = ""

    # 获取股票名称（用于展示）
    q = get_realtime_quote(code) if code else None
    name = q.name if q else (code or keyword)

    import os

    # 数据源 1：东方财富（需 AKShare）
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
            logger.warning("东方财富新闻获取失败 code=%s", code, exc_info=True)

    # 数据源 2：腾讯财经（降级）
    if code:
        items = _fetch_tencent_news(code, limit=limit)
        if items:
            return NewsBundle(code=code, name=name, items=items, source="腾讯财经")

    # 全部失败
    return NewsBundle(code=code or keyword, name=name, items=[], source="无可用数据源")
