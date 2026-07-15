"""逐品种读取分钟数据，并压缩为日线和小时状态。"""

import gc
from pathlib import Path

import numpy as np
import pandas as pd

from config import GROUP, HISTORY_DAYS, MINUTE_COLUMNS, NUMERIC_COLUMNS


def safe_change(numerator, denominator):
    """分母为 0 或任一值缺失时返回 NaN。"""
    valid = numerator.notna() & denominator.notna() & denominator.ne(0)
    result = pd.Series(np.nan, index=numerator.index, dtype="float64")
    result.loc[valid] = numerator.loc[valid] / denominator.loc[valid] - 1.0
    return result.replace([np.inf, -np.inf], np.nan)


def read_minutes(file):
    """只读规则需要的列，并保证每个分钟时点唯一且有序。"""
    header = pd.read_csv(file, nrows=0).columns
    missing = sorted(set(MINUTE_COLUMNS) - set(header))
    if missing:
        raise ValueError(f"{file.name} 缺少字段: {', '.join(missing)}")

    df = pd.read_csv(
        file,
        usecols=MINUTE_COLUMNS,
        dtype={column: "float64" for column in NUMERIC_COLUMNS},
        parse_dates=["datetime"],
        date_format="mixed",
    )
    df = df.dropna(subset=["datetime"])
    df = df.sort_values("datetime", kind="mergesort")
    return df.drop_duplicates("datetime", keep="last").reset_index(drop=True)


def assign_trade_date(df):
    """夜盘映射到该品种下一个真实出现日盘的交易日。"""
    natural_date = df["datetime"].dt.normalize()
    day_mask = df["datetime"].dt.hour.between(8, 17)
    calendar = pd.DatetimeIndex(natural_date.loc[day_mask].drop_duplicates().sort_values())
    if calendar.empty:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")

    # 晚盘先指向次日，再向后找下一个真实日盘，自动跨周末/节假日。
    target = natural_date + pd.to_timedelta(
        df["datetime"].dt.hour.ge(18).astype("int8"), unit="D"
    )
    position = calendar.searchsorted(target)
    valid = position < len(calendar)
    trade_date = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    trade_date.loc[valid] = calendar.take(position[valid]).to_numpy()
    return trade_date


def make_daily(df, symbol, group):
    """按交易日合成完整日 K，并只用前 20 个完整日生成历史指标。"""
    grouped = df.groupby("trade_date", sort=True, observed=True)
    first = grouped.nth(0).set_index("trade_date")
    last = grouped.nth(-1).set_index("trade_date")
    daily = pd.DataFrame(index=first.index)
    daily.index.name = "trade_date"
    daily["day_start_time"] = first["datetime"]
    daily["day_end_time"] = last["datetime"]
    daily["day_open"] = first["open"]
    daily["day_high"] = grouped["high"].max()
    daily["day_low"] = grouped["low"].min()
    daily["day_close"] = last["close"]
    daily["day_oi_open"] = first["open_interest"]
    daily["day_oi_close"] = last["open_interest"]
    daily["daily_return"] = safe_change(daily["day_close"], daily["day_open"])
    daily["daily_oi_change"] = safe_change(daily["day_oi_close"], daily["day_oi_open"])

    previous = daily.shift(1)
    rolling = previous.rolling(HISTORY_DAYS, min_periods=HISTORY_DAYS)
    daily["prior_high"] = rolling["day_high"].max()
    daily["prior_low"] = rolling["day_low"].min()
    daily["avg_abs_return"] = rolling["daily_return"].apply(
        lambda values: np.abs(values).mean(), raw=True
    )
    daily["avg_abs_oi_change"] = rolling["daily_oi_change"].apply(
        lambda values: np.abs(values).mean(), raw=True
    )
    dates = daily.index.to_series()
    daily["window_start"] = dates.shift(HISTORY_DAYS).to_numpy()
    daily["window_end"] = dates.shift(1).to_numpy()
    daily.insert(0, "group", group)
    daily.insert(0, "symbol", symbol)
    return daily.reset_index()


