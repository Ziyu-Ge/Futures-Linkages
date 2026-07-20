"""回测策略：龙头向下时，做空同板块的跟随期货。

开空：“向下”跟随信号出现后的下一根分钟 K 线开盘价。
平空：当个交易日最后一根分钟 K 线收盘价。
仓位：同一品种同一交易日只做一次；当日多个品种等权。
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data"
DEFAULT_INPUT = ROOT / "results" / "identification"
DEFAULT_OUTPUT = ROOT / "results" / "short_backtest"


def parse_args():
    parser = argparse.ArgumentParser(description="龙头下跌、做空跟随期货的简单回测")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA), help="分钟行情目录")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT), help="识别结果目录")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="回测输出目录")
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.0,
        help="单边费率，如万分之一填 0.0001，默认不计手续费",
    )
    return parser.parse_args()


def load_candidates(input_dir):
    """只保留向下信号，同一品种当日取最早一次。"""
    input_dir = Path(input_dir)
    signals = pd.read_csv(
        input_dir / "follower_results.csv",
        parse_dates=["识别时间", "交易日"],
    )
    daily = pd.read_csv(
        input_dir / "daily_bars.csv",
        usecols=["symbol", "trade_date", "close", "day_end_time"],
        parse_dates=["trade_date", "day_end_time"],
    )

    signals = signals.loc[signals["方向"].eq("向下")].copy()
    signals = signals.sort_values("识别时间", kind="mergesort")
    signals = signals.drop_duplicates(["交易日", "跟涨品种"], keep="first")

    candidates = signals.merge(
        daily,
        left_on=["交易日", "跟涨品种"],
        right_on=["trade_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    return candidates, daily


def add_entry_prices(candidates, data_dir):
    """从分钟数据找到信号之后的第一个开盘价。"""
    parts = []
    for symbol, signals in candidates.groupby("跟涨品种", sort=True):
        file = Path(data_dir) / f"{symbol}.csv"
        if not file.exists():
            print(f"跳过 {symbol}：缺少 {file}")
            continue

        minutes = pd.read_csv(file, usecols=["datetime", "open"])
        minutes["datetime"] = pd.to_datetime(minutes["datetime"], errors="coerce")
        minutes = minutes.dropna(subset=["datetime", "open"])
        minutes = minutes.sort_values("datetime", kind="mergesort")
        minutes = minutes.drop_duplicates("datetime", keep="last").reset_index(drop=True)

        block = signals.copy()
        positions = minutes["datetime"].searchsorted(block["识别时间"], side="right")
        valid = positions < len(minutes)
        block = block.loc[valid].copy()
        positions = positions[valid]
        block["开空时间"] = minutes.iloc[positions]["datetime"].to_numpy()
        block["开空价"] = minutes.iloc[positions]["open"].to_numpy()
        parts.append(block)
        print(f"读取 {symbol}：{len(block)} 个候选交易")

    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def make_trades(candidates, fee_rate):
    """检查开平仓时间，并计算每笔做空收益。"""
    if candidates.empty:
        return candidates

    valid = (
        candidates["开空时间"].le(candidates["day_end_time"])
        & candidates["开空价"].gt(0)
        & candidates["close"].gt(0)
    )
    trades = candidates.loc[valid].copy()
    trades["平空时间"] = trades["day_end_time"]
    trades["平空价"] = trades["close"]
    trades["税前收益率"] = trades["开空价"] / trades["平空价"] - 1.0
    trades["净收益率"] = trades["税前收益率"] - 2.0 * fee_rate

    columns = [
        "交易日", "龙头品种", "跟涨品种", "板块", "识别时间",
        "开空时间", "开空价", "平空时间", "平空价", "税前收益率", "净收益率",
    ]
    return trades[columns].sort_values(["交易日", "跟涨品种"]).reset_index(drop=True)


def calculate_performance(trades, daily):
    """按当日所有交易等权，计算净值、最大回撤和夏普。"""
    if trades.empty:
        return pd.DataFrame(), pd.DataFrame()

    first_date, last_date = trades["交易日"].min(), trades["交易日"].max()
    calendar = daily.loc[
        daily["trade_date"].between(first_date, last_date), "trade_date"
    ].drop_duplicates().sort_values()
    daily_return = trades.groupby("交易日")["净收益率"].mean()

    curve = pd.DataFrame({"交易日": calendar})
    curve["当日收益率"] = curve["交易日"].map(daily_return).fillna(0.0)
    curve["累计净值"] = (1.0 + curve["当日收益率"]).cumprod()
    curve["回撤"] = curve["累计净值"] / curve["累计净值"].cummax() - 1.0

    count = len(curve)
    total_return = curve["累计净值"].iloc[-1] - 1.0
    annual_return = (1.0 + total_return) ** (252.0 / count) - 1.0
    volatility = curve["当日收益率"].std(ddof=1)
    sharpe = np.nan
    if pd.notna(volatility) and volatility > 0:
        sharpe = np.sqrt(252.0) * curve["当日收益率"].mean() / volatility

    metrics = pd.DataFrame({
        "指标": ["交易次数", "胜率", "累计收益率", "年化收益率", "最大回撤", "年化夏普比率"],
        "数值": [
            len(trades),
            trades["净收益率"].gt(0).mean(),
            total_return,
            annual_return,
            -curve["回撤"].min(),
            sharpe,
        ],
    })
    return curve, metrics


def main():
    args = parse_args()
    if args.fee_rate < 0:
        raise SystemExit("手续费率不能为负数")

    candidates, daily = load_candidates(args.input_dir)
    candidates = add_entry_prices(candidates, args.data_dir)
    trades = make_trades(candidates, args.fee_rate)
    curve, metrics = calculate_performance(trades, daily)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    curve.to_csv(output_dir / "daily_returns.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(output_dir / "metrics.csv", index=False, encoding="utf-8-sig")

    print(f"\n交易明细: {output_dir / 'trades.csv'}")
    print(f"每日净值: {output_dir / 'daily_returns.csv'}")
    print(f"绩效指标: {output_dir / 'metrics.csv'}")
    if not metrics.empty:
        print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
