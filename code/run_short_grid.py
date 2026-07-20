"""做空策略的三参数网格回测。

默认网格：
- RETURN_MULTIPLIER: 1.0--5.0，步长 0.5
- OI_MULTIPLIER: 0.5--5.0，步长 0.5
- CORRELATION_THRESHOLD: 0.5--0.9，步长 0.1

实现上先取所有参数组合会选中的唯一龙头事件，只计算一次跟随品种
相关性和入场价，再回填到 450 个网格，避免重复读取分钟数据。
"""

import argparse
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

import rules
from market_data import prepare_all
from run_short_backtest import add_entry_prices, calculate_performance


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data"
DEFAULT_OUTPUT = ROOT / "results" / "short_grid"
EVENT_COLUMNS = ["识别时间", "交易日", "龙头品种", "板块", "方向"]
PARAMETER_COLUMNS = ["RETURN_MULTIPLIER", "OI_MULTIPLIER", "CORRELATION_THRESHOLD"]


def parse_args():
    parser = argparse.ArgumentParser(description="做空跟随策略的三参数网格回测")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA), help="分钟行情目录")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="网格结果目录")
    parser.add_argument(
        "--fee-rates",
        default="0,0.0001",
        help="单边费率，逗号分隔；默认同时计算零费率和单边 1bp",
    )
    return parser.parse_args()


def make_grid():
    returns = np.round(np.arange(1.0, 5.0 + 0.01, 0.5), 1)
    positions = np.round(np.arange(0.5, 5.0 + 0.01, 0.5), 1)
    correlations = np.round(np.arange(0.5, 0.9 + 0.01, 0.1), 1)
    return returns, positions, correlations


def prepare_down_pool(snapshots):
    """提前保留所有可能成为向下龙头的小时快照。"""
    required = [
        "prior_20_high", "prior_20_low", "avg_abs_return_20",
        "avg_abs_oi_change_20", "return", "oi_change",
    ]
    work = snapshots.loc[snapshots["group"].ne("未分类")].copy()
    keys = ["trade_date", "identify_hour", "group"]
    work["identification_time"] = work.groupby(keys)["snapshot_time"].transform("max")
    work = work.loc[work[required].notna().all(axis=1)].copy()
    work = work.loc[
        work["return"].lt(0)
        & work["oi_change"].lt(0)
        & work["low"].lt(work["prior_20_low"])
        & work["down_break_time"].notna()
        & work["down_break_time"].le(work["snapshot_time"])
    ].copy()
    work["return_ratio"] = work["return"].abs() / work["avg_abs_return_20"]
    work["oi_ratio"] = work["oi_change"].abs() / work["avg_abs_oi_change_20"]
    work["abs_return"] = work["return"].abs()
    work["abs_oi_change"] = work["oi_change"].abs()
    return work.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["return_ratio", "oi_ratio"]
    )


def select_leader_cases(pool, return_values, oi_values):
    """为每组收益/持仓阈值选龙头，并保留参数归属。"""
    keys = ["trade_date", "identify_hour", "group"]
    sort_columns = keys + [
        "down_break_time", "abs_return", "abs_oi_change", "symbol"
    ]
    parts = []
    total = len(return_values) * len(oi_values)
    for number, (return_limit, oi_limit) in enumerate(
        product(return_values, oi_values), start=1
    ):
        eligible = pool.loc[
            pool["return_ratio"].gt(return_limit)
            & pool["oi_ratio"].gt(oi_limit)
        ].sort_values(
            sort_columns,
            ascending=[True, True, True, True, False, False, True],
            kind="mergesort",
        )
        leaders = eligible.drop_duplicates(keys, keep="first").copy()
        leaders["RETURN_MULTIPLIER"] = return_limit
        leaders["OI_MULTIPLIER"] = oi_limit
        parts.append(leaders)
        if number % 10 == 0 or number == total:
            print(f"龙头阈值 {number:02d}/{total:02d}", flush=True)

    selected = pd.concat(parts, ignore_index=True)
    selected["识别时间"] = selected["identification_time"]
    selected["交易日"] = selected["trade_date"]
    selected["龙头品种"] = selected["symbol"]
    selected["板块"] = selected["group"]
    selected["方向"] = "向下"
    selected["当前涨跌幅"] = selected["return"]
    selected["识别小时"] = selected["identify_hour"]
    selected["历史窗口开始"] = selected["history_start"]
    selected["历史窗口结束"] = selected["history_end"]
    return selected


def expand_follower_grid(leader_cases, snapshots, daily, correlation_values):
    """候选跟随品种只计算一次，然后映射回各参数组合。"""
    leader_columns = EVENT_COLUMNS + [
        "识别小时", "历史窗口开始", "历史窗口结束", "当前涨跌幅"
    ]
    unique_leaders = leader_cases[leader_columns].drop_duplicates(EVENT_COLUMNS)

    original_threshold = rules.CORRELATION_THRESHOLD
    rules.CORRELATION_THRESHOLD = float(min(correlation_values))
    try:
        followers = rules.identify_followers(unique_leaders, snapshots, daily)
    finally:
        rules.CORRELATION_THRESHOLD = original_threshold

    memberships = leader_cases[
        EVENT_COLUMNS + ["RETURN_MULTIPLIER", "OI_MULTIPLIER"]
    ].drop_duplicates()
    followers = followers.merge(
        memberships,
        on=EVENT_COLUMNS,
        how="inner",
        validate="many_to_many",
    )

    parts = []
    for threshold in correlation_values:
        block = followers.loc[
            followers["20日收益率相关系数"].ge(threshold)
        ].copy()
        block["CORRELATION_THRESHOLD"] = threshold
        parts.append(block)
    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values("识别时间", kind="mergesort")
    return result.drop_duplicates(
        PARAMETER_COLUMNS + ["交易日", "跟涨品种"], keep="first"
    )


