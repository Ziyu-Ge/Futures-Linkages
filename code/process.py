from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "processed"

GROUPS = {
    "贵金属": "AU AG",
    "有色基本金属": "CU AL ZN PB NI SN AO",
    "新能源材料": "SI LC PS",
    "黑色钢矿": "I RB HC SS",
    "煤焦": "J JM",
    "铁合金": "SF SM",
    "能源油品": "SC FU LU BU PG",
    "橡胶": "RU NR BR",
    "聚酯产业链": "PX TA EG PF PR",
    "烯烃塑料": "L PP V EB PL",
    "煤化工建材": "MA SA FG UR",
    "谷物淀粉": "C CS",
    "油脂油料": "A B M RM PK",
    "软商品纺织": "CF CY SR",
    "果品": "AP CJ",
    "畜禽": "JD LH",
    "金融期货": "IF IM TL",
}
GROUP = {s: g for g, xs in GROUPS.items() for s in xs.split()}
COLS = "datetime open high low close volume total_turnover open_interest".split()


def daily(file):
    symbol = file.stem.upper()
    df = pd.read_csv(file, usecols=lambda c: c in COLS)
    dt = pd.to_datetime(df["datetime"])
    date = dt.dt.normalize()
    calendar = pd.Index(date[dt.dt.hour.between(9, 15)].drop_duplicates().sort_values())
    target = date + pd.to_timedelta(dt.dt.hour.ge(21).astype(int), unit="D")
    df["trade_date"] = calendar[
        calendar.searchsorted(target).clip(0, len(calendar) - 1)
    ].strftime("%Y-%m-%d")
    df = df.groupby("trade_date", as_index=False).agg(
        start=("datetime", "first"),
        end=("datetime", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        total_turnover=("total_turnover", "sum"),
        open_interest=("open_interest", "last"),
    )
    df.insert(0, "group", GROUP.get(symbol, "未分类"))
    df.insert(0, "symbol", symbol)
    return df


def symbol_returns(daily_bars=None):
    if daily_bars is None:
        daily_bars = pd.read_csv(OUT / "daily_bars.csv")

    daily_bars = daily_bars.sort_values(["symbol", "trade_date"]).copy()
    daily_bars["return"] = daily_bars.groupby("symbol")["close"].pct_change()
    return daily_bars.dropna(subset=["return"])[["trade_date", "group", "symbol", "return"]]


def main():
    files = sorted(DATA.glob("*.csv"))
    bars = pd.concat([daily(f) for f in files], ignore_index=True)
    groups = pd.DataFrame([(f.stem.upper(), GROUP.get(f.stem.upper(), "未分类")) for f in files], columns=["symbol", "group"])
    returns = symbol_returns(bars)

    (OUT / "by_group").mkdir(parents=True, exist_ok=True)
    groups.to_csv(OUT / "instrument_groups.csv", index=False, encoding="utf-8-sig")
    bars.to_csv(OUT / "daily_bars.csv", index=False, encoding="utf-8-sig")
    returns.to_csv(OUT / "symbol_returns.csv", index=False, encoding="utf-8-sig")
    for group, data in bars.groupby("group"):
        data.to_csv(OUT / "by_group" / f"{group}.csv", index=False, encoding="utf-8-sig")

    print(f"{len(files)} files -> {OUT}")


if __name__ == "__main__":
    main()
