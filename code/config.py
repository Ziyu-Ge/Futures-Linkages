"""历史龙头/跟随识别的统一配置。"""

from pathlib import Path

from process import GROUP, GROUPS


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "results" / "identification"

# 默认 None 表示覆盖数据中所有具备 20 日历史的时点，可在命令行覆盖。
DEFAULT_START_DATE = None
DEFAULT_END_DATE = None

# 所有规则阈值集中在这里，便于直接修改。
HISTORY_DAYS = 20
RETURN_MULTIPLIER = 2.0
OI_MULTIPLIER = 1.5
MIN_CORRELATION_SAMPLES = 30
CORRELATION_THRESHOLD = 0.30

# True 时三份结果表只保留至少有一个合格跟随品种的龙头截面。
OUTPUT_ONLY_WITH_FOLLOWERS = True

# 任务只需要这些分钟字段；CSV 的索引列、date、成交量等不会读取。
MINUTE_COLUMNS = ["datetime", "open", "high", "low", "close", "open_interest"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "open_interest"]

DIRECTIONS = ("上涨", "下跌")
OUTPUT_ENCODING = "utf-8-sig"
FLOAT_FORMAT = "%.10f"
