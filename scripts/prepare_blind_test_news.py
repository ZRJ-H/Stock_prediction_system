"""Download and normalize an offline Eastmoney news snapshot for 600519."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_OUTPUT = Path("data/blind_test/600519_news.jsonl")
SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def normalize_item(raw: dict[str, Any], fetched_at: str) -> dict[str, str] | None:
    published = str(raw.get("date", "")).strip()
    title = _strip_html(raw.get("title"))
    if not title:
        return None
    try:
        published_at = datetime.fromisoformat(published.replace("T", " ").replace("Z", ""))
    except ValueError:
        return None
    code = str(raw.get("code", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not url and code:
        url = f"https://finance.eastmoney.com/a/{code}.html"
    return {
        "symbol": "600519",
        "published_at": published_at.strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "summary": _strip_html(raw.get("content"))[:500],
        "source": _strip_html(raw.get("mediaName")) or "东方财富",
        "url": url,
        "fetched_at": fetched_at,
    }


def fetch_page(keyword: str, page_index: int, page_size: int = 50) -> list[dict[str, Any]]:
    callback = "blindNewsCallback"
    inner_param = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "time",
                "pageIndex": page_index,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    response = requests.get(
        SEARCH_URL,
        params={
            "cb": callback,
            "param": json.dumps(inner_param, ensure_ascii=False),
            "_": int(datetime.now().timestamp() * 1000),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://so.eastmoney.com/news/s?keyword={keyword}",
        },
        timeout=15,
    )
    response.raise_for_status()
    text = response.text.strip()
    match = re.match(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
    if not match:
        raise RuntimeError("东方财富新闻接口返回了无法识别的格式。")
    payload = json.loads(match.group(1))
    return payload.get("result", {}).get("cmsArticleWebOld", []) or []


def fetch_news(keyword: str, pages: int, page_size: int) -> list[dict[str, str]]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for page in range(1, pages + 1):
        raw_items = fetch_page(keyword, page, page_size)
        if not raw_items:
            break
        for raw in raw_items:
            item = normalize_item(raw, fetched_at)
            if item is None:
                continue
            key = (item["published_at"], item["title"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        if len(raw_items) < page_size:
            break
    return sorted(items, key=lambda item: item["published_at"])


def fetch_akshare_news(symbol: str) -> list[dict[str, str]]:
    """Use AKShare's maintained Eastmoney adapter when direct search is restricted."""
    try:
        import akshare as ak
    except ImportError:
        return []
    frame = ak.stock_news_em(symbol=symbol)
    if frame is None or frame.empty:
        return []
    fetched_at = datetime.now(timezone.utc).isoformat()
    items = []
    for _, row in frame.iterrows():
        item = normalize_item({
            "date": row.get("发布时间", ""),
            "title": row.get("新闻标题", ""),
            "content": row.get("新闻内容", ""),
            "mediaName": row.get("文章来源", ""),
            "url": row.get("新闻链接", ""),
        }, fetched_at)
        if item:
            items.append(item)
    unique = {(item["published_at"], item["title"]): item for item in items}
    return sorted(unique.values(), key=lambda item: item["published_at"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="准备贵州茅台历史盲测新闻快照")
    parser.add_argument("--keyword", default="600519")
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser


def main(argv: list[str] | None = None) -> Path:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    items = fetch_akshare_news(args.keyword)
    try:
        paged_items = fetch_news(args.keyword, args.pages, args.page_size)
    except (requests.RequestException, RuntimeError, json.JSONDecodeError):
        paged_items = []
    combined = {
        (item["published_at"], item["title"]): item
        for item in items + paged_items
    }
    items = sorted(combined.values(), key=lambda item: item["published_at"])
    if not items:
        raise RuntimeError("未抓取到可用新闻，保留现有快照不变。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
        encoding="utf-8",
    )
    print(f"已保存 {len(items)} 条真实新闻到 {output}")
    print(f"覆盖范围: {items[0]['published_at']} ~ {items[-1]['published_at']}")
    return output


if __name__ == "__main__":
    main()
