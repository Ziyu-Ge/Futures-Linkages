import argparse
from pathlib import Path

from simple_leader_config import OUTPUT_DIR
from simple_leader_data import load_daily_bars
from simple_leader_strategy import run_strategy


def parse_args():
    parser = argparse.ArgumentParser(description="运行简单滚动龙头识别策略")
    parser.add_argument("--daily-bars", help="可选：指定 daily_bars.csv")
    parser.add_argument("--as-of", help="可选：只使用该日期及以前的数据")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="结果目录")
    return parser.parse_args()


def main():
    args = parse_args()
    bars = load_daily_bars(args.daily_bars)
    events, followers = run_strategy(bars, args.as_of)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_file = output_dir / "leader_events.csv"
    follower_file = output_dir / "followers.csv"
    events.to_csv(event_file, index=False, encoding="utf-8-sig")
    followers.to_csv(follower_file, index=False, encoding="utf-8-sig")

    print(f"日线记录: {len(bars)}")
    print(f"龙头事件: {len(events)} -> {event_file}")
    print(f"跟随关系: {len(followers)} -> {follower_file}")


if __name__ == "__main__":
    main()
