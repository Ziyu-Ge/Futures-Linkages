from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DAILY_BARS_FILE = ROOT / "results" / "processed" / "daily_bars.csv"
OUTPUT_DIR = ROOT / "results" / "simple_rolling_leader"

# 策略只保留四个固定参数，不做参数优化。
BREAKOUT_WINDOW = 20
CONFIRM_DAYS = 3
CORRELATION_WINDOW = 20
CORRELATION_THRESHOLD = 0.6

GROUPS = {
    "贵金属": "AU AG",
    "有色基本金属": "CU AL ZN PB NI SN AO",
    "新能源材料": "SI LC PS",
    "黑色钢矿": "I RB HC SS",
    "煤焦": "J JM",
    "铁合金": "SF SM",
    "能源油品": "SC FU LU BU PG",
    "橡胶": "RU NR BR",
    "聚酯产业链": "PX TA EG PF PR",
    "烯烃塑料": "L PP V EB PL",
    "煤化工建材": "MA SA FG UR",
    "谷物淀粉": "C CS",
    "油脂油料": "A B M RM PK",
    "软商品纺织": "CF CY SR",
    "果品": "AP CJ",
    "畜禽": "JD LH",
    "金融期货": "IF IM TL",
}

SYMBOL_TO_SECTOR = {
    symbol: sector
    for sector, symbols in GROUPS.items()
    for symbol in symbols.split()
}
