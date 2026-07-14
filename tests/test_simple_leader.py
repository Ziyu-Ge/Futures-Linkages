import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from simple_leader_strategy import (  # noqa: E402
    calculate_rolling_corr,
    find_breakouts,
    run_strategy,
)


def make_market():
    """A先启动且最强，B高相关后启动，C低相关。"""
    dates = pd.bdate_range("2025-01-01", periods=25)
    pre_a = [100 if i % 2 == 0 else 101 for i in range(21)]
    pre_c = [100 if i % 2 == 0 else 99 for i in range(21)]
    prices = {
        "A": pre_a + [110, 111, 112, 113],
        "B": pre_a + [100.5, 102, 103, 104],
        "C": pre_c + [100, 101, 101.5, 102],
    }
    rows = []
    for symbol, values in prices.items():
        for date, close in zip(dates, values):
            rows.append({
                "trade_date": date,
                "sector": "测试板块",
                "symbol": symbol,
                "close": close,
            })
    return pd.DataFrame(rows), dates


def event_started_on(events, date, direction="上涨"):
    rows = events[
        (events["start_date"] == date) & (events["direction"] == direction)
    ]
    assert len(rows) == 1
    return rows.iloc[0]


def test_breakout_only_uses_previous_20_days():
    bars, dates = make_market()
    result = find_breakouts(bars)
    row = result[(result["symbol"] == "A") & (result["trade_date"] == dates[21])].iloc[0]
    assert row["past_high"] == 101
    assert bool(row["up_breakout"])

    # 修改启动日之后的价格，不应改变启动日的突破判断。
    changed = bars.copy()
    changed.loc[changed["trade_date"] > dates[21], "close"] = 9999
    changed_result = find_breakouts(changed)
    changed_row = changed_result[
        (changed_result["symbol"] == "A")
        & (changed_result["trade_date"] == dates[21])
    ].iloc[0]
    assert changed_row["past_high"] == row["past_high"]
    assert changed_row["up_breakout"] == row["up_breakout"]


def test_leader_waits_until_third_day():
    bars, dates = make_market()
    events, _ = run_strategy(bars, as_of=dates[23])
    row = event_started_on(events, dates[21])
    assert row["status"] == "确认中"
    assert pd.isna(row["confirm_date"])

    events, followers = run_strategy(bars, as_of=dates[24])
    row = event_started_on(events, dates[21])
    assert row["status"] == "确认龙头"
    assert row["confirm_date"] == dates[24]
    assert row["leader"] == "A"
    assert row["strongest_symbol"] == "A"
    assert set(followers["follower"]) == {"B"}
    assert followers.iloc[0]["follower_type"] == "滞后跟随"


def test_correlation_uses_only_pre_start_returns():
    bars, dates = make_market()
    table = bars.pivot(index="trade_date", columns="symbol", values="close")
    before = calculate_rolling_corr(table, "A", "B", dates[21])

    # 启动后的价格变化不能反过来改变启动前相关系数。
    changed = table.copy()
    changed.loc[dates[21]:, "B"] = [80, 70, 60, 50]
    after = calculate_rolling_corr(changed, "A", "B", dates[21])
    assert before == after == 1.0


def test_earliest_but_not_strongest_is_not_leader():
    bars, dates = make_market()
    bars.loc[
        (bars["symbol"] == "B") & (bars["trade_date"] == dates[24]), "close"
    ] = 120
    events, _ = run_strategy(bars)
    row = event_started_on(events, dates[21])
    assert row["status"] == "先行品种"
    assert row["leader"] == "A"
    assert row["strongest_symbol"] == "B"
    assert row["strongest_status"] == "强势品种"


def test_same_day_start_has_no_unique_leader():
    bars, dates = make_market()
    bars.loc[
        (bars["symbol"] == "B") & (bars["trade_date"] == dates[21]), "close"
    ] = 105
    events, followers = run_strategy(bars)
    row = event_started_on(events, dates[21])
    assert row["status"] == "同步启动"
    assert row["earliest_symbols"] == "A|B"
    assert row["leader"] == ""
    assert followers.empty


def test_no_follower_is_independent_move():
    bars, dates = make_market()
    bars = bars[bars["symbol"] == "A"]
    events, followers = run_strategy(bars)
    row = event_started_on(events, dates[21])
    assert row["status"] == "独立行情"
    assert row["follower_count"] == 0
    assert followers.empty


def test_low_correlation_and_short_history_are_excluded():
    bars, dates = make_market()
    # D只有10个启动前收益率，即使同向上涨也不能成为跟随品种。
    d_dates = dates[10:]
    d_prices = [100 if i % 2 == 0 else 101 for i in range(11)] + [100.5, 102, 103, 104]
    d_rows = pd.DataFrame({
        "trade_date": d_dates,
        "sector": "测试板块",
        "symbol": "D",
        "close": d_prices,
    })
    bars = pd.concat([bars, d_rows], ignore_index=True)
    events, followers = run_strategy(bars)
    row = event_started_on(events, dates[21])
    assert row["status"] == "确认龙头"
    assert "C" not in set(followers["follower"])  # C与A负相关
    assert "D" not in set(followers["follower"])  # D历史不足20日


def test_new_code_files_are_under_300_lines():
    files = list((ROOT / "code").glob("simple_leader*.py"))
    files.append(ROOT / "tests" / "test_simple_leader.py")
    for file in files:
        assert len(file.read_text(encoding="utf-8").splitlines()) < 300, file
