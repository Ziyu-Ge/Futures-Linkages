"""把冻结的识别记录整理为明细、一览和汇总表。"""

from pathlib import Path

import numpy as np
import pandas as pd

from config import FLOAT_FORMAT, OUTPUT_ONLY_WITH_FOLLOWERS


DETAIL_COLUMNS = [
    "trade_date", "identification_time", "hour_key", "group", "direction",
    "leader_symbol", "leader_snapshot_time", "first_break_time", "first_break_price",
    "leader_current_return", "leader_current_oi_change", "current_extreme",
    "breakout_threshold", "return_threshold", "oi_threshold",
    "history_window_start", "history_window_end", "follower_symbol",
    "follower_snapshot_time", "follower_current_return", "lagged_correlation",
    "correlation_samples", "next_hour_time", "next_hour_return",
    "direction_return", "later_same_direction",
]

OVERVIEW_COLUMNS = [
    "trade_date", "identification_time", "group", "direction", "leader_symbol",
    "follower_symbols", "lagged_correlations",
]

KEY_COLUMNS = [
    "trade_date", "identification_time", "group", "direction", "leader_symbol"
]

DETAIL_NAMES = {
    "trade_date": "交易日", "identification_time": "识别时间", "hour_key": "自然小时",
    "group": "板块", "direction": "方向", "leader_symbol": "龙头代码",
    "leader_snapshot_time": "龙头小时末时间", "first_break_time": "首次突破时间",
    "first_break_price": "首次突破价格", "leader_current_return": "龙头当日涨跌幅",
    "leader_current_oi_change": "龙头当日持仓变化幅", "current_extreme": "当下日K极值",
    "breakout_threshold": "前20日突破价", "return_threshold": "涨跌幅阈值",
    "oi_threshold": "增减仓阈值", "history_window_start": "前20日窗口开始",
    "history_window_end": "前20日窗口结束", "follower_symbol": "跟随品种代码",
    "follower_snapshot_time": "跟随品种小时末时间",
    "follower_current_return": "跟随品种当日涨跌幅",
    "lagged_correlation": "滞后一小时相关系数", "correlation_samples": "相关样本数",
    "next_hour_time": "下一实际交易小时时间", "next_hour_return": "下一小时收益率",
    "direction_return": "方向收益", "later_same_direction": "后续是否同向",
}

OVERVIEW_NAMES = {
    "trade_date": "交易日", "identification_time": "识别时间", "group": "板块",
    "direction": "方向", "leader_symbol": "龙头代码",
    "follower_symbols": "跟随品种代码列表", "lagged_correlations": "滞后相关系数列表",
}

SUMMARY_NAMES = {
    "scope": "统计范围", "group": "板块", "direction": "方向",
    "leader_count": "龙头识别数量", "with_followers_count": "有跟随品种的识别数量",
    "next_hour_samples": "有后续小时样本数", "same_direction_samples": "后续同向样本数",
    "same_direction_ratio": "后续同向比例",
    "mean_direction_return": "平均下一小时方向收益",
    "median_direction_return": "方向收益中位数",
}


def base_values(record):
    return {
        key: value for key, value in record.items() if key != "followers"
    }


def records_to_tables(records):
    """按输出配置筛选记录，再展开为明细和一览。"""
    if OUTPUT_ONLY_WITH_FOLLOWERS:
        records = [record for record in records if record["followers"]]
    detail_rows, overview_rows = [], []
    for record in records:
        base = base_values(record)
        followers = record["followers"]
        overview_rows.append({
            **{key: base[key] for key in KEY_COLUMNS},
            "follower_symbols": ",".join(item["symbol"] for item in followers),
            "lagged_correlations": ",".join(
                f'{item["correlation"]:.10f}' for item in followers
            ),
        })
        rows = followers if followers else [None]
        for follower in rows:
            row = base.copy()
            row.update({
                "follower_symbol": None,
                "follower_snapshot_time": pd.NaT,
                "follower_current_return": np.nan,
                "lagged_correlation": np.nan,
                "correlation_samples": np.nan,
                "next_hour_time": pd.NaT,
                "next_hour_return": np.nan,
                "direction_return": np.nan,
                "later_same_direction": None,
            })
            if follower is not None:
                row.update({
                    "follower_symbol": follower["symbol"],
                    "follower_snapshot_time": follower["snapshot_time"],
                    "follower_current_return": follower["current_return"],
                    "lagged_correlation": follower["correlation"],
                    "correlation_samples": follower["correlation_samples"],
                    "next_hour_time": follower["next_hour_time"],
                    "next_hour_return": follower["next_hour_return"],
                    "direction_return": follower["direction_return"],
                    "later_same_direction": follower["later_same_direction"],
                })
            detail_rows.append(row)

    detail = pd.DataFrame(detail_rows).reindex(columns=DETAIL_COLUMNS)
    overview = pd.DataFrame(overview_rows).reindex(columns=OVERVIEW_COLUMNS)
    detail = detail.sort_values(
        KEY_COLUMNS + ["lagged_correlation", "follower_symbol"],
        ascending=[True] * len(KEY_COLUMNS) + [False, True],
        kind="mergesort", na_position="last",
    ).reset_index(drop=True)
    overview = overview.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    return detail, overview


def one_summary(detail, overview, scope, group, direction):
    valid = detail.loc[
        detail["follower_symbol"].notna() & detail["next_hour_return"].notna()
    ]
    same_count = int(valid["later_same_direction"].eq(True).sum())
    sample_count = len(valid)
    return {
        "scope": scope,
        "group": group,
        "direction": direction,
        "leader_count": len(overview),
        "with_followers_count": int(overview["follower_symbols"].ne("").sum()),
        "next_hour_samples": sample_count,
        "same_direction_samples": same_count,
        "same_direction_ratio": same_count / sample_count if sample_count else np.nan,
        "mean_direction_return": valid["direction_return"].mean(),
        "median_direction_return": valid["direction_return"].median(),
    }


def make_summary(detail, overview):
    rows = [one_summary(detail, overview, "整体", "全部", "全部")]
    combinations = overview[["group", "direction"]].drop_duplicates()
    combinations = combinations.sort_values(["group", "direction"], kind="mergesort")
    for group, direction in combinations.itertuples(index=False, name=None):
        detail_part = detail.loc[
            detail["group"].eq(group) & detail["direction"].eq(direction)
        ]
        overview_part = overview.loc[
            overview["group"].eq(group) & overview["direction"].eq(direction)
        ]
        rows.append(one_summary(
            detail_part, overview_part, "板块方向", group, direction
        ))
    return pd.DataFrame(rows)


def format_datetimes(table):
    result = table.copy()
    for column in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            if column == "trade_date":
                result[column] = result[column].dt.strftime("%Y-%m-%d")
            else:
                result[column] = result[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    return result


def csv_bytes(table, names):
    """统一序列化口径，也用于确定性复跑比较。"""
    output = format_datetimes(table).rename(columns=names)
    text = output.to_csv(index=False, float_format=FLOAT_FORMAT, lineterminator="\n")
    return ("\ufeff" + text).encode("utf-8")


def write_outputs(detail, overview, summary, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "detail": output_dir / "leader_follower_detail.csv",
        "overview": output_dir / "leader_follower_overview.csv",
        "summary": output_dir / "identification_summary.csv",
    }
    payloads = {
        "detail": csv_bytes(detail, DETAIL_NAMES),
        "overview": csv_bytes(overview, OVERVIEW_NAMES),
        "summary": csv_bytes(summary, SUMMARY_NAMES),
    }
    for key, path in files.items():
        path.write_bytes(payloads[key])
    return files, payloads
