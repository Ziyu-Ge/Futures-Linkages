"""对全量识别结果执行题目要求的可复核检查。"""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    CORRELATION_THRESHOLD, GROUP, HISTORY_DAYS, OI_MULTIPLIER, RETURN_MULTIPLIER,
)
from identify import identify_history, lagged_correlation
from market_data import assign_trade_date, read_minutes
from report import (
    DETAIL_NAMES,
    KEY_COLUMNS,
    OVERVIEW_NAMES,
    SUMMARY_NAMES,
    csv_bytes,
    make_summary,
    records_to_tables,
)


def assert_close(actual, expected, label):
    if not np.isclose(actual, expected, rtol=1e-10, atol=1e-12):
        raise AssertionError(f"{label} 不一致: {actual} != {expected}")


def audit_one_direction(row, daily_all, data_dir):
    """从原始分钟重新回算一例，且证明突破分钟之前没有突破。"""
    symbol = row["leader_symbol"]
    trade_date = row["trade_date"]
    history = daily_all.loc[
        daily_all["symbol"].eq(symbol) & daily_all["trade_date"].lt(trade_date)
    ].sort_values("trade_date", kind="mergesort").tail(HISTORY_DAYS)
    if len(history) != HISTORY_DAYS or history["trade_date"].max() >= trade_date:
        raise AssertionError("手工抽查的 20 日窗口不完整或包含当日")
    if history["trade_date"].iloc[0] != row["history_window_start"]:
        raise AssertionError("20 日窗口开始日期不一致")
    if history["trade_date"].iloc[-1] != row["history_window_end"]:
        raise AssertionError("20 日窗口结束日期不一致")

    minutes = read_minutes(Path(data_dir) / f"{symbol}.csv")
    minutes["trade_date"] = assign_trade_date(minutes)
    current = minutes.loc[
        minutes["trade_date"].eq(trade_date)
        & minutes["datetime"].le(row["leader_snapshot_time"])
    ].sort_values("datetime", kind="mergesort")
    if current.empty or current["datetime"].max() > row["identification_time"]:
        raise AssertionError("当下日 K 使用了识别时间之后的数据")

    day_return = current["close"].iloc[-1] / current["open"].iloc[0] - 1.0
    oi_change = current["open_interest"].iloc[-1] / current["open_interest"].iloc[0] - 1.0
    return_threshold = RETURN_MULTIPLIER * history["daily_return"].abs().mean()
    oi_threshold = OI_MULTIPLIER * history["daily_oi_change"].abs().mean()
    assert_close(day_return, row["leader_current_return"], "当日涨跌幅")
    assert_close(oi_change, row["leader_current_oi_change"], "当日持仓变化幅")
    assert_close(return_threshold, row["return_threshold"], "涨跌幅阈值")
    assert_close(oi_threshold, row["oi_threshold"], "持仓变化阈值")

    direction = row["direction"]
    if direction == "上涨":
        breakout = history["day_high"].max()
        crossed = current.loc[current["high"].gt(breakout)]
        extreme = current["high"].max()
        rules_ok = day_return > 0 and abs(day_return) > return_threshold and extreme > breakout
    else:
        breakout = history["day_low"].min()
        crossed = current.loc[current["low"].lt(breakout)]
        extreme = current["low"].min()
        rules_ok = day_return < 0 and abs(day_return) > return_threshold and extreme < breakout
    if crossed.empty or not rules_ok or abs(oi_change) <= oi_threshold:
        raise AssertionError(f"{direction}龙头未满足三条规则")
    first = crossed.iloc[0]
    if first["datetime"] != row["first_break_time"]:
        raise AssertionError("首次突破分钟不一致")
    before = current.loc[current["datetime"].lt(first["datetime"])]
    if direction == "上涨" and before["high"].gt(breakout).any():
        raise AssertionError("上涨首次突破前已有更早突破")
    if direction == "下跌" and before["low"].lt(breakout).any():
        raise AssertionError("下跌首次突破前已有更早突破")
    assert_close(breakout, row["breakout_threshold"], "前20日突破价")
    assert_close(extreme, row["current_extreme"], "当下日K极值")
    return (
        f"{direction}抽查：{trade_date:%Y-%m-%d} {symbol}，首次突破"
        f" {first['datetime']:%Y-%m-%d %H:%M}；|涨跌幅|={abs(day_return):.6%}"
        f" > {return_threshold:.6%}，|持仓变化|={abs(oi_change):.6%}"
        f" > {oi_threshold:.6%}，突破价={breakout:.6f}，通过。"
    )