def add_closes_and_entries(signals, daily, data_dir):
    closing = daily[["symbol", "trade_date", "close", "day_end_time"]]
    candidates = signals.merge(
        closing,
        left_on=["交易日", "跟涨品种"],
        right_on=["trade_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    priced = add_entry_prices(candidates, data_dir)
    valid = (
        priced["开空时间"].le(priced["day_end_time"])
        & priced["开空价"].gt(0)
        & priced["close"].gt(0)
    )
    trades = priced.loc[valid].copy()
    trades["平空时间"] = trades["day_end_time"]
    trades["平空价"] = trades["close"]
    trades["税前收益率"] = trades["开空价"] / trades["平空价"] - 1.0
    return trades


def calculate_grid_metrics(trades, daily, grid, fee_rates):
    rows = []
    grouped = {
        key: frame for key, frame in trades.groupby(PARAMETER_COLUMNS, sort=False)
    }
    for return_limit, oi_limit, correlation_limit in grid:
        key = (return_limit, oi_limit, correlation_limit)
        block = grouped.get(key, pd.DataFrame()).copy()
        for fee_rate in fee_rates:
            if not block.empty:
                block["净收益率"] = block["税前收益率"] - 2.0 * fee_rate
                _, metrics = calculate_performance(block, daily)
                values = dict(zip(metrics["指标"], metrics["数值"]))
            else:
                values = {
                    "交易次数": 0, "胜率": np.nan, "累计收益率": np.nan,
                    "年化收益率": np.nan, "最大回撤": np.nan, "年化夏普比率": np.nan,
                }
            rows.append({
                "RETURN_MULTIPLIER": return_limit,
                "OI_MULTIPLIER": oi_limit,
                "CORRELATION_THRESHOLD": correlation_limit,
                "单边费率": fee_rate,
                **values,
            })
    return pd.DataFrame(rows)


def make_parameter_summary(metrics):
    """按单个参数聚合，用中位数判断高分是尖峰还是稳定区域。"""
    work = metrics.copy()
    work["正收益"] = work["累计收益率"].gt(0)
    parts = []
    for fee_rate, fee_block in work.groupby("单边费率", sort=True):
        for parameter in PARAMETER_COLUMNS:
            summary = fee_block.groupby(parameter, as_index=False).agg(
                组合数=("累计收益率", "size"),
                交易次数中位数=("交易次数", "median"),
                累计收益中位数=("累计收益率", "median"),
                夏普中位数=("年化夏普比率", "median"),
                正收益比例=("正收益", "mean"),
            ).rename(columns={parameter: "参数值"})
            summary.insert(0, "参数", parameter)
            summary.insert(0, "单边费率", fee_rate)
            parts.append(summary)
    return pd.concat(parts, ignore_index=True)


def main():
    args = parse_args()
    fee_rates = [float(value) for value in args.fee_rates.split(",")]
    if not fee_rates or any(value < 0 for value in fee_rates):
        raise SystemExit("手续费率必须是非负数")

    return_values, oi_values, correlation_values = make_grid()
    grid = list(product(return_values, oi_values, correlation_values))
    daily, snapshots = prepare_all(args.data_dir)
    pool = prepare_down_pool(snapshots)
    leader_cases = select_leader_cases(pool, return_values, oi_values)
    signals = expand_follower_grid(
        leader_cases, snapshots, daily, correlation_values
    )
    trades = add_closes_and_entries(signals, daily, args.data_dir)
    metrics = calculate_grid_metrics(trades, daily, grid, fee_rates)

    trade_columns = PARAMETER_COLUMNS + [
        "交易日", "龙头品种", "跟涨品种", "板块", "识别时间",
        "开空时间", "开空价", "平空时间", "平空价", "税前收益率",
    ]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(
        output_dir / "grid_metrics.csv", index=False, encoding="utf-8-sig"
    )
    metrics.sort_values(
        ["单边费率", "年化夏普比率", "交易次数"],
        ascending=[True, False, False],
    ).to_csv(
        output_dir / "grid_ranked.csv", index=False, encoding="utf-8-sig"
    )
    make_parameter_summary(metrics).to_csv(
        output_dir / "parameter_summary.csv", index=False, encoding="utf-8-sig"
    )
    trades[trade_columns].sort_values(
        PARAMETER_COLUMNS + ["交易日", "跟涨品种"]
    ).to_csv(output_dir / "grid_trades.csv", index=False, encoding="utf-8-sig")

    print(f"\n网格数量: {len(grid)}")
    print(f"绩效结果: {output_dir / 'grid_metrics.csv'}")
    print(f"夏普排序: {output_dir / 'grid_ranked.csv'}")
    print(f"参数汇总: {output_dir / 'parameter_summary.csv'}")
    print(f"交易明细: {output_dir / 'grid_trades.csv'}")


if __name__ == "__main__":
    main()
