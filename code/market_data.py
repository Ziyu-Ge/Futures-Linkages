"""读取分钟行情，并生成日 K 与每小时可见的当下日 K。"""

import gc
from pathlib import Path

import numpy as np
import pandas as pd

from config import GROUP, HISTORY_DAYS, MINUTE_COLUMNS, NUMERIC_COLUMNS


def safe_pct_change(current, previous):
    """计算 current / previous - 1，分母缺失或为 0 时返回 NaN。"""
    valid = current.notna() & previous.notna() & previous.ne(0)
    result = pd.Series(np.nan, index=current.index, dtype="float64")
    result.loc[valid] = current.loc[valid] / previous.loc[valid] - 1.0
    return result.replace([np.inf, -np.inf], np.nan)


def read_minutes(file):
    """只读取规则需要的列，并按时间排序去重。"""
    header = pd.read_csv(file, nrows=0).columns
    missing = sorted(set(MINUTE_COLUMNS) - set(header))
    if missing:
        raise ValueError(f"{file.name} 缺少字段: {', '.join(missing)}")

    df = pd.read_csv(
        file,
        usecols=MINUTE_COLUMNS,
        dtype={column: "float64" for column in NUMERIC_COLUMNS},
        parse_dates=["datetime"],
    )
    df = df.dropna(subset=["datetime"]).sort_values("datetime", kind="mergesort")
    return df.drop_duplicates("datetime", keep="last").reset_index(drop=True)


def assign_trade_date(df):
    """把夜盘映射到下一个真实日盘交易日，自动跨过周末和节假日。"""
    natural_date = df["datetime"].dt.normalize()
    day_mask = df["datetime"].dt.hour.between(8, 17)
    calendar = pd.DatetimeIndex(natural_date.loc[day_mask].drop_duplicates().sort_values())
    if calendar.empty:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")

    # 18:00 之后视作夜盘，先指向下一自然日，再找下一个真实日盘日期。
    target = natural_date + pd.to_timedelta(
        df["datetime"].dt.hour.ge(18).astype("int8"), unit="D"
    )
    position = calendar.searchsorted(target)
    valid = position < len(calendar)
    trade_date = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    trade_date.loc[valid] = calendar.take(position[valid]).to_numpy()
    return trade_date


def add_history_factors(daily):
    """用今天以前的完整日 K，计算前 20 日突破价和平均波动阈值。"""
    daily = daily.sort_values("trade_date", kind="mergesort").copy()
    daily["prev_close"] = daily["close"].shift(1)
    daily["prev_open_interest"] = daily["open_interest"].shift(1)
    daily["return"] = safe_pct_change(daily["close"], daily["prev_close"])
    daily["oi_change"] = safe_pct_change(
        daily["open_interest"], daily["prev_open_interest"]
    )

    previous = daily.shift(1)
    rolling = previous.rolling(HISTORY_DAYS, min_periods=HISTORY_DAYS)
    daily["prior_20_high"] = rolling["high"].max()
    daily["prior_20_low"] = rolling["low"].min()
    daily["avg_abs_return_20"] = rolling["return"].apply(
        lambda values: np.abs(values).mean(), raw=True
    )
    daily["avg_abs_oi_change_20"] = rolling["oi_change"].apply(
        lambda values: np.abs(values).mean(), raw=True
    )
    dates = daily["trade_date"]
    daily["history_start"] = dates.shift(HISTORY_DAYS)
    daily["history_end"] = dates.shift(1)
    return daily


def make_daily(df, symbol, group):
    """把分钟数据合成完整交易日日 K。"""
    grouped = df.groupby("trade_date", sort=True, observed=True)
    first = grouped.nth(0).set_index("trade_date")
    last = grouped.nth(-1).set_index("trade_date")

    daily = pd.DataFrame(index=first.index)
    daily.index.name = "trade_date"
    daily["open"] = first["open"]
    daily["high"] = grouped["high"].max()
    daily["low"] = grouped["low"].min()
    daily["close"] = last["close"]
    daily["open_interest"] = last["open_interest"]
    daily["day_start_time"] = first["datetime"]
    daily["day_end_time"] = last["datetime"]
    daily = add_history_factors(daily.reset_index())
    daily.insert(0, "group", group)
    daily.insert(0, "symbol", symbol)
    return daily


