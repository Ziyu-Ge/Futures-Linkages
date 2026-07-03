import pandas as pd

from process import OUT, symbol_returns


LAGS = [1, 2, 3, 5]
THRESHOLD = 0.05


def make_residuals(table):
    eps = pd.DataFrame(index=table.index, columns=table.columns, dtype=float)

    for symbol in table.columns:
        r = table[symbol]
        factor = table.drop(columns=symbol).mean(axis=1)
        data = pd.concat({"r": r, "factor": factor}, axis=1).dropna()

        if len(data) < 3 or data["factor"].var() == 0:
            continue

        beta = data["r"].cov(data["factor"]) / data["factor"].var()
        alpha = data["r"].mean() - beta * data["factor"].mean()
        eps.loc[data.index, symbol] = data["r"] - alpha - beta * data["factor"]

    eps.index.name = "trade_date"
    return eps


def lag_corr_matrix(table, lag):
    future = table.shift(-lag)
    corr = pd.DataFrame(index=table.columns, columns=table.columns, dtype=float)

    for lead in table.columns:
        for follow in table.columns:
            if lead != follow:
                corr.loc[lead, follow] = table[lead].corr(future[follow])

    corr.index.name = "lead_symbol"
    return corr


def lead_edges(corr, lag, group):
    rows = []
    for lead in corr.index:
        for follow in corr.columns:
            if lead == follow:
                continue

            lag_corr = corr.loc[lead, follow]
            reverse_corr = corr.loc[follow, lead]
            edge = lag_corr - reverse_corr

            if abs(lag_corr) >= THRESHOLD and edge >= THRESHOLD:
                rows.append(
                    {
                        "group": group,
                        "lag": lag,
                        "lead": lead,
                        "follow": follow,
                        "residual_lag_corr": lag_corr,
                        "reverse_residual_lag_corr": reverse_corr,
                        "residual_lead_edge": edge,
                    }
                )
    return rows


def main():
    returns = symbol_returns()
    out = OUT / "residual_corr_by_group"
    all_edges = []

    for group, data in returns.groupby("group"):
        table = data.pivot(index="trade_date", columns="symbol", values="return")
        eps = make_residuals(table)

        (out / "residuals").mkdir(parents=True, exist_ok=True)
        (out / "same_time_corr").mkdir(parents=True, exist_ok=True)
        eps.to_csv(out / "residuals" / f"{group}.csv", encoding="utf-8-sig")
        eps.corr().to_csv(out / "same_time_corr" / f"{group}.csv", encoding="utf-8-sig")

        for lag in LAGS:
            corr = lag_corr_matrix(eps, lag)
            folder = out / "lag_corr" / f"lag_{lag}"
            folder.mkdir(parents=True, exist_ok=True)
            corr.to_csv(folder / f"{group}.csv", encoding="utf-8-sig")
            all_edges += lead_edges(corr, lag, group)

        print(f"{group}: {len(eps.columns)} symbols -> {out}")

    pd.DataFrame(all_edges).to_csv(out / "residual_lead_edges.csv", index=False, encoding="utf-8-sig")
    print(f"\nSaved residual lead edges to {out / 'residual_lead_edges.csv'}")


if __name__ == "__main__":
    main()
