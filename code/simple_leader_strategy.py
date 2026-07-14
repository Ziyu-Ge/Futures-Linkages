import math

import pandas as pd

from simple_leader_config import (
    BREAKOUT_WINDOW,
    CONFIRM_DAYS,
    CORRELATION_THRESHOLD,
    CORRELATION_WINDOW,
)
from simple_leader_data import normalize_daily_bars


EVENT_COLUMNS = [
    "analysis_date", "sector", "direction", "start_date", "confirm_date",
    "status", "leader", "earliest_symbols", "strongest_symbol",
    "strongest_status", "leader_return", "follower_count",
]
FOLLOWER_COLUMNS = [
    "sector", "direction", "start_date", "leader", "follower",
    "rolling_corr_20", "leader_return", "follower_return", "return_gap",
    "follower_start_date", "follower_type",
]


def find_breakouts(bars, window=BREAKOUT_WINDOW):
    """滚动寻找突破；过去最高价和最低价都不包含当日。"""
    data = normalize_daily_bars(bars)
    grouped = data.groupby("symbol", sort=False)["close"]
    data["past_high"] = grouped.transform(
        lambda values: values.shift(1).rolling(window, min_periods=window).max()
    )
    data["past_low"] = grouped.transform(
        lambda values: values.shift(1).rolling(window, min_periods=window).min()
    )
    data["up_breakout"] = data["close"] > data["past_high"]
    data["down_breakout"] = data["close"] < data["past_low"]
    return data


def create_events(breakouts, confirm_days=CONFIRM_DAYS):
    """同板块同方向事件在确认窗口内只创建一次。"""
    events = []
    for sector, sector_data in breakouts.groupby("sector", sort=True):
        dates = pd.Index(sector_data["trade_date"].drop_duplicates().sort_values())
        date_position = {date: position for position, date in enumerate(dates)}

        for direction, column in [("上涨", "up_breakout"), ("下跌", "down_breakout")]:
            signals = sector_data[sector_data[column]].sort_values("trade_date")
            blocked_until = -1
            for start_date in signals["trade_date"].drop_duplicates():
                start_position = date_position[start_date]
                if start_position <= blocked_until:
                    continue

                same_day = signals[signals["trade_date"] == start_date]
                earliest = "|".join(sorted(same_day["symbol"].unique()))
                confirm_position = start_position + confirm_days
                confirm_date = (
                    dates[confirm_position] if confirm_position < len(dates) else pd.NaT
                )
                events.append({
                    "sector": sector,
                    "direction": direction,
                    "start_date": start_date,
                    "confirm_date": confirm_date,
                    "analysis_date": dates[-1],
                    "earliest_symbols": earliest,
                })
                blocked_until = confirm_position
    return events


def calculate_event_returns(close_table, start_date, end_date, direction):
    """所有品种都从启动日前一交易日开始计算，保证可比较。"""
    dates = close_table.index
    start_position = dates.get_indexer([start_date])[0]
    if start_position <= 0 or end_date not in dates:
        return pd.DataFrame(columns=["symbol", "raw_return", "directional_move"])

    base_date = dates[start_position - 1]
    raw_return = close_table.loc[end_date] / close_table.loc[base_date] - 1
    moves = raw_return.rename("raw_return").dropna().reset_index()
    moves.columns = ["symbol", "raw_return"]
    sign = 1 if direction == "上涨" else -1
    moves["directional_move"] = sign * moves["raw_return"]
    return moves


def calculate_rolling_corr(
    close_table, leader, follower, start_date, window=CORRELATION_WINDOW
):
    """只使用启动日前最近20个完整的共同日收益率。"""
    returns = close_table.pct_change(fill_method=None)
    recent = returns.loc[returns.index < start_date, [leader, follower]].tail(window)
    recent = recent.dropna()
    if len(recent) != window:
        return math.nan
    return recent[leader].corr(recent[follower])