def first_break_times(df, daily):
    """记录每个交易日第一次突破前 20 日高低点的分钟时间。"""
    history = daily.set_index("trade_date")
    prior_high = df["trade_date"].map(history["prior_20_high"])
    prior_low = df["trade_date"].map(history["prior_20_low"])

    up = df.loc[df["high"].gt(prior_high), ["trade_date", "datetime", "high"]]
    down = df.loc[df["low"].lt(prior_low), ["trade_date", "datetime", "low"]]
    up = up.drop_duplicates("trade_date", keep="first").set_index("trade_date")
    down = down.drop_duplicates("trade_date", keep="first").set_index("trade_date")
    up = up.rename(columns={"datetime": "up_break_time", "high": "up_break_price"})
    down = down.rename(columns={"datetime": "down_break_time", "low": "down_break_price"})
    return up, down


def make_hourly_snapshots(df, daily, symbol, group):
    """生成每个自然小时收盘时，交易日内已经可见的当下日 K。"""
    work = df.copy()
    work["identify_hour"] = work["datetime"].dt.floor("h")
    grouped = work.groupby(["trade_date", "identify_hour"], sort=True, observed=True)
    last = grouped.nth(-1).reset_index()
    hourly = grouped.agg(hour_high=("high", "max"), hour_low=("low", "min")).reset_index()
    hourly = hourly.merge(
        last[["trade_date", "identify_hour", "datetime", "close", "open_interest"]],
        on=["trade_date", "identify_hour"],
        how="left",
        validate="one_to_one",
    ).rename(columns={"datetime": "snapshot_time"})

    # 当前未完成日 K：只累计到本小时，不使用本小时之后的分钟。
    by_day = hourly.groupby("trade_date", sort=False, observed=True)
    hourly["high"] = by_day["hour_high"].cummax()
    hourly["low"] = by_day["hour_low"].cummin()

    daily_cols = [
        "trade_date", "open", "prev_close", "prev_open_interest", "prior_20_high",
        "prior_20_low", "avg_abs_return_20", "avg_abs_oi_change_20",
        "history_start", "history_end",
    ]
    hourly = hourly.merge(
        daily[daily_cols], on="trade_date", how="left", validate="many_to_one"
    )
    hourly["return"] = safe_pct_change(hourly["close"], hourly["prev_close"])
    hourly["oi_change"] = safe_pct_change(
        hourly["open_interest"], hourly["prev_open_interest"]
    )

    up, down = first_break_times(df, daily)
    hourly = hourly.merge(up, on="trade_date", how="left")
    hourly = hourly.merge(down, on="trade_date", how="left")
    hourly.insert(0, "group", group)
    hourly.insert(0, "symbol", symbol)
    return hourly


def prepare_symbol(file):
    """读取单个品种，返回完整日 K 和每小时当前日 K。"""
    symbol = file.stem.upper()
    group = GROUP.get(symbol, "未分类")
    minutes = read_minutes(file)
    minutes["trade_date"] = assign_trade_date(minutes)
    minutes = minutes.dropna(subset=["trade_date"])
    daily = make_daily(minutes, symbol, group)
    hourly = make_hourly_snapshots(minutes, daily, symbol, group)
    return daily, hourly


def prepare_all(data_dir, symbols=None):
    """逐品种处理数据，避免一次性把 4GB 分钟数据放进内存。"""
    wanted = {symbol.upper() for symbol in symbols} if symbols else None
    files = sorted(Path(data_dir).glob("*.csv"))
    if wanted:
        files = [file for file in files if file.stem.upper() in wanted]
    if not files:
        raise FileNotFoundError(f"{data_dir} 中没有可处理的 CSV 文件")

    daily_parts, snapshot_parts = [], []
    for number, file in enumerate(files, start=1):
        daily, hourly = prepare_symbol(file)
        daily_parts.append(daily)
        snapshot_parts.append(hourly)
        print(f"预处理 {number:02d}/{len(files):02d}: {file.stem.upper()}", flush=True)
        gc.collect()
    return pd.concat(daily_parts, ignore_index=True), pd.concat(snapshot_parts, ignore_index=True)
