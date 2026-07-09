from pathlib import Path
import os
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "processed"
FIG = ROOT / "figures" / "price_compare_by_sector"


def top_pairs(df, n=6):
    df = df.sort_values("score", ascending=False).copy()
    df["pair"] = df.apply(lambda x: "-".join(sorted([x["leader"], x["follower"]])), axis=1)
    return df.drop_duplicates("pair").head(n)


def prices(bars, a, b):
    df = bars[bars["symbol"].isin([a, b])]
    df = df.pivot(index="trade_date", columns="symbol", values="close").dropna()
    if df.empty:
        return df
    return df[[a, b]].div(df.iloc[0]).mul(100)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    bars = pd.read_csv(OUT / "daily_bars.csv", parse_dates=["trade_date"])
    scores = pd.read_csv(OUT / "leading_score_by_group" / "leading_scores.csv")

    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    for sector, df in scores.groupby("sector"):
        pairs = top_pairs(df)
        fig, axes = plt.subplots(3, 2, figsize=(12, 9))
        axes = axes.ravel()

        for ax, (_, row) in zip(axes, pairs.iterrows()):
            leader, follower = row["leader"], row["follower"]
            p = prices(bars, leader, follower)
            lag = "" if pd.isna(row["best_lag"]) else f", lag={int(row['best_lag'])}"

            if p.empty:
                ax.set_visible(False)
                continue

            p.plot(ax=ax, lw=1.2)
            ax.set_title(f"{leader} -> {follower}, score={row['score']:.2f}{lag}", fontsize=10)
            ax.set_xlabel("")
            ax.set_ylabel("close=100")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)
            ax.tick_params(axis="x", labelrotation=35)

        for ax in axes[len(pairs):]:
            ax.set_visible(False)

        fig.suptitle(f"{sector} top {len(pairs)} price pairs")
        fig.tight_layout()
        fig.savefig(FIG / f"{sector}.png", dpi=150)
        plt.close(fig)
        print(f"{sector}: {len(pairs)} pairs -> {FIG / f'{sector}.png'}")


if __name__ == "__main__":
    main()
