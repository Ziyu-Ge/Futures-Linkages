import warnings

import pandas as pd
from statsmodels.tsa.api import VAR

from process import OUT, symbol_returns


LAGS = [1, 2, 3, 5]
ALPHA = 0.05


def var_rows(sector, table, model_lag):
    data = table.dropna()
    if data.shape[1] < 2 or len(data) <= model_lag + 5:
        return []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = VAR(data).fit(model_lag)

    rows = []
    for term in result.params.index:
        if term == "const":
            continue

        lag_name, leader = term.split(".", 1)
        for follower in result.names:
            p_value = result.pvalues.loc[term, follower]
            rows.append(
                {
                    "sector": sector,
                    "model_lag": model_lag,
                    "predictor_lag": int(lag_name[1:]),
                    "leader_candidate": leader,
                    "follower_candidate": follower,
                    "var_coefficient": result.params.loc[term, follower],
                    "var_p_value": p_value,
                    "is_var_significant": p_value < ALPHA,
                }
            )
    return rows


def main():
    returns = symbol_returns()
    out = OUT / "var_by_group"
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    for sector, data in returns.groupby("group"):
        table = data.pivot(index="trade_date", columns="symbol", values="return").sort_index()
        for lag in LAGS:
            rows += var_rows(sector, table, lag)
        print(f"{sector}: {len(table.columns)} symbols")

    result = pd.DataFrame(rows)
    result.to_csv(out / "var_coefficients.csv", index=False, encoding="utf-8-sig")
    result[result["is_var_significant"]].to_csv(
        out / "significant_var_coefficients.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
