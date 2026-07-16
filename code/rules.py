"""龙头期货和跟涨期货的简单规则。"""

import numpy as np
import pandas as pd

from config import (
    CORRELATION_THRESHOLD,
    HISTORY_DAYS,
    MIN_CORRELATION_DAYS,
    OI_MULTIPLIER,
    RETURN_MULTIPLIER,
)


LEADER_COLUMNS = [
    "识别时间", "交易日", "龙头品种", "板块", "方向", "当前涨跌幅",
    "当前增减仓幅度", "前20日最高价或最低价", "前20日平均涨跌幅绝对值",
    "前20日平均增减仓幅度绝对值", "首次突破时间", "识别小时",
    "历史窗口开始", "历史窗口结束", "触发原因",
]

FOLLOWER_COLUMNS = [
    "识别时间", "交易日", "龙头品种", "跟涨品种", "板块", "方向",
    "20日收益率相关系数", "相关样本数", "龙头当前涨跌幅",
    "跟涨品种当前涨跌幅", "触发原因",
]


def make_leader_reason(row, direction):
    """把触发条件写成可读中文，方便人工复核。"""
    if direction == "向上":
        break_text = f"high={row['high']:.6g} 突破前20日高点 {row['break_level']:.6g}"
        oi_text = "增仓"
    else:
        break_text = f"low={row['low']:.6g} 跌破前20日低点 {row['break_level']:.6g}"
        oi_text = "减仓"
    return (
        f"{break_text}；涨跌幅={row['return']:.4%}，"
        f"超过2倍前20日平均绝对涨跌幅 {row['avg_abs_return_20']:.4%}；"
        f"{oi_text}幅度={row['oi_change']:.4%}，"
        f"超过1.5倍前20日平均绝对增减仓幅度 {row['avg_abs_oi_change_20']:.4%}；"
        f"首次突破时间={row['first_break_time']}"
    )


def choose_leader(frame, direction):
    """在同一小时、同一板块内，按规则选出最早突破的龙头。"""
    required = [
        "prior_20_high", "prior_20_low", "avg_abs_return_20",
        "avg_abs_oi_change_20", "return", "oi_change",
    ]
    frame = frame.loc[frame[required].notna().all(axis=1)].copy()
    if frame.empty:
        return None

    return_ok = frame["return"].abs().gt(RETURN_MULTIPLIER * frame["avg_abs_return_20"])
    oi_ok = frame["oi_change"].abs().gt(OI_MULTIPLIER * frame["avg_abs_oi_change_20"])
    if direction == "向上":
        eligible = frame.loc[
            return_ok
            & oi_ok
            & frame["return"].gt(0)
            & frame["oi_change"].gt(0)
            & frame["high"].gt(frame["prior_20_high"])
            & frame["up_break_time"].notna()
            & frame["up_break_time"].le(frame["snapshot_time"])
        ].copy()
        eligible["first_break_time"] = eligible["up_break_time"]
        eligible["break_level"] = eligible["prior_20_high"]
    else:
        eligible = frame.loc[
            return_ok
            & oi_ok
            & frame["return"].lt(0)
            & frame["oi_change"].lt(0)
            & frame["low"].lt(frame["prior_20_low"])
            & frame["down_break_time"].notna()
            & frame["down_break_time"].le(frame["snapshot_time"])
        ].copy()
        eligible["first_break_time"] = eligible["down_break_time"]
        eligible["break_level"] = eligible["prior_20_low"]
    if eligible.empty:
        return None

    eligible["abs_return"] = eligible["return"].abs()
    eligible["abs_oi_change"] = eligible["oi_change"].abs()
    eligible = eligible.sort_values(
        ["first_break_time", "abs_return", "abs_oi_change", "symbol"],
        ascending=[True, False, False, True],
        kind="mergesort",
    )
    leader = eligible.iloc[0].copy()
    leader["direction"] = direction
    leader["reason"] = make_leader_reason(leader, direction)
    return leader


