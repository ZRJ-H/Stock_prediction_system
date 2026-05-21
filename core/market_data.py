from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
import requests


@dataclass
class StockQuote:
    code: str
    name: str
    market: str  # "SH" | "SZ"
    price: float
    open: float
    high: float
    low: float
    pre_close: float
    change_pct: float
    change_amount: float
    volume: int
    amount: float
    turnover: float
    pe: float
    pb: float
    total_mv: float
    time: str

    def to_dict(self) -> dict:
        return {
            "代码": self.code,
            "名称": self.name,
            "市场": self.market,
            "最新价": self.price,
            "今开": self.open,
            "最高": self.high,
            "最低": self.low,
            "昨收": self.pre_close,
            "涨跌幅": f"{self.change_pct:+.2f}%",
            "涨跌额": f"{self.change_amount:+.2f}",
            "成交量(手)": self.volume,
            "成交额": f"{self.amount:.2f}",
            "换手率": f"{self.turnover:.2f}%",
            "市盈率": f"{self.pe:.2f}" if self.pe > 0 else "亏损",
            "市净率": f"{self.pb:.2f}",
            "总市值": f"{self.total_mv:.2f}亿",
        }


@dataclass
class KlineBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


# ── Tencent real-time quote ──────────────────────────────

_TENCENT_QUOTE_FIELDS = [
    "market", "name", "code", "price", "pre_close", "open", "volume",
    "_1", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9", "_10",
    "_11", "_12", "_13", "_14", "_15", "_16", "_17", "_18", "_19",
    "_20", "_21", "_22", "_p0", "time", "change_amount", "change_pct",
    "high", "low", "price_volume", "volume_hand", "amount",
    "turnover", "pe", "_ps", "high_stop", "low_stop", "amplitude",
    "circulating_mv", "total_mv", "pb", "_23", "_24", "_25",
    "_26", "_27", "_28", "_29", "_30", "_31", "_32", "_33",
    "_34", "_35", "_36", "_37", "_38", "_39", "_40",
]


def _detect_market(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("0", "3", "2")):
        return "SZ"
    return "SZ"


def _code_to_tencent(code: str) -> str:
    m = _detect_market(code)
    return f"{'sh' if m == 'SH' else 'sz'}{code}"


def _parse_tencent_quote(raw: str) -> StockQuote:
    raw = raw.strip()
    if "=" in raw:
        raw = raw.split("=", 1)[1].strip('";\n ')
    parts = raw.split("~")
    vals: Dict[str, str] = {}
    for i, fname in enumerate(_TENCENT_QUOTE_FIELDS):
        vals[fname] = parts[i] if i < len(parts) else ""
    return StockQuote(
        code=vals["code"],
        name=vals["name"],
        market="SH" if vals.get("market") == "1" else "SZ",
        price=_f(vals, "price"),
        open=_f(vals, "open"),
        high=_f(vals, "high"),
        low=_f(vals, "low"),
        pre_close=_f(vals, "pre_close"),
        change_pct=_f(vals, "change_pct"),
        change_amount=_f(vals, "change_amount"),
        volume=int(_f(vals, "volume")),
        amount=_f(vals, "amount"),
        turnover=_f(vals, "turnover"),
        pe=_f(vals, "pe"),
        pb=_f(vals, "pb"),
        total_mv=_f(vals, "total_mv"),
        time=vals["time"],
    )


def _f(d: dict, key: str) -> float:
    try:
        return float(d.get(key, 0) or 0)
    except ValueError:
        return 0.0


def get_realtime_quote(code: str) -> Optional[StockQuote]:
    """Get real-time quote from Tencent API."""
    tc = _code_to_tencent(code)
    url = f"https://qt.gtimg.cn/q={tc}"
    try:
        r = _http().get(url, timeout=8)
        r.encoding = "gbk"
        if not r.text or "none" in r.text.lower():
            return None
        return _parse_tencent_quote(r.text)
    except Exception:
        return None


# ── Tencent daily K-line ─────────────────────────────────

def _parse_kline(raw) -> List[KlineBar]:
    bars: List[KlineBar] = []
    if isinstance(raw, list):
        for row in raw:
            if len(row) < 6:
                continue
            bars.append(KlineBar(
                date=row[0],
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=int(float(row[5])),
            ))
        return bars
    if isinstance(raw, str):
        for line in raw.strip().splitlines():
            parts = line.split(" ")
            if len(parts) < 6:
                continue
            bars.append(KlineBar(
                date=parts[0],
                open=float(parts[1]),
                close=float(parts[2]),
                high=float(parts[3]),
                low=float(parts[4]),
                volume=int(parts[5]),
            ))
    return bars