def first_breaks(df, daily):
    """用分钟高低价记录每天首次严格突破的准确时间和价格。"""
    indexed = daily.set_index("trade_date")
    prior_high = df["trade_date"].map(indexed["prior_high"])
    prior_low = df["trade_date"].map(indexed["prior_low"])

    up = df.loc[df["high"].gt(prior_high), ["trade_date", "datetime", "high"]]
    down = df.loc[df["low"].lt(prior_low), ["trade_date", "datetime", "low"]]
    up = up.drop_duplicates("trade_date", keep="first").set_index("trade_date")
    down = down.drop_duplicates("trade_date", keep="first").set_index("trade_date")
    return (
        up.rename(columns={"datetime": "up_break_time", "high": "up_break_price"}),
        down.rename(columns={"datetime": "down_break_time", "low": "down_break_price"}),
    )


def make_hours(df, daily, symbol, group):
    """生成自然小时收盘收益率，以及每小时可见的当下日 K。"""
    df["hour_key"] = df["datetime"].dt.floor("h")
    grouped = df.groupby(["trade_date", "hour_key"], sort=True, observed=True)
    last = grouped.nth(-1).reset_index()
    hours = grouped.agg(hour_high=("high", "max"), hour_low=("low", "min")).reset_index()
    hours = hours.merge(
        last[["trade_date", "hour_key", "datetime", "close", "open_interest"]],
        on=["trade_date", "hour_key"],
        how="left",
        validate="one_to_one",
    ).rename(columns={"datetime": "snapshot_time", "close": "hour_close"})
    hours = hours.sort_values("hour_key", kind="mergesort").reset_index(drop=True)
    hours["hour_return"] = hours["hour_close"].pct_change(fill_method=None)
    hours["hour_return"] = hours["hour_return"].replace([np.inf, -np.inf], np.nan)
    hours["next_hour_time"] = hours["snapshot_time"].shift(-1)
    hours["next_hour_return"] = hours["hour_return"].shift(-1)

    # 当前日 K 只累计到该小时，绝不使用本小时之后的分钟。
    by_day = hours.groupby("trade_date", sort=False, observed=True)
    hours["current_high"] = by_day["hour_high"].cummax()
    hours["current_low"] = by_day["hour_low"].cummin()
    daily_columns = [
        "trade_date", "day_open", "day_oi_open", "prior_high", "prior_low",
        "avg_abs_return", "avg_abs_oi_change", "window_start", "window_end",
    ]
    hours = hours.merge(daily[daily_columns], on="trade_date", how="left", validate="many_to_one")
    hours["current_return"] = safe_change(hours["hour_close"], hours["day_open"])
    hours["current_oi_change"] = safe_change(hours["open_interest"], hours["day_oi_open"])
    up, down = first_breaks(df, daily)
    hours = hours.merge(up, on="trade_date", how="left").merge(down, on="trade_date", how="left")
    hours.insert(0, "group", group)
    hours.insert(0, "symbol", symbol)
    return hours


def prepare_symbol(file):
    symbol = file.stem.upper()
    group = GROUP.get(symbol, "未分类")
    df = read_minutes(file)
    df["trade_date"] = assign_trade_date(df)
    df = df.dropna(subset=["trade_date"])
    daily = make_daily(df, symbol, group)
    hours = make_hours(df, daily, symbol, group)
    return daily, hours


def prepare_all(data_dir):
    """所有分钟文件逐个处理；内存中只长期保留压缩后的表。"""
    files = sorted(Path(data_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"{data_dir} 中没有 CSV 数据")
    daily_parts, snapshot_parts, hourly_by_symbol = [], [], {}
    for number, file in enumerate(files, start=1):
        daily, hours = prepare_symbol(file)
        daily_parts.append(daily)
        # 下一小时字段只放辅助验证查找表，不进入历史截面。
        snapshot_parts.append(hours.drop(columns=["next_hour_time", "next_hour_return"]))
        hourly_by_symbol[file.stem.upper()] = hours[[
            "trade_date", "hour_key", "snapshot_time", "hour_return",
            "next_hour_time", "next_hour_return",
        ]].copy()
        print(f"预处理 {number:02d}/{len(files):02d}: {file.stem.upper()}", flush=True)
        gc.collect()
    daily_all = pd.concat(daily_parts, ignore_index=True)
    snapshots = pd.concat(snapshot_parts, ignore_index=True)
    return daily_all, snapshots, hourly_by_symbol
