import warnings

import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests

from process import OUT, symbol_returns


LAGS = [1, 2, 3, 5]
ALPHA = 0.05


def granger_pvalue(table, leader, follower, lag):
    data = table[[follower, leader]].dropna()
    if len(data) <= 3 * lag + 1:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = grangercausalitytests(data, maxlag=[lag], verbose=False)

    return result[lag][0]["ssr_ftest"][1]


def main():
    returns = symbol_returns()
    out = OUT / "granger_by_group"
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    for sector, data in returns.groupby("group"):
        table = data.pivot(index="trade_date", columns="symbol", values="return").sort_index()

        for leader in table.columns:
            for follower in table.columns:
                if leader == follower:
                    continue

                for lag in LAGS:
                    p_value = granger_pvalue(table, leader, follower, lag)
                    rows.append(
                        {
                            "sector": sector,
                            "leader_candidate": leader,
                            "follower_candidate": follower,
                            "lag": lag,
                            "p_value": p_value,
                            "is_granger_significant": p_value is not None and p_value < ALPHA,
                        }
                    )

        print(f"{sector}: {len(table.columns)} symbols")

    result = pd.DataFrame(rows)
    result.to_csv(out / "granger_results.csv", index=False, encoding="utf-8-sig")
    result[result["is_granger_significant"]].to_csv(
        out / "significant_granger_edges.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
