"""全量历史龙头与跟随品种识别入口。"""

import argparse

import pandas as pd

from config import (
    DATA_DIR,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    OUTPUT_DIR,
    ROOT,
)
from identify import identify_history
from market_data import prepare_all
from report import make_summary, records_to_tables, write_outputs
from validate import run_validations, validate_line_counts


def parse_args():
    parser = argparse.ArgumentParser(description="逐小时识别历史龙头与跟随期货")
    parser.add_argument("--start", default=DEFAULT_START_DATE, help="识别开始日 YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_END_DATE, help="识别结束日 YYYY-MM-DD")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="分钟 CSV 目录")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="结果目录")
    return parser.parse_args()


def parse_date(value, label):
    if value is None:
        return None
    try:
        return pd.Timestamp(value).normalize()
    except ValueError as error:
        raise SystemExit(f"{label}日期无效: {value}") from error


def effective_range(snapshots, start_date, end_date):
    required = [
        "prior_high", "prior_low", "avg_abs_return", "avg_abs_oi_change",
        "window_start", "window_end",
    ]
    eligible = snapshots.loc[
        snapshots["group"].ne("未分类") & snapshots[required].notna().all(axis=1),
        "trade_date",
    ]
    if eligible.empty:
        raise RuntimeError("数据中没有具备完整 20 日窗口的历史时点")
    first, last = eligible.min(), eligible.max()
    first = max(first, start_date) if start_date is not None else first
    last = min(last, end_date) if end_date is not None else last
    if first > last:
        raise SystemExit(f"识别日期范围为空: {first:%Y-%m-%d} 至 {last:%Y-%m-%d}")
    return first, last


def main():
    args = parse_args()
    start_date = parse_date(args.start, "开始")
    end_date = parse_date(args.end, "结束")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise SystemExit("开始日期不能晚于结束日期")

    # 在读取 4.3GB 数据之前先执行代码行数硬约束。
    print(validate_line_counts(ROOT / "code"), flush=True)
    daily_all, snapshots, hourly_by_symbol = prepare_all(args.data_dir)
    first, last = effective_range(snapshots, start_date, end_date)
    print(f"开始逐小时历史回放：{first:%Y-%m-%d} 至 {last:%Y-%m-%d}", flush=True)

    records, diagnostics = identify_history(
        snapshots, hourly_by_symbol, start_date, end_date, return_diagnostics=True
    )
    detail, overview = records_to_tables(records)
    summary = make_summary(detail, overview)
    files, payloads = write_outputs(detail, overview, summary, args.output_dir)
    validation_path = run_validations(
        records, detail, overview, daily_all, snapshots, hourly_by_symbol,
        args.data_dir, ROOT / "code", args.output_dir, start_date, end_date, payloads,
        diagnostics,
    )

    total = summary.iloc[0]
    ratio = total["same_direction_ratio"]
    ratio_text = "无样本" if pd.isna(ratio) else f"{ratio:.2%}"
    print(f"识别日期范围：{first:%Y-%m-%d} 至 {last:%Y-%m-%d}")
    print(f"历史识别明细：{files['detail']}")
    print(f"历史识别一览：{files['overview']}")
    print(f"识别统计：{files['summary']}")
    print(f"验证报告：{validation_path}")
    print(f"龙头识别数量：{int(total['leader_count'])}")
    print(f"有跟随品种的识别数量：{int(total['with_followers_count'])}")
    print(f"辅助验证后续同向比例：{ratio_text}")


if __name__ == "__main__":
    main()