def validate_rules(detail, daily_all, data_dir):
    samples = detail.drop_duplicates(KEY_COLUMNS, keep="first")
    lines = []
    for direction in ("上涨", "下跌"):
        candidates = samples.loc[samples["direction"].eq(direction)]
        if candidates.empty:
            lines.append(f"{direction}抽查：当前识别范围没有该方向龙头，跳过。")
        else:
            lines.append(audit_one_direction(candidates.iloc[0], daily_all, data_dir))
    return lines


def validate_lag(detail, hourly_by_symbol):
    if detail.empty:
        return "滞后方向抽查：当前识别范围没有龙头，跳过。"
    candidates = detail.loc[detail["follower_symbol"].notna()]
    output_follower = not candidates.empty
    if output_follower:
        row = candidates.iloc[0]
        follower_symbol = row["follower_symbol"]
    else:
        # 即使阈值下没有合格跟随，也选择同板块品种验证时间连接方向。
        choice = None
        for _, possible in detail.drop_duplicates(KEY_COLUMNS).iterrows():
            peers = sorted(
                symbol for symbol in hourly_by_symbol
                if GROUP.get(symbol) == possible["group"]
                and symbol != possible["leader_symbol"]
            )
            for peer in peers:
                test_corr, test_count = lagged_correlation(
                    hourly_by_symbol[possible["leader_symbol"]],
                    hourly_by_symbol[peer],
                    possible["history_window_start"],
                    possible["history_window_end"],
                )
                if test_count >= 30:
                    choice = possible, peer, test_corr, test_count
                    break
            if choice is not None:
                break
        if choice is None:
            return "滞后方向抽查：当前识别范围没有足够共同样本，跳过。"
        row, follower_symbol, correlation, count = choice
    if output_follower:
        correlation, count = lagged_correlation(
            hourly_by_symbol[row["leader_symbol"]],
            hourly_by_symbol[follower_symbol],
            row["history_window_start"],
            row["history_window_end"],
        )
    if output_follower:
        assert_close(correlation, row["lagged_correlation"], "滞后一小时相关")
        if count != row["correlation_samples"]:
            raise AssertionError("滞后相关样本数不一致")
    if row["history_window_end"] >= row["trade_date"]:
        raise AssertionError("相关窗口包含识别当日")
    correlation_text = "NaN" if pd.isna(correlation) else f"{correlation:.10f}"
    return (
        f"滞后方向抽查：{row['leader_symbol']}(t-1小时) -> "
        f"{follower_symbol}(t)，按 leader.hour_key+1h 对齐，"
        f"n={count}，corr={correlation_text}，通过。"
    )


def validate_no_future(detail):
    if detail.empty:
        return "无未来数据抽查：当前识别范围没有龙头，跳过。"
    if not (
        detail["first_break_time"].le(detail["leader_snapshot_time"]).all()
        and detail["leader_snapshot_time"].le(detail["identification_time"]).all()
        and detail["history_window_end"].lt(detail["trade_date"]).all()
    ):
        raise AssertionError("识别字段中发现未来时间")
    follower = detail.loc[detail["follower_symbol"].notna()]
    if not follower["follower_snapshot_time"].le(follower["identification_time"]).all():
        raise AssertionError("跟随筛选使用了识别时间后的状态")
    future = follower.loc[follower["next_hour_time"].notna()]
    if not future["next_hour_time"].gt(future["identification_time"]).all():
        raise AssertionError("辅助验证不是下一真实小时")
    row = detail.iloc[0]
    return (
        f"无未来数据抽查：{row['identification_time']:%Y-%m-%d %H:%M} 截面，"
        "日内状态/首次突破均不晚于识别时间，20日窗口早于当日；"
        "下一小时字段仅在跟随筛选冻结后补充，通过。"
    )


