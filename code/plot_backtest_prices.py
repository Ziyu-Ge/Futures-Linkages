"""画做空回测交易的分钟价格走势。

每条线是一笔交易，从开空时间画到平空时间。
为了把不同品种放在同一张图上，价格统一换算成相对开空价的涨跌幅。
"""

from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "results" / ".matplotlib-cache"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


DATA_DIR = ROOT / "data"
TRADE_FILE = ROOT / "results" / "short_backtest" / "trades.csv"
OUT_FILE = ROOT / "results" / "figures" / "short_backtest_price_paths.png"


def setup_chinese_font():
    plt.rcParams["font.sans-serif"] = [
        "PingFang SC", "Heiti SC", "Microsoft YaHei", "SimHei", "Arial Unicode MS"
    ]
    plt.rcParams["axes.unicode_minus"] = False


def read_trades():
    return pd.read_csv(
        TRADE_FILE,
        parse_dates=["识别时间", "开空时间", "平空时间"],
    )


def read_minutes(symbol):
    file = DATA_DIR / f"{symbol}.csv"
    data = pd.read_csv(file, usecols=["datetime", "close"])
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data = data.dropna(subset=["datetime", "close"])
    return data.sort_values("datetime")


def trade_price_path(trade, minutes):
    start = trade["开空时间"]
    end = trade["平空时间"]
    path = minutes.loc[minutes["datetime"].between(start, end)].copy()
    if path.empty:
        return path

    path = path.reset_index(drop=True)
    path["开空后K线数"] = path.index
    path["相对开空价涨跌幅"] = path["close"] / trade["开空价"] - 1
    return path


def main():
    setup_chinese_font()
    trades = read_trades()

    fig, ax = plt.subplots(figsize=(11, 6))
    for symbol, symbol_trades in trades.groupby("跟涨品种"):
        minutes = read_minutes(symbol)
        for _, trade in symbol_trades.iterrows():
            path = trade_price_path(trade, minutes)
            if path.empty:
                continue
            color = "#2563eb" if trade["净收益率"] > 0 else "#dc2626"
            ax.plot(
                path["开空后K线数"],
                path["相对开空价涨跌幅"] * 100,
                color=color,
                alpha=0.28,
                linewidth=1.2,
            )

    ax.axhline(0, color="#111827", linewidth=1)
    ax.set_title("做空回测交易价格走势")
    ax.set_xlabel("开空后分钟K线根数")
    ax.set_ylabel("价格相对开空价涨跌幅（%）")
    ax.text(
        0.01, 0.02,
        "蓝线：做空盈利；红线：做空亏损",
        transform=ax.transAxes,
        fontsize=10,
        color="#4b5563",
    )
    ax.grid(True, color="#e5e7eb", linewidth=0.8)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT_FILE, dpi=150)
    print(f"已输出: {OUT_FILE}")


if __name__ == "__main__":
    main()