def identify_leaders(snapshots):
    """逐小时、逐板块识别龙头，返回可解释的龙头结果表。"""
    work = snapshots.loc[snapshots["group"].ne("未分类")].copy()
    keys = ["trade_date", "identify_hour", "group"]
    work["identification_time"] = work.groupby(keys)["snapshot_time"].transform("max")

    required = [
        "prior_20_high", "prior_20_low", "avg_abs_return_20",
        "avg_abs_oi_change_20", "return", "oi_change",
    ]
    work = work.loc[work[required].notna().all(axis=1)].copy()
    if work.empty:
        return pd.DataFrame(columns=LEADER_COLUMNS)

    return_ok = work["return"].abs().gt(RETURN_MULTIPLIER * work["avg_abs_return_20"])
    oi_ok = work["oi_change"].abs().gt(OI_MULTIPLIER * work["avg_abs_oi_change_20"])

    # 向上和向下规则完全展开，方便看清楚每条条件。
    up = work.loc[
        return_ok
        & oi_ok
        & work["return"].gt(0)
        & work["oi_change"].gt(0)
        & work["high"].gt(work["prior_20_high"])
        & work["up_break_time"].notna()
        & work["up_break_time"].le(work["snapshot_time"])
    ].copy()
    up["direction"] = "向上"
    up["first_break_time"] = up["up_break_time"]
    up["break_level"] = up["prior_20_high"]

    down = work.loc[
        return_ok
        & oi_ok
        & work["return"].lt(0)
        & work["oi_change"].lt(0)
        & work["low"].lt(work["prior_20_low"])
        & work["down_break_time"].notna()
        & work["down_break_time"].le(work["snapshot_time"])
    ].copy()
    down["direction"] = "向下"
    down["first_break_time"] = down["down_break_time"]
    down["break_level"] = down["prior_20_low"]

    eligible = pd.concat([up, down], ignore_index=True)
    if eligible.empty:
        return pd.DataFrame(columns=LEADER_COLUMNS)
    eligible["abs_return"] = eligible["return"].abs()
    eligible["abs_oi_change"] = eligible["oi_change"].abs()
    eligible = eligible.sort_values(
        keys + ["direction", "first_break_time", "abs_return", "abs_oi_change", "symbol"],
        ascending=[True, True, True, True, True, False, False, True],
        kind="mergesort",
    )
    leaders = eligible.drop_duplicates(keys + ["direction"], keep="first")

    rows = []
    for _, leader in leaders.iterrows():
        rows.append({
            "识别时间": leader["identification_time"],
            "交易日": leader["trade_date"],
            "龙头品种": leader["symbol"],
            "板块": leader["group"],
            "方向": leader["direction"],
            "当前涨跌幅": leader["return"],
            "当前增减仓幅度": leader["oi_change"],
            "前20日最高价或最低价": leader["break_level"],
            "前20日平均涨跌幅绝对值": leader["avg_abs_return_20"],
            "前20日平均增减仓幅度绝对值": leader["avg_abs_oi_change_20"],
            "首次突破时间": leader["first_break_time"],
            "识别小时": leader["identify_hour"],
            "历史窗口开始": leader["history_start"],
            "历史窗口结束": leader["history_end"],
            "触发原因": make_leader_reason(leader, leader["direction"]),
        })
    return pd.DataFrame(rows).reindex(columns=LEADER_COLUMNS)


def past_return_correlation(return_pivot, leader, follower, cache):
    """计算龙头与候选品种前 20 个交易日日收益率相关系数。"""
    cache_key = (leader["龙头品种"], follower, leader["历史窗口开始"], leader["历史窗口结束"])
    if cache_key in cache:
        return cache[cache_key]
    if leader["龙头品种"] not in return_pivot or follower not in return_pivot:
        return np.nan, 0
    paired = return_pivot.loc[
        leader["历史窗口开始"]:leader["历史窗口结束"],
        [leader["龙头品种"], follower],
    ].dropna()
    if len(paired) < MIN_CORRELATION_DAYS:
        cache[cache_key] = (np.nan, len(paired))
        return cache[cache_key]
    correlation = paired[leader["龙头品种"]].corr(paired[follower])
    if not np.isfinite(correlation):
        cache[cache_key] = (np.nan, len(paired))
    else:
        cache[cache_key] = (float(correlation), len(paired))
    return cache[cache_key]


def make_follower_reason(correlation, leader_return, follower_return, direction):
    """把跟涨/跟跌触发条件写成中文原因。"""
    sign_text = "同为上涨" if direction == "向上" else "同为下跌"
    return (
        f"同板块；过去{HISTORY_DAYS}个交易日日收益率相关系数={correlation:.4f}，"
        f"不低于阈值{CORRELATION_THRESHOLD:.2f}；当前方向一致："
        f"龙头={leader_return:.4%}，候选={follower_return:.4%}，{sign_text}"
    )


def identify_followers(leaders, snapshots, daily):
    """对每个已识别龙头，在同板块内寻找方向一致且相关性达标的品种。"""
    if leaders.empty:
        return pd.DataFrame(columns=FOLLOWER_COLUMNS)
    rows = []
    snapshot_keys = ["交易日", "识别小时", "板块"]
    snapshot_map = {
        key: frame for key, frame in snapshots.groupby(["trade_date", "identify_hour", "group"])
    }
    return_pivot = daily.pivot_table(index="trade_date", columns="symbol", values="return")
    correlation_cache = {}
    for _, leader in leaders.iterrows():
        key = (leader["交易日"], leader["识别小时"], leader["板块"])
        frame = snapshot_map.get(key)
        if frame is None:
            continue
        if leader["方向"] == "向上":
            candidates = frame.loc[frame["return"].gt(0)]
        else:
            candidates = frame.loc[frame["return"].lt(0)]
        candidates = candidates.loc[candidates["symbol"].ne(leader["龙头品种"])]
        for _, candidate in candidates.sort_values("symbol", kind="mergesort").iterrows():
            correlation, sample_count = past_return_correlation(
                return_pivot, leader, candidate["symbol"], correlation_cache
            )
            if pd.isna(correlation) or correlation < CORRELATION_THRESHOLD:
                continue
            rows.append({
                "识别时间": leader["识别时间"],
                "交易日": leader["交易日"],
                "龙头品种": leader["龙头品种"],
                "跟涨品种": candidate["symbol"],
                "板块": leader["板块"],
                "方向": leader["方向"],
                "20日收益率相关系数": correlation,
                "相关样本数": sample_count,
                "龙头当前涨跌幅": leader["当前涨跌幅"],
                "跟涨品种当前涨跌幅": candidate["return"],
                "触发原因": make_follower_reason(
                    correlation, leader["当前涨跌幅"], candidate["return"], leader["方向"]
                ),
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=FOLLOWER_COLUMNS)
    return result.sort_values(
        ["识别时间", "板块", "方向", "龙头品种", "20日收益率相关系数", "跟涨品种"],
        ascending=[True, True, True, True, False, True],
        kind="mergesort",
    ).reset_index(drop=True).reindex(columns=FOLLOWER_COLUMNS)
