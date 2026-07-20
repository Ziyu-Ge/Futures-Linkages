# 期货龙头与跟涨品种识别

本项目按 `prompt.md` 实现一个简单、规则驱动的 pandas 程序：从 `data/` 中读取分钟行情，逐小时合成“当前可见日 K”，再识别龙头期货和同板块跟涨期货。

## 运行

```bash
python3 -m pip install -r requirements.txt
python3 code/run_identification.py
```

可限制识别日期或品种，历史窗口仍会使用开始日期之前的数据：

```bash
python3 code/run_identification.py --start 2024-01-01 --end 2024-12-31
python3 code/run_identification.py --symbols CU,AL,ZN --start 2024-01-01
```

输出目录默认为 `results/identification/`：

- `leader_results.csv`：龙头识别结果。
- `follower_results.csv`：跟涨/跟跌识别结果。
- `daily_bars.csv`：用于复核的完整日 K 中间表。

## 规则口径

- 日收益率：`当前 close / 上一交易日 close - 1`。
- 持仓变化：`当前 open_interest / 上一交易日 open_interest - 1`。
- 历史阈值：只用今天以前的完整 20 个交易日日 K。
- 当前交易日：每个自然小时只使用该交易日开盘到该小时最后一条分钟数据。
- 龙头选择：同一小时、同一板块、同一方向内，所有满足突破、涨跌幅、持仓三条规则的品种按首次突破时间排序，最早突破者作为该板块该方向龙头。
- 跟涨识别：同板块、当前方向一致，并且过去 20 个交易日日收益率相关系数不低于 `0.5`。

阈值和板块映射在 `code/config.py`，核心数据处理在 `code/market_data.py`，识别规则在 `code/rules.py`。每个 Python 文件都控制在 300 行以内。
