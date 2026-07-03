from process import OUT, symbol_returns


def main():
    returns = symbol_returns()
    out = OUT / "instrument_corr_by_group"
    out.mkdir(parents=True, exist_ok=True)

    for group, data in returns.groupby("group"):
        table = data.pivot(index="trade_date", columns="symbol", values="return")
        corr = table.corr()
        corr.to_csv(out / f"{group}.csv", encoding="utf-8-sig")
        print(f"{group}: {len(corr)} symbols -> {out / f'{group}.csv'}")


if __name__ == "__main__":
    main()
