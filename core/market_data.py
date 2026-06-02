"""
行情数据层（Market Data Layer）
===============================
封装 A 股行情数据获取逻辑，全部基于腾讯免费 API（无需注册/密钥）：
  - 实时行情：qt.gtimg.cn → StockQuote（最新价、涨跌幅、PE/PB 等）
  - 日K线：   web.ifzq.gtimg.cn → KlineBar 列表（开高低收量）
  - 股票搜索：内置 A 股列表 + AKShare（可选）

设计原则：
  - 零外部认证依赖（腾讯 API 无需 API Key）
  - AKShare 仅在设置 USE_AKSHARE=1 时启用（网络不好时可能超时）
  - 内置 fallback 股票列表（38 只大市值/高流动性 A 股）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger("stock_app.market_data")


@dataclass
class StockQuote:
    """实时行情快照。

    Attributes:
        code:         6 位股票代码
        name:         股票名称
        market:       市场标识 "SH"（沪市）| "SZ"（深市）
        price:        最新成交价
        open:         今日开盘价
        high:         今日最高价
        low:          今日最低价
        pre_close:    昨日收盘价
        change_pct:   涨跌幅（%）
        change_amount: 涨跌额
        volume:       成交量（手）
        amount:       成交额
        turnover:     换手率（%）
        pe:           市盈率（TTM）
        pb:           市净率
        total_mv:     总市值（亿）
        time:         数据时间
    """
    code: str
    name: str
    market: str
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
        """转为中文键名字典（用于 Chat UI 展示）。"""
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
    """单根日K线数据。"""
    date: str       # 日期（yyyy-MM-dd）
    open: float     # 开盘价
    high: float     # 最高价
    low: float      # 最低价
    close: float    # 收盘价
    volume: int     # 成交量（手）

    def to_dict(self) -> dict:
        """转为英文键名字典（用于 DataFrame 构建）。"""
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


# ═════════════════════════════════════════════════════════════
# 腾讯实时行情 API
# ═════════════════════════════════════════════════════════════

# 腾讯行情接口返回字段名列表（按 ~ 分隔后的顺序）
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
    """根据股票代码前缀判断所属市场。
    规则：6/9 开头 → 沪市（SH），0/3/2 开头 → 深市（SZ）。
    """
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("0", "3", "2")):
        return "SZ"
    return "SZ"  # 默认深市


def _code_to_tencent(code: str) -> str:
    """将 6 位数字代码转换为腾讯行情 API 格式（sh/sz + 代码）。"""
    m = _detect_market(code)
    return f"{'sh' if m == 'SH' else 'sz'}{code}"


def _f(d: dict, key: str) -> float:
    """安全地从字典取值并转为 float，转换失败返回 0.0。"""
    try:
        return float(d.get(key, 0) or 0)
    except ValueError:
        return 0.0


def _parse_tencent_quote(raw: str) -> StockQuote:
    """解析腾讯实时行情 API 的原始响应字符串 → StockQuote 对象。

    腾讯返回格式：var hq_str_xxx="字段1~字段2~...";
    解析步骤：去壳 → 按 ~ 分割 → 按字段名映射 → 类型转换。
    """
    raw = raw.strip()
    # 去掉 "var hq_str_xxx=" 前缀和末尾分号
    if "=" in raw:
        raw = raw.split("=", 1)[1].strip('";\n ')
    parts = raw.split("~")
    # 将位置索引映射到字段名
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


def get_realtime_quote(code: str) -> Optional[StockQuote]:
    """从腾讯 API 获取单只股票实时行情。

    Args:
        code: 6 位股票代码

    Returns:
        StockQuote 对象，获取失败或代码不存在时返回 None
    """
    tc = _code_to_tencent(code)
    url = f"https://qt.gtimg.cn/q={tc}"
    try:
        r = _http().get(url, timeout=8)
        r.encoding = "gbk"  # 腾讯接口返回 GBK 编码
        if not r.text or "none" in r.text.lower():
            return None
        return _parse_tencent_quote(r.text)
    except Exception:
        logger.warning("获取实时行情失败 code=%s", code, exc_info=True)
        return None


# ═════════════════════════════════════════════════════════════
# 腾讯日K线 API
# ═════════════════════════════════════════════════════════════

def _parse_kline(raw) -> List[KlineBar]:
    """解析腾讯日K线原始数据 → KlineBar 列表。

    支持两种格式：
      - JSON 数组格式：[[date, open, close, high, low, vol], ...]
      - 字符串格式（KLineday1 接口）：每行 "date open close high low vol"
    """
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
    """从腾讯 API 获取股票日K线数据（前复权）。

    Args:
        code: 6 位股票代码
        days: 期望获取的天数（默认 90，实际会多取几根以防止边界缺失）

    Returns:
        KlineBar 列表（按日期升序），获取失败返回空列表
    """
    m = _detect_market(code)
    tc = f"{'sh' if m == 'SH' else 'sz'}{code}"
    # 多取 5 根以防边界缺失（前复权计算可能影响早期数据）
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
        # 截取最近 days 根 K 线
        return bars[-days:] if len(bars) > days else bars
    except Exception:
        logger.warning("获取日K线失败 code=%s days=%s", code, days, exc_info=True)
        return []


def kline_to_dataframe(bars: List[KlineBar]) -> pd.DataFrame:
    """将 KlineBar 列表转换为 pandas DataFrame（按日期升序排列）。"""
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame([b.to_dict() for b in bars])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ═════════════════════════════════════════════════════════════
# 股票搜索
# ═════════════════════════════════════════════════════════════

# 股票列表缓存（模块级，避免重复加载/网络请求）
_STOCK_LIST_CACHE: Optional[pd.DataFrame] = None


def _http() -> requests.Session:
    """创建预配置的 HTTP 会话。
    关闭 trust_env 以绕过系统代理设置（避免某些环境下的网络问题）。
    """
    s = requests.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    return s


def _load_stock_list() -> pd.DataFrame:
    """加载 A 股股票列表（带缓存）。

    优先级：AKShare（需 USE_AKSHARE=1）→ 内置 38 只核心股票列表。
    结果缓存在模块全局变量中，避免重复网络请求。
    """
    global _STOCK_LIST_CACHE
    if _STOCK_LIST_CACHE is not None:
        return _STOCK_LIST_CACHE

    # 尝试 AKShare（仅在用户主动启用时）
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

    # 内置 fallback：38 只大市值/高流动性 A 股（覆盖沪深主板、创业板、科创板）
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
    """根据关键词搜索股票（支持代码或名称匹配）。

    Args:
        keyword: 搜索关键词（代码或中文名称）
        limit:   最多返回条数

    Returns:
        [{"code": "600519", "name": "贵州茅台"}, ...] 格式的列表
    """
    df = _load_stock_list()
    keyword = keyword.strip()

    # 精确代码匹配优先
    code_match = df[df["code"].str.fullmatch(keyword)]
    if not code_match.empty:
        # 代码匹配 + 名称模糊匹配（合并去重）
        name_match = df[df["name"].str.contains(keyword, case=False, na=False)]
        df = pd.concat([code_match, name_match]).drop_duplicates(subset=["code"])
    else:
        # 模糊匹配：名称或代码包含关键词
        df = df[df["name"].str.contains(keyword, case=False, na=False) |
                df["code"].str.contains(re.escape(keyword), na=False)]
    return df.head(limit)[["code", "name"]].to_dict(orient="records")


def get_batch_quotes(codes: List[str]) -> List[StockQuote]:
    """批量获取多只股票的实时行情（逐个请求）。"""
    results: List[StockQuote] = []
    for code in codes:
        q = get_realtime_quote(code)
        if q:
            results.append(q)
    return results
