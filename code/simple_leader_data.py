from pathlib import Path

import pandas as pd

from simple_leader_config import DAILY_BARS_FILE, DATA_DIR, SYMBOL_TO_SECTOR


DAILY_COLUMNS = ["trade_date", "sector", "symbol", "close"]


def normalize_daily_bars(data):
    """统一日线字段，只留下日期、板块、品种和收盘价。"""
    data = data.copy()
    if "group" in data.columns and "sector" not in data.columns:
        data = data.rename(columns={"group": "sector"})

    required = {"trade_date", "symbol", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"日线数据缺少字段: {sorted(missing)}")

    data["symbol"] = data["symbol"].astype(str).str.upper()
    if "sector" not in data.columns:
        data["sector"] = data["symbol"].map(SYMBOL_TO_SECTOR)
    else:
        mapped = data["symbol"].map(SYMBOL_TO_SECTOR)
        data["sector"] = data["sector"].fillna(mapped)

    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.normalize()
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["trade_date", "sector", "symbol", "close"])
    data = data[data["close"] > 0]
    data = data[DAILY_COLUMNS].sort_values(["sector", "symbol", "trade_date"])
    return data.drop_duplicates(["sector", "symbol", "trade_date"], keep="last")


def minute_file_to_daily(file):
    """把一个分钟文件聚合成日收盘价，不读取成交量等无关字段。"""
    symbol = file.stem.upper()
    sector = SYMBOL_TO_SECTOR.get(symbol)
    if sector is None:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    data = pd.read_csv(file, usecols=["datetime", "close"])
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna().sort_values("datetime")

    # 21点后的夜盘归到下一个有日盘数据的交易日。
    raw_date = data["datetime"].dt.normalize()
    daytime = data["datetime"].dt.hour.between(9, 15)
    calendar = pd.Index(raw_date[daytime].drop_duplicates().sort_values())
    if calendar.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    target = raw_date + pd.to_timedelta(
        data["datetime"].dt.hour.ge(21).astype(int), unit="D"
    )
    positions = calendar.searchsorted(target)
    valid = positions < len(calendar)
    data = data.loc[valid, ["datetime", "close"]].copy()
    data["trade_date"] = calendar.take(positions[valid]).to_numpy()

    daily = data.groupby("trade_date", as_index=False)["close"].last()
    daily.insert(1, "sector", sector)
    daily.insert(2, "symbol", symbol)
    return daily[DAILY_COLUMNS]


def load_minute_files(data_dir=DATA_DIR):
    """逐个读取分钟文件，避免同时把全部原始数据放进内存。"""
    parts = []
    files = sorted(Path(data_dir).glob("*.csv"))
    for file in files:
        daily = minute_file_to_daily(file)
        if not daily.empty:
            parts.append(daily)
    if not parts:
        raise FileNotFoundError(f"没有找到可用行情文件: {data_dir}")
    return normalize_daily_bars(pd.concat(parts, ignore_index=True))


def load_daily_bars(path=None):
    """优先读取指定日线；没有日线时才从分钟文件生成。"""
    if path is not None:
        file = Path(path)
        if not file.exists():
            raise FileNotFoundError(f"日线文件不存在: {file}")
        return normalize_daily_bars(pd.read_csv(file))

    if DAILY_BARS_FILE.exists():
        return normalize_daily_bars(pd.read_csv(DAILY_BARS_FILE))
    return load_minute_files()