def validate_reconciliation(detail, overview):
    detail_keys = pd.MultiIndex.from_frame(detail[KEY_COLUMNS].drop_duplicates())
    overview_keys = pd.MultiIndex.from_frame(overview[KEY_COLUMNS])
    if overview_keys.has_duplicates or set(detail_keys) != set(overview_keys):
        raise AssertionError("历史明细与一览的识别键无法完全对上")
    indexed = overview.set_index(KEY_COLUMNS)
    for key, part in detail.groupby(KEY_COLUMNS, sort=False, dropna=False):
        followers = part.loc[part["follower_symbol"].notna()]
        symbols = ",".join(followers["follower_symbol"].astype(str))
        correlations = ",".join(f"{value:.10f}" for value in followers["lagged_correlation"])
        target = indexed.loc[key]
        if symbols != target["follower_symbols"] or correlations != target["lagged_correlations"]:
            raise AssertionError("明细中的跟随列表与一览不一致")
    return f"明细/一览对账：{len(overview)} 个唯一识别键全部一致，通过。"


def validate_line_counts(code_dir):
    counts = {}
    for file in sorted(Path(code_dir).glob("*.py")):
        counts[file.name] = len(file.read_text(encoding="utf-8").splitlines())
    too_long = {name: count for name, count in counts.items() if count > 300}
    if too_long:
        raise AssertionError(f"代码文件超过300行: {too_long}")
    return f"代码行数：{len(counts)} 个 Python 文件均不超过 300 行（最大 {max(counts.values())} 行），通过。"


def validate_correlation_diagnostics(diagnostics):
    count = diagnostics["finite_windows"]
    pair = diagnostics["max_pair"]
    if pair is None:
        return "相关阈值复核：当前识别范围没有样本数不少于30的候选窗口。"
    leader, follower, start, end, samples = pair
    maximum = diagnostics["max_correlation"]
    result = "低于" if maximum < CORRELATION_THRESHOLD else "达到或超过"
    return (
        f"相关阈值复核：实际筛选过 {count} 个有限相关窗口，最高为 "
        f"{leader}->{follower}，{start:%Y-%m-%d}~{end:%Y-%m-%d}，"
        f"n={samples}，corr={maximum:.10f}，{result}阈值 "
        f"{CORRELATION_THRESHOLD:.2f}。"
    )


def validate_repeat(records, snapshots, hourly_by_symbol, start_date, end_date, payloads):
    repeated = identify_history(snapshots, hourly_by_symbol, start_date, end_date)
    detail2, overview2 = records_to_tables(repeated)
    summary2 = make_summary(detail2, overview2)
    payloads2 = {
        "detail": csv_bytes(detail2, DETAIL_NAMES),
        "overview": csv_bytes(overview2, OVERVIEW_NAMES),
        "summary": csv_bytes(summary2, SUMMARY_NAMES),
    }
    if payloads != payloads2:
        raise AssertionError("相同历史范围重复识别的 CSV 不完全一致")
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()}
    return "确定性复跑：三份 CSV 字节完全一致，SHA-256=" + ", ".join(
        f"{key}:{value[:12]}" for key, value in hashes.items()
    ) + "，通过。"


def run_validations(
    records, detail, overview, daily_all, snapshots, hourly_by_symbol,
    data_dir, code_dir, output_dir, start_date, end_date, payloads, diagnostics,
):
    lines = ["历史龙头与跟随品种识别验证报告", ""]
    lines.extend(validate_rules(detail, daily_all, data_dir))
    lines.append(validate_lag(detail, hourly_by_symbol))
    lines.append(validate_correlation_diagnostics(diagnostics))
    lines.append(validate_no_future(detail))
    lines.append(validate_reconciliation(detail, overview))
    lines.append(validate_repeat(
        records, snapshots, hourly_by_symbol, start_date, end_date, payloads
    ))
    lines.append(validate_line_counts(code_dir))
    path = Path(output_dir) / "validation_report.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