def get_daily_kline(code: str, days: int = 90) -> List[KlineBar]:
    """Get daily K-line from Tencent API."""
    m = _detect_market(code)
    tc = f"{'sh' if m == 'SH' else 'sz'}{code}"
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tc},day,,,{days + 5},qfq"
    )
    try:
        r = _http().get(url, timeout=10)
        data = r.json()
        klines = data.get("data", {}).get(tc, {})
        if isinstance(klines, dict):
            raw = klines.get("qfqday", "") or klines.get("day", "")
        else:
            raw = ""
        bars = _parse_kline(raw)
        return bars[-days:] if len(bars) > days else bars
    except Exception:
        return []


def kline_to_dataframe(bars: List[KlineBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame([b.to_dict() for b in bars])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ── Stock search (simple matching) ───────────────────────

_STOCK_LIST_CACHE: Optional[pd.DataFrame] = None


def _http() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    return s


def _load_stock_list() -> pd.DataFrame:
    global _STOCK_LIST_CACHE
    if _STOCK_LIST_CACHE is not None:
        return _STOCK_LIST_CACHE
    # Try AKShare first (if network is available), fall back to built-in list
    try:
        import os as _os
        if _os.environ.get("USE_AKSHARE", "").lower() in ("1", "true", "yes"):
            import akshare as ak
            df = ak.stock_info_a_code_name()
            df.columns = ["code", "name"]
            df["code"] = df["code"].astype(str).str.zfill(6)
            _STOCK_LIST_CACHE = df
            return df
    except Exception:
        pass
    # Fallback: use a built-in list of major A-share stocks
    except Exception:
        pass
    # Fallback: use a built-in list of major A-share stocks
    fallback = pd.DataFrame([
        ("000001", "平安银行"), ("000002", "万科A"), ("000063", "中兴通讯"),
        ("000333", "美的集团"), ("000651", "格力电器"), ("000725", "京东方A"),
        ("000858", "五粮液"), ("002230", "科大讯飞"), ("002415", "海康威视"),
        ("002594", "比亚迪"), ("300750", "宁德时代"), ("600000", "浦发银行"),
        ("600009", "上海机场"), ("600016", "民生银行"), ("600028", "中国石化"),
        ("600030", "中信证券"), ("600036", "招商银行"), ("600048", "保利发展"),
        ("600050", "中国联通"), ("600104", "上汽集团"), ("600276", "恒瑞医药"),
        ("600309", "万华化学"), ("600519", "贵州茅台"), ("600585", "海螺水泥"),
        ("600809", "山西汾酒"), ("600887", "伊利股份"), ("600900", "长江电力"),
        ("601012", "隆基绿能"), ("601088", "中国神华"), ("601166", "兴业银行"),
        ("601288", "农业银行"), ("601318", "中国平安"), ("601398", "工商银行"),
        ("601668", "中国建筑"), ("601857", "中国石油"), ("603259", "药明康德"),
        ("603288", "海天味业"), ("688981", "中芯国际"),
    ], columns=["code", "name"])
    _STOCK_LIST_CACHE = fallback
    return fallback


def search_stock(keyword: str, limit: int = 10) -> List[Dict[str, str]]:
    """Search stock by name or code."""
    df = _load_stock_list()
    keyword = keyword.strip()
    # Exact code match
    code_match = df[df["code"].str.fullmatch(keyword)]
    if not code_match.empty:
        name_match = df[df["name"].str.contains(keyword, case=False, na=False)]
        df = pd.concat([code_match, name_match]).drop_duplicates(subset=["code"])
    else:
        df = df[df["name"].str.contains(keyword, case=False, na=False) |
                df["code"].str.contains(re.escape(keyword), na=False)]
    return df.head(limit)[["code", "name"]].to_dict(orient="records")


def get_batch_quotes(codes: List[str]) -> List[StockQuote]:
    """Batch fetch real-time quotes (via Tencent)."""
    results: List[StockQuote] = []
    for code in codes:
        q = get_realtime_quote(code)
        if q:
            results.append(q)
    return results
