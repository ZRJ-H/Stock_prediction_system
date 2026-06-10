"""下载并标准化贵州茅台前复权日线数据。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


DEFAULT_OUTPUT = Path("data/blind_test/600519_daily.csv")


def normalize_history(raw: pd.DataFrame) -> pd.DataFrame:
    """将 AKShare 日线字段转换为模型训练格式。"""
    column_map = {
        "日期": "timestamp",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "vol",
    }
    missing = [name for name in column_map if name not in raw.columns]
    if missing:
        raise ValueError(f"行情数据缺少字段: {missing}")

    df = raw.rename(columns=column_map)[list(column_map.values())].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ["open", "high", "low", "close", "vol"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = (
        df.dropna()
        .drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if len(df) < 100:
        raise ValueError(f"有效日线数据过少，当前仅 {len(df)} 条。")

    # 行 t 的目标是该交易日相对前一交易日的方向；模型窗口只使用 t 之前的数据。
    df["label"] = (df["close"].diff() > 0).astype(int)
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    return df


def fetch_history(start_date: str, end_date: str) -> pd.DataFrame:
    """通过 AKShare 获取东方财富前复权日线。"""
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先安装 requirements-optional.txt。") from exc

    raw = ak.stock_zh_a_hist(
        symbol="600519",
        period="daily",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust="qfq",
    )
    if raw is None or raw.empty:
        raise RuntimeError("AKShare 未返回贵州茅台历史行情。")
    return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="准备贵州茅台历史盲测数据")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument(
        "--end",
        default=(date.today() - timedelta(days=1)).isoformat(),
        help="结束日期，默认昨天，格式 YYYY-MM-DD",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser


def main(argv: list[str] | None = None) -> Path:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    df = normalize_history(fetch_history(args.start, args.end))
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False, encoding="utf-8")
    print(f"已保存 {len(df)} 条贵州茅台前复权日线到 {output}")
    print(f"日期范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    return output


if __name__ == "__main__":
    main()
