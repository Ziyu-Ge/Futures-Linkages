"""按历史小时顺序执行龙头与跟随品种识别。"""

import numpy as np
import pandas as pd

from config import (
    CORRELATION_THRESHOLD,
    DIRECTIONS,
    HISTORY_DAYS,
    MIN_CORRELATION_SAMPLES,
    OI_MULTIPLIER,
    RETURN_MULTIPLIER,
)


def lagged_correlation(leader_hours, follower_hours, window_start, window_end):
    """计算 leader(t-1自然小时) -> follower(t自然小时) 的有符号相关。"""
    leader = leader_hours.loc[
        leader_hours["trade_date"].between(window_start, window_end),
        ["trade_date", "hour_key", "hour_return"],
    ].dropna(subset=["hour_return"])
    follower = follower_hours.loc[
        follower_hours["trade_date"].between(window_start, window_end),
        ["trade_date", "hour_key", "hour_return"],
    ].dropna(subset=["hour_return"])
    if leader.empty or follower.empty:
        return np.nan, 0

    # 时间键加一小时后再连接；午休、夜盘间隔不会被当成“一小时滞后”。
    leader = leader.rename(columns={"hour_return": "leader_return"})
    leader["hour_key"] = leader["hour_key"] + pd.Timedelta(hours=1)
    follower = follower.rename(columns={"hour_return": "follower_return"})
    paired = leader.merge(
        follower,
        on=["trade_date", "hour_key"],
        how="inner",
        validate="one_to_one",
    )
    sample_count = len(paired)
    if sample_count < MIN_CORRELATION_SAMPLES:
        return np.nan, sample_count
    correlation = paired["leader_return"].corr(paired["follower_return"])
    if not np.isfinite(correlation):
        return np.nan, sample_count
    return float(correlation), sample_count


def choose_leader(frame, direction):
    """应用三条硬规则和四级排序，返回该截面的唯一龙头。"""
    return_threshold = RETURN_MULTIPLIER * frame["avg_abs_return"]
    oi_threshold = OI_MULTIPLIER * frame["avg_abs_oi_change"]
    common = (
        frame["current_return"].abs().gt(return_threshold)
        & frame["current_oi_change"].abs().gt(oi_threshold)
    )
    if direction == "上涨":
        eligible = frame.loc[
            common
            & frame["current_return"].gt(0)
            & frame["current_high"].gt(frame["prior_high"])
            & frame["up_break_time"].notna()
            & frame["up_break_time"].le(frame["snapshot_time"])
        ].copy()
        break_column, price_column = "up_break_time", "up_break_price"
        extreme_column, threshold_column = "current_high", "prior_high"
    else:
        eligible = frame.loc[
            common
            & frame["current_return"].lt(0)
            & frame["current_low"].lt(frame["prior_low"])
            & frame["down_break_time"].notna()
            & frame["down_break_time"].le(frame["snapshot_time"])
        ].copy()
        break_column, price_column = "down_break_time", "down_break_price"
        extreme_column, threshold_column = "current_low", "prior_low"
    if eligible.empty:
        return None

    eligible["abs_return"] = eligible["current_return"].abs()
    eligible["abs_oi_change"] = eligible["current_oi_change"].abs()
    eligible = eligible.sort_values(
        [break_column, "abs_return", "abs_oi_change", "symbol"],
        ascending=[True, False, False, True],
        kind="mergesort",
    )
    leader = eligible.iloc[0].copy()
    leader["first_break_time"] = leader[break_column]
    leader["first_break_price"] = leader[price_column]
    leader["current_extreme"] = leader[extreme_column]
    leader["breakout_threshold"] = leader[threshold_column]
    leader["return_threshold"] = RETURN_MULTIPLIER * leader["avg_abs_return"]
    leader["oi_threshold"] = OI_MULTIPLIER * leader["avg_abs_oi_change"]
    return leader


def correlation_for_pair(
    leader, follower_symbol, hourly_by_symbol, cache, diagnostics=None
):
    key = (
        leader["symbol"], follower_symbol, leader["window_start"], leader["window_end"]
    )
    if key not in cache:
        cache[key] = lagged_correlation(
            hourly_by_symbol[leader["symbol"]],
            hourly_by_symbol[follower_symbol],
            leader["window_start"],
            leader["window_end"],
        )
        if diagnostics is not None:
            correlation, sample_count = cache[key]
            diagnostics["evaluated_windows"] += 1
            if np.isfinite(correlation):
                diagnostics["finite_windows"] += 1
                if correlation > diagnostics["max_correlation"]:
                    diagnostics["max_correlation"] = correlation
                    diagnostics["max_pair"] = (
                        leader["symbol"], follower_symbol,
                        leader["window_start"], leader["window_end"], sample_count,
                    )
    return cache[key]


