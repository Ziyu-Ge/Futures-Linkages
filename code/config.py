"""规则识别项目的集中配置。

这里尽量只放常量，方便以后调整阈值、路径和板块映射。
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "results" / "identification"

# 滚动窗口和规则阈值，全部写成常量，避免规则藏在代码深处。
HISTORY_DAYS = 20
RETURN_MULTIPLIER = 4.0
OI_MULTIPLIER = 2.0
CORRELATION_THRESHOLD = 0.5
MIN_CORRELATION_DAYS = 20

# CSV 输出口径。
OUTPUT_ENCODING = "utf-8-sig"
FLOAT_FORMAT = "%.10f"

# 每个分钟 CSV 至少需要这些字段；索引列、成交额等字段不会参与识别。
MINUTE_COLUMNS = ["datetime", "open", "high", "low", "close", "open_interest"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "open_interest"]

# 简单板块映射。没有列到的品种仍可生成日线，但不会参与同板块跟涨识别。
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

GROUP = {symbol: group for group, symbols in GROUPS.items() for symbol in symbols.split()}
