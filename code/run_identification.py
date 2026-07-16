"""命令行入口：每小时识别龙头期货和跟涨期货。"""

import argparse
from pathlib import Path

import pandas as pd

from config import DATA_DIR, FLOAT_FORMAT, OUTPUT_DIR, OUTPUT_ENCODING
from market_data import prepare_all
from rules import identify_followers, identify_leaders


def parse_args():
    parser = argparse.ArgumentParser(description="规则驱动识别龙头期货和跟涨期货")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="分钟行情 CSV 目录")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="CSV 输出目录")
    parser.add_argument("--start", default=None, help="识别开始交易日 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="识别结束交易日 YYYY-MM-DD")
    parser.add_argument(
        "--symbols",
        default=None,
        help="只处理指定品种，逗号分隔，例如 CU,AL,ZN；默认处理 data/ 下全部 CSV",
    )
    return parser.parse_args()


def parse_date(value, label):
    if value is None:
        return None
    try:
        return pd.Timestamp(value).normalize()
    except ValueError as error:
        raise SystemExit(f"{label}日期格式无效: {value}") from error


def filter_dates(table, start_date, end_date):
    """只限制识别输出范围，不影响前 20 日历史窗口的生成。"""
    result = table
    if start_date is not None:
        result = result.loc[result["trade_date"].ge(start_date)]
    if end_date is not None:
        result = result.loc[result["trade_date"].le(end_date)]
    return result.copy()


def write_csv(table, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(
        path,
        index=False,
        encoding=OUTPUT_ENCODING,
        float_format=FLOAT_FORMAT,
    )


def main():
    args = parse_args()
    start_date = parse_date(args.start, "开始")
    end_date = parse_date(args.end, "结束")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise SystemExit("开始日期不能晚于结束日期")

    symbols = None
    if args.symbols:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]

    daily, snapshots = prepare_all(args.data_dir, symbols=symbols)
    snapshots_for_identify = filter_dates(snapshots, start_date, end_date)

    # 先识别龙头，再围绕每个龙头找同板块、同方向、高相关的跟涨品种。
    leaders = identify_leaders(snapshots_for_identify)
    followers = identify_followers(leaders, snapshots_for_identify, daily)

    output_dir = Path(args.output_dir)
    write_csv(leaders, output_dir / "leader_results.csv")
    write_csv(followers, output_dir / "follower_results.csv")
    write_csv(daily, output_dir / "daily_bars.csv")

    print(f"龙头识别结果: {output_dir / 'leader_results.csv'}")
    print(f"跟涨识别结果: {output_dir / 'follower_results.csv'}")
    print(f"日K中间表: {output_dir / 'daily_bars.csv'}")
    print(f"龙头数量: {len(leaders)}")
    print(f"跟涨记录数量: {len(followers)}")


if __name__ == "__main__":
    main()
