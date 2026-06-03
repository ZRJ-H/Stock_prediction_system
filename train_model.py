"""
股票预测模型训练 CLI
====================
命令行训练入口，使用时间序列切分（不打乱）训练 CNN/MLP 模型。

用法：
  python train_model.py --data dataset/tt.csv --model-dir models

输出：
  - models/stock_cnn.keras 或 stock_mlp.joblib  （模型权重）
  - models/scaler.json                          （归一化参数）
  - models/meta.json                            （元信息）
  - models/training_report.json                 （训练报告）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（供测试复用）。"""
    parser = argparse.ArgumentParser(
        description="训练股票涨跌预测模型（时间序列切分）",
    )
    parser.add_argument(
        "--data", default="dataset/tt.csv",
        help="训练数据 CSV 路径（默认 dataset/tt.csv）",
    )
    parser.add_argument(
        "--model-dir", default="models",
        help="模型输出目录（默认 models）",
    )
    parser.add_argument(
        "--epochs", type=int, default=12,
        help="CNN 训练轮数（默认 12）",
    )
    parser.add_argument(
        "--batch-size", type=int, default=32,
        help="CNN 批次大小（默认 32）",
    )
    return parser


def main(argv: list[str] | None = None) -> dict:
    """训练入口，返回训练报告字典。"""
    args = build_parser().parse_args(argv)

    import pandas as pd
    from core.model_service import StockCNNService

    df = pd.read_csv(args.data)
    svc = StockCNNService(model_dir=args.model_dir)
    report = svc.train_with_time_split(
        df, epochs=args.epochs, batch_size=args.batch_size,
    )

    # 写入报告文件
    report_path = Path(args.model_dir) / "training_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    print(f"训练完成。报告已保存到 {report_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    main()
