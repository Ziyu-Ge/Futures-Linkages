import pandas as pd

from process import OUT, symbol_returns


LAGS = [1, 2, 3, 5]
THRESHOLD = 0.05


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
                        "lag_corr": lag_corr,
                        "reverse_lag_corr": reverse_corr,
                        "lead_edge": edge,
                    }
                )
    return rows


def main():
    returns = symbol_returns()
    out = OUT / "lag_corr_by_group"
    all_edges = []

    for group, data in returns.groupby("group"):
        table = data.pivot(index="trade_date", columns="symbol", values="return")

        for lag in LAGS:
            corr = lag_corr_matrix(table, lag)
            folder = out / f"lag_{lag}"
            folder.mkdir(parents=True, exist_ok=True)
            corr.to_csv(folder / f"{group}.csv", encoding="utf-8-sig")
            all_edges += lead_edges(corr, lag, group)

            print(f"{group} lag={lag}: {len(corr)} symbols -> {folder / f'{group}.csv'}")

    pd.DataFrame(all_edges).to_csv(out / "lead_edges.csv", index=False, encoding="utf-8-sig")
    print(f"\nSaved lead edges to {out / 'lead_edges.csv'}")


if __name__ == "__main__":
    main()
