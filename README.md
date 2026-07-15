# 期货龙头与跟随品种历史识别

本项目按 `prompt.md` 的规则，从旧到新回放分钟数据，在每个自然小时识别各板块的上涨/下跌龙头及其跟随品种。实现只使用 Python、pandas 和 numpy，不使用机器学习。

## 运行

```bash
python3 -m pip install -r requirements.txt
python3 code/run_identification.py
```

默认覆盖数据中所有具备前 20 个完整交易日的时点。也可以限制识别日期；限制范围之前的数据仍用于历史窗口，范围之后的第一条真实小时数据仍只用于辅助验证：

```bash
python3 code/run_identification.py --start 2024-01-01 --end 2024-12-31
```

规则阈值、默认日期和路径都集中在 `code/config.py`。板块映射直接复用 `code/process.py` 中的 `GROUPS`。

## 时间和计算口径

- 每个品种单独读取，只读取 `datetime/open/high/low/close/open_interest` 六列；不会把全部分钟数据一次装入内存。
- 夜盘按该品种下一个真实存在日盘的日期归属，自动跨过周末和节假日；找不到后续日盘的尾部夜盘不会错误回填。
- 自然小时用 `datetime.floor("h")` 划分，桶内最后一条有效分钟是该品种的小时状态。包括真实存在的 `15:00` 单分钟小时桶。
- 日内开盘和开盘持仓严格取交易日第一条记录，不跳过空值。历史指标先 `shift(1)` 再滚动 20 日，因此识别当日绝不会进入历史窗口。
- 滞后相关把龙头小时键加一小时后与跟随品种小时键做时间连接，计算 `leader(t-1小时) -> follower(t)`；休市空档不会按相邻行错误配对。
- 跟随品种确定以后，才从其时间序列读取下一个真实交易小时收益。该字段只做辅助验证，不参与筛选。

## 输出

运行后在 `results/identification/` 生成：

- `leader_follower_detail.csv`：每个龙头—跟随品种一行；当前配置只输出有跟随品种的龙头。
- `leader_follower_overview.csv`：每个有跟随品种的历史小时/板块/方向一行，适合直接筛选查看。
- `identification_summary.csv`：整体及板块×方向统计。
- `validation_report.txt`：上涨/下跌规则原始分钟回算、20 日窗口、相关方向、无未来数据、确定性复跑、表间对账和代码行数检查。

CSV 使用 UTF-8 BOM，Excel 可直接打开。浮点数统一保留 10 位小数以便复核和确定性比较。

## 文件结构

- `code/config.py`：统一阈值和路径。
- `code/market_data.py`：交易日映射、日线和小时状态生成。
- `code/identify.py`：龙头排序、跟随筛选和滞后相关。
- `code/report.py`：三份结果表和统计。
- `code/validate.py`：题目要求的七项验证。
- `code/run_identification.py`：命令行入口。