def find_followers(
    close_table,
    breakouts,
    event,
    leader,
    end_date,
    moves,
    threshold=CORRELATION_THRESHOLD,
):
    """用启动前相关性和启动后的相对涨跌幅筛选跟随品种。"""
    move_table = moves.set_index("symbol")
    if leader not in move_table.index:
        return []

    leader_move = move_table.at[leader, "directional_move"]
    leader_return = move_table.at[leader, "raw_return"]
    if leader_move <= 0:
        return []

    direction_column = "up_breakout" if event["direction"] == "上涨" else "down_breakout"
    rows = []
    for follower in close_table.columns:
        if follower == leader or follower not in move_table.index:
            continue

        follower_move = move_table.at[follower, "directional_move"]
        if not 0 < follower_move < leader_move:
            continue

        corr = calculate_rolling_corr(
            close_table, leader, follower, event["start_date"]
        )
        if pd.isna(corr) or corr < threshold:
            continue

        mask = (
            (breakouts["symbol"] == follower)
            & (breakouts["trade_date"] >= event["start_date"])
            & (breakouts["trade_date"] <= end_date)
            & breakouts[direction_column]
        )
        start_dates = breakouts.loc[mask, "trade_date"].sort_values()
        follower_start = start_dates.iloc[0] if not start_dates.empty else pd.NaT
        if pd.isna(follower_start):
            follower_type = "潜在补涨" if event["direction"] == "上涨" else "潜在补跌"
        elif follower_start == event["start_date"]:
            follower_type = "同步弱势"
        else:
            follower_type = "滞后跟随"

        follower_return = move_table.at[follower, "raw_return"]
        rows.append({
            "sector": event["sector"],
            "direction": event["direction"],
            "start_date": event["start_date"],
            "leader": leader,
            "follower": follower,
            "rolling_corr_20": corr,
            "leader_return": leader_return,
            "follower_return": follower_return,
            "return_gap": leader_move - follower_move,
            "follower_start_date": follower_start,
            "follower_type": follower_type,
        })
    return rows


def confirm_leader(bars, breakouts, event):
    """按当前可见数据更新一个事件，确认日前绝不确认龙头。"""
    sector_bars = bars[bars["sector"] == event["sector"]]
    close_table = sector_bars.pivot(
        index="trade_date", columns="symbol", values="close"
    ).sort_index()
    sector_breakouts = breakouts[breakouts["sector"] == event["sector"]]
    earliest = event["earliest_symbols"].split("|")
    confirmed = pd.notna(event["confirm_date"])
    end_date = event["confirm_date"] if confirmed else event["analysis_date"]
    moves = calculate_event_returns(
        close_table, event["start_date"], end_date, event["direction"]
    )

    positive_moves = moves[moves["directional_move"] > 0]
    strongest = ""
    if not positive_moves.empty:
        strongest = positive_moves.sort_values(
            ["directional_move", "symbol"], ascending=[False, True]
        ).iloc[0]["symbol"]

    # 日线无法区分同日启动顺序，因此不强行选择唯一龙头。
    if len(earliest) > 1:
        row = _event_row(event, "同步启动", "", strongest, "", math.nan, 0)
        return row, []

    leader = earliest[0]
    leader_rows = moves[moves["symbol"] == leader]
    leader_return = (
        leader_rows.iloc[0]["raw_return"] if not leader_rows.empty else math.nan
    )
    followers = find_followers(
        close_table, sector_breakouts, event, leader, end_date, moves
    )

    if not confirmed:
        status = "龙头候选" if end_date == event["start_date"] else "确认中"
        row = _event_row(
            event, status, leader, strongest, "", leader_return, len(followers)
        )
        return row, followers

    if leader != strongest:
        status = "先行品种"
        strongest_status = "强势品种" if strongest else ""
    elif followers:
        status = "确认龙头"
        strongest_status = ""
    else:
        status = "独立行情"
        strongest_status = ""

    row = _event_row(
        event, status, leader, strongest, strongest_status,
        leader_return, len(followers),
    )
    return row, followers


def _event_row(
    event, status, leader, strongest, strongest_status, leader_return, follower_count
):
    return {
        "analysis_date": event["analysis_date"],
        "sector": event["sector"],
        "direction": event["direction"],
        "start_date": event["start_date"],
        "confirm_date": event["confirm_date"],
        "status": status,
        "leader": leader,
        "earliest_symbols": event["earliest_symbols"],
        "strongest_symbol": strongest,
        "strongest_status": strongest_status,
        "leader_return": leader_return,
        "follower_count": follower_count,
    }


def run_strategy(bars, as_of=None):
    """滚动运行策略；as_of 之后的数据会在入口处直接删除。"""
    data = normalize_daily_bars(bars)
    if as_of is not None:
        as_of = pd.Timestamp(as_of).normalize()
        data = data[data["trade_date"] <= as_of]
    if data.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS), pd.DataFrame(columns=FOLLOWER_COLUMNS)

    breakouts = find_breakouts(data)
    events = create_events(breakouts)
    event_rows = []
    follower_rows = []
    for event in events:
        event_row, followers = confirm_leader(data, breakouts, event)
        event_rows.append(event_row)
        follower_rows.extend(followers)

    leader_events = pd.DataFrame(event_rows, columns=EVENT_COLUMNS)
    followers = pd.DataFrame(follower_rows, columns=FOLLOWER_COLUMNS)
    if not leader_events.empty:
        leader_events = leader_events.sort_values(
            ["start_date", "sector", "direction"]
        ).reset_index(drop=True)
    if not followers.empty:
        followers = followers.sort_values(
            ["start_date", "sector", "leader", "follower"]
        ).reset_index(drop=True)
    return leader_events, followers