def next_hour_values(symbol, hour_key, next_lookup, direction):
    """识别冻结后，才查询该跟随品种时间序列中的下一真实小时。"""
    row = next_lookup[symbol].loc[hour_key]
    next_time = row["next_hour_time"]
    next_return = row["next_hour_return"]
    if pd.isna(next_return):
        return next_time, np.nan, np.nan, None
    direction_return = float(next_return) * (1.0 if direction == "上涨" else -1.0)
    return next_time, float(next_return), direction_return, bool(direction_return > 0)


def find_followers(
    frame, leader, direction, hourly_by_symbol, next_lookup, cache, diagnostics=None
):
    """筛选同方向品种，再计算前 20 日的一小时滞后相关。"""
    if direction == "上涨":
        candidates = frame.loc[frame["current_return"].gt(0)]
    else:
        candidates = frame.loc[frame["current_return"].lt(0)]
    candidates = candidates.loc[candidates["symbol"].ne(leader["symbol"])]
    followers = []
    for _, follower in candidates.sort_values("symbol", kind="mergesort").iterrows():
        correlation, sample_count = correlation_for_pair(
            leader, follower["symbol"], hourly_by_symbol, cache, diagnostics
        )
        if pd.isna(correlation) or correlation < CORRELATION_THRESHOLD:
            continue
        next_time, next_return, direction_return, same_direction = next_hour_values(
            follower["symbol"], follower["hour_key"], next_lookup, direction
        )
        followers.append({
            "symbol": follower["symbol"],
            "snapshot_time": follower["snapshot_time"],
            "current_return": follower["current_return"],
            "correlation": correlation,
            "correlation_samples": sample_count,
            "next_hour_time": next_time,
            "next_hour_return": next_return,
            "direction_return": direction_return,
            "later_same_direction": same_direction,
        })
    return sorted(followers, key=lambda item: (-item["correlation"], item["symbol"]))


def make_record(frame, leader, followers, direction):
    return {
        "trade_date": leader["trade_date"],
        "hour_key": leader["hour_key"],
        # 板块内所有本小时状态均不晚于这个识别时间。
        "identification_time": frame["snapshot_time"].max(),
        "group": leader["group"],
        "direction": direction,
        "leader_symbol": leader["symbol"],
        "leader_snapshot_time": leader["snapshot_time"],
        "first_break_time": leader["first_break_time"],
        "first_break_price": leader["first_break_price"],
        "leader_current_return": leader["current_return"],
        "leader_current_oi_change": leader["current_oi_change"],
        "current_extreme": leader["current_extreme"],
        "breakout_threshold": leader["breakout_threshold"],
        "return_threshold": leader["return_threshold"],
        "oi_threshold": leader["oi_threshold"],
        "history_window_start": leader["window_start"],
        "history_window_end": leader["window_end"],
        "followers": followers,
    }


def identify_history(
    snapshots, hourly_by_symbol, start_date=None, end_date=None,
    return_diagnostics=False,
):
    """从旧到新遍历每个真实小时截面，返回冻结的识别记录。"""
    work = snapshots.loc[snapshots["group"].ne("未分类")].copy()
    if start_date is not None:
        work = work.loc[work["trade_date"].ge(pd.Timestamp(start_date))]
    if end_date is not None:
        work = work.loc[work["trade_date"].le(pd.Timestamp(end_date))]
    work = work.sort_values(
        ["hour_key", "group", "symbol"], kind="mergesort"
    ).reset_index(drop=True)
    next_lookup = {
        symbol: hours.set_index("hour_key")[["next_hour_time", "next_hour_return"]]
        for symbol, hours in hourly_by_symbol.items()
    }
    cache, records = {}, []
    diagnostics = {
        "evaluated_windows": 0, "finite_windows": 0,
        "max_correlation": -np.inf, "max_pair": None,
    }
    keys = ["trade_date", "hour_key", "group"]
    for _, frame in work.groupby(keys, sort=True, observed=True):
        for direction in DIRECTIONS:
            leader = choose_leader(frame, direction)
            if leader is None:
                continue
            followers = find_followers(
                frame, leader, direction, hourly_by_symbol, next_lookup, cache,
                diagnostics,
            )
            records.append(make_record(frame, leader, followers, direction))
    return (records, diagnostics) if return_diagnostics else records
