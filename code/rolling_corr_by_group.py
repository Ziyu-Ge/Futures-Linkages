from itertools import combinations

import pandas as pd

from process import OUT, symbol_returns


WINDOWS = [20, 60, 120]
LAGS = [1, 2, 3, 5]


def write(df, file):
    header = not file.exists()
    df.to_csv(file, mode="a", header=header, index=False, encoding="utf-8-sig" if header else "utf-8")


def save_same_time(table, sector, window, file):
    for a, b in combinations(table.columns, 2):
        corr = table[a].rolling(window).corr(table[b]).dropna()
        rows = pd.DataFrame(
            {
                "date": corr.index,
                "sector": sector,
                "symbol_1": a,
                "symbol_2": b,
                "window": window,
                "rolling_corr": corr.values,
            }
        )
        write(rows, file)


def save_lead_lag(table, sector, window, lag, file):
    for leader in table.columns:
        for follower in table.columns:
            if leader == follower:
                continue

            lead = table[leader].rolling(window).corr(table[follower].shift(-lag))
            reverse = table[follower].rolling(window).corr(table[leader].shift(-lag))
            rows = pd.DataFrame(
                {
                    "date": table.index,
                    "sector": sector,
                    "leader": leader,
                    "follower": follower,
                    "window": window,
                    "lag": lag,
                    "rolling_lead_corr": lead.values,
                    "reverse_rolling_lead_corr": reverse.values,
                    "lead_strength": lead.values - reverse.values,
                }
            ).dropna()
            write(rows, file)


def main():
    returns = symbol_returns()
    out = OUT / "rolling_corr_by_group"
    out.mkdir(parents=True, exist_ok=True)

    same_time_file = out / "rolling_same_time_corr.csv"
    lead_file = out / "rolling_lead_corr.csv"
    for file in [same_time_file, lead_file]:
        if file.exists():
            file.unlink()

    for sector, data in returns.groupby("group"):
        table = data.pivot(index="trade_date", columns="symbol", values="return").sort_index()

        for window in WINDOWS:
            save_same_time(table, sector, window, same_time_file)
            for lag in LAGS:
                save_lead_lag(table, sector, window, lag, lead_file)

        print(f"{sector}: {len(table.columns)} symbols")

    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
