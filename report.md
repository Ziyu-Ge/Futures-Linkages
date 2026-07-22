# 期货龙头与跟随品种识别逻辑报告

## 1. 这个项目在做什么

> 程序先把分钟行情合成“当前小时能看到的日 K”，然后看哪个品种最早突破自己过去 20 个交易日的高点或低点，同时涨跌幅和持仓变化都明显放大；这个品种就是该板块当前小时的龙头。找到龙头后，再在同板块里找当前同方向、并且过去 20 日收益率和龙头高度相关的品种，这些就是跟随品种。

## 2. 项目主线

主流程如下：

```text
分钟行情 CSV
    ↓
按交易日整理，夜盘归入下一个真实日盘交易日
    ↓
生成完整日 K
    ↓
生成每小时“当前可见日 K”
    ↓
计算收益率、持仓变化、前 20 日高低点、前 20 日平均波动
    ↓
逐小时、逐板块识别龙头
    ↓
围绕每个龙头识别跟随品种
    ↓
输出识别 CSV 和日 K 中间表
    ↓
基于向下跟随信号做空回测
    ↓
生成网络图和事件复盘页
```


## 3. 当前代码使用的阈值

| 参数 | 当前值 | 含义 |
| --- | ---: | --- |
| `HISTORY_DAYS` | 20 | 回看过去 20 个完整交易日。 |
| `RETURN_MULTIPLIER` | 4.0 | 当前涨跌幅绝对值要超过历史平均绝对涨跌幅的 4 倍。 |
| `OI_MULTIPLIER` | 2.0 | 当前持仓变化绝对值要超过历史平均绝对持仓变化的 2 倍。 |
| `CORRELATION_THRESHOLD` | 0.5 | 跟随品种和龙头的 20 日收益率相关系数至少为 0.5。 |
| `MIN_CORRELATION_DAYS` | 20 | 相关性计算至少需要 20 个有效样本。 |

## 4. 龙头识别条件

### 4.1 向上龙头条件

#### 向上龙头一句话总结

```text
向上龙头 =
    突破前 20 日高点
    + 当前上涨
    + 涨幅超过历史平均波动 4 倍
    + 当前增仓
    + 增仓幅度超过历史平均持仓变化 2 倍
```

#### 条件 1：有完整历史窗口

必须能拿到过去 20 个完整交易日的数据：

```text
prior_20_high_t 非空
avg_abs_return_20_t 非空
avg_abs_oi_change_20_t 非空
return_t 非空
oi_change_t 非空
```

#### 条件 2：价格向上突破前 20 日高点

```text
prior_20_high_t = max(high_{t-20}, high_{t-19}, ..., high_{t-1})
```

```text
high_{t,h} > prior_20_high_t
```

#### 条件 3：当前收益率为正

```text
return_t = close_t / close_{t-1} - 1
```

```text
return_{t,h} > 0
```

也就是当前是上涨的。

#### 条件 4：当前涨幅明显大于历史平均波动

```text
avg_abs_return_20_t =
mean(|return_{t-20}|, |return_{t-19}|, ..., |return_{t-1}|)
```

```text
|return_{t,h}| > 4.0 * avg_abs_return_20_t
```

解释：

如果过去 20 天这个品种平均每天绝对涨跌幅是 1%，那么当前涨幅要大于：

```text
4.0 * 1% = 4%
```

这样才算“涨得足够异常”。

#### 条件 5：当前持仓增加

```text
oi_change_t = open_interest_t / open_interest_{t-1} - 1
```

```text
oi_change_{t,h} > 0
```

也就是不只是价格涨，持仓也在增加。

#### 条件 6：当前增仓幅度明显大于历史平均持仓变化

```text
avg_abs_oi_change_20_t =
mean(|oi_change_{t-20}|, |oi_change_{t-19}|, ..., |oi_change_{t-1}|)
```

```text
|oi_change_{t,h}| > 2.0 * avg_abs_oi_change_20_t
```

解释：

如果过去 20 天这个品种平均持仓变化幅度是 2%，那么当前持仓变化要大于：

```text
2.0 * 2% = 4%
```

这样才算“增仓足够明显”。


### 4.2 向下龙头条件

某个品种要成为向下龙头，也必须同时满足 6 个条件。

```text
向下龙头 =
    跌破前 20 日低点
    + 当前下跌
    + 跌幅超过历史平均波动 4 倍
    + 当前减仓
    + 减仓幅度超过历史平均持仓变化 2 倍
```

## 5. 多个龙头候选怎么选

同一个板块、同一个小时、同一个方向里，可能多个品种都满足龙头条件。

这时程序按下面顺序排序：

1. `first_break_time` 越早越优先。
2. 如果突破时间一样，`|return|` 越大越优先。
3. 如果涨跌幅也一样，`|oi_change|` 越大越优先。
4. 如果还一样，品种代码按字母顺序排序。

公式化表达：

```text
leader =
arg sort by (
    first_break_time ascending,
    |return| descending,
    |oi_change| descending,
    symbol ascending
)
```

## 6. 跟随品种识别条件

### 条件 1：同板块

```text
group_j = group_L
```

### 条件 2：不能是龙头自己

```text
symbol_j != symbol_L
```

### 条件 3：当前方向和龙头一致

如果龙头是向上：

```text
return_{j,t,h} > 0
```

如果龙头是向下：

```text
return_{j,t,h} < 0
```

解释：

- 龙头上涨时，只找当前也上涨的品种。
- 龙头下跌时，只找当前也下跌的品种。

### 条件 4：过去 20 日收益率相关性足够高

程序计算龙头和候选品种过去 20 个交易日的日收益率相关系数。

设：

```text
R_L = 龙头过去 20 日收益率序列
R_j = 候选品种过去 20 日收益率序列
```

相关系数公式是标准 Pearson 相关系数：

```text
corr(L, j) =
cov(R_L, R_j) / (std(R_L) * std(R_j))
```

展开写就是：

```text
corr(L, j) =
Σ[(R_L,k - mean(R_L)) * (R_j,k - mean(R_j))]
/
sqrt(Σ(R_L,k - mean(R_L))^2 * Σ(R_j,k - mean(R_j))^2)
```

当前代码要求：

```text
corr(L, j) >= 0.5
```

### 跟随品种一句话总结

```text
跟随品种 =
    和龙头同板块
    + 当前方向和龙头一致
    + 过去 20 日收益率相关系数 >= 0.5
    + 有 20 个有效相关性样本
```


## 7. 输出结果怎么看

识别入口是：

```bash
python3 code/run_identification.py
```

可选参数：

| 参数 | 含义 |
| --- | --- |
| `--data-dir` | 分钟行情 CSV 目录，默认 `data/`。 |
| `--output-dir` | 识别结果输出目录，默认 `results/identification/`。 |
| `--start` | 只输出该交易日及之后的识别结果。 |
| `--end` | 只输出该交易日及之前的识别结果。 |
| `--symbols` | 只处理指定品种，逗号分隔，例如 `CU,AL,ZN`。 |

`--start` 和 `--end` 只限制最终识别输出范围，不会截断前 20 日历史窗口。

### 7.1 龙头结果表

输出文件：

```text
results/identification/leader_results.csv
```

重要字段：

| 字段 | 含义 |
| --- | --- |
| `识别时间` | 同一交易日、同一小时、同一板块内实际使用到的最后一条分钟数据时间。 |
| `交易日` | 所属交易日。 |
| `龙头品种` | 被识别出的龙头。 |
| `板块` | 龙头所属板块。 |
| `方向` | `向上` 或 `向下`。 |
| `当前涨跌幅` | 当前可见日 K 的 `close / prev_close - 1`。 |
| `当前增减仓幅度` | 当前可见日 K 的 `open_interest / prev_open_interest - 1`。 |
| `前20日最高价或最低价` | 向上时是前 20 日最高价，向下时是前 20 日最低价。 |
| `前20日平均涨跌幅绝对值` | `avg_abs_return_20_t`。 |
| `前20日平均增减仓幅度绝对值` | `avg_abs_oi_change_20_t`。 |
| `首次突破时间` | 当个交易日第一次突破高点或跌破低点的分钟时间。 |
| `识别小时` | 当前快照所属自然小时。 |
| `历史窗口开始` | 前 20 日窗口开始日期。 |
| `历史窗口结束` | 前 20 日窗口结束日期。 |
| `触发原因` | 中文解释，写明突破价、涨跌幅阈值、持仓阈值和首次突破时间。 |

### 7.2 跟随结果表

输出文件：

```text
results/identification/follower_results.csv
```

重要字段：

| 字段 | 含义 |
| --- | --- |
| `识别时间` | 跟随信号对应的识别时间。 |
| `交易日` | 所属交易日。 |
| `龙头品种` | 已识别出的龙头。 |
| `跟涨品种` | 被识别出的跟随品种。向下时实际含义是跟跌。 |
| `板块` | 龙头和跟随品种共同所属板块。 |
| `方向` | 跟随龙头的方向，`向上` 或 `向下`。 |
| `20日收益率相关系数` | 龙头和候选品种过去 20 日收益率相关性。 |
| `相关样本数` | 实际用于计算相关性的交易日数量。 |
| `龙头当前涨跌幅` | 龙头当前小时收益率。 |
| `跟涨品种当前涨跌幅` | 跟随品种当前小时收益率。 |
| `触发原因` | 中文解释。 |

### 7.3 日 K 中间表

输出文件：

```text
results/identification/daily_bars.csv
```

这张表用于复核识别过程，包含：

| 字段 | 含义 |
| --- | --- |
| `symbol` / `group` | 品种和板块。 |
| `trade_date` | 映射后的交易日。 |
| `open` / `high` / `low` / `close` | 完整交易日日 K。 |
| `open_interest` | 当日最后一条分钟数据的持仓量。 |
| `day_start_time` / `day_end_time` | 当日第一条和最后一条分钟数据时间。 |
| `prev_close` / `prev_open_interest` | 上一交易日收盘价和持仓量。 |
| `return` / `oi_change` | 完整日 K 口径的收益率和持仓变化。 |
| `prior_20_high` / `prior_20_low` | 今天以前 20 个完整交易日的高点和低点。 |
| `avg_abs_return_20` / `avg_abs_oi_change_20` | 今天以前 20 个完整交易日的平均绝对涨跌幅和平均绝对持仓变化。 |
| `history_start` / `history_end` | 历史窗口起止日期。 |

## 8. 做空回测逻辑

回测入口是：

```bash
python3 code/run_short_backtest.py
```

当前回测只使用“向下”跟随信号：

```text
做空标的 = follower_results.csv 中 方向 = 向下 的跟随品种
```

交易规则：

1. 同一交易日、同一跟随品种，只保留最早一次向下跟随信号。
2. 开空时间为信号出现后的下一根分钟 K 线。
3. 开空价格为该分钟 K 线的 `open`。
4. 平空时间为该交易日最后一根分钟 K 线。
5. 平空价格为完整日 K 的 `close`。
6. 收益率按做空计算：

```text
税前收益率 = 开空价 / 平空价 - 1
净收益率 = 税前收益率 - 2 * 单边费率
```

默认 `--fee-rate=0.0`，也就是不计手续费。

回测输出目录：

```text
results/short_backtest/
```

输出文件：

| 文件 | 含义 |
| --- | --- |
| `trades.csv` | 每笔交易明细，包括开空时间、开空价、平空时间、平空价、税前收益率和净收益率。 |
| `daily_returns.csv` | 按交易日等权后的当日收益率、累计净值和回撤。 |
| `metrics.csv` | 汇总绩效指标。 |

当前 `results/short_backtest/metrics.csv` 中的结果为：

| 指标 | 数值 |
| --- | ---: |
| 交易次数 | 57 |
| 胜率 | 73.68% |
| 累计收益率 | 7.09% |
| 年化收益率 | 0.98% |
| 最大回撤 | 0.28% |
| 年化夏普比率 | 0.81 |

## 9. 参数网格回测逻辑

网格入口是：

```bash
python3 code/run_short_grid.py
```

默认三组参数：

| 参数 | 网格范围 |
| --- | --- |
| `RETURN_MULTIPLIER` | 1.0 到 5.0，步长 0.5。 |
| `OI_MULTIPLIER` | 0.5 到 5.0，步长 0.5。 |
| `CORRELATION_THRESHOLD` | 0.5 到 0.9，步长 0.1。 |

默认同时计算两个手续费口径：

```text
--fee-rates 0,0.0001
```

网格实现没有对每组参数重复读取全部分钟数据，而是：

1. 先提前筛出所有可能成为“向下龙头”的小时快照。
2. 对每组收益率阈值和持仓阈值选出对应龙头。
3. 用最低相关性阈值先计算所有可能跟随品种。
4. 再按不同 `CORRELATION_THRESHOLD` 回填筛选结果。
5. 最后统一补开空价和平空价，计算各参数组合绩效。

输出目录：

```text
results/short_grid/
```

输出文件：

| 文件 | 含义 |
| --- | --- |
| `grid_metrics.csv` | 每组参数和手续费下的绩效指标。 |
| `grid_ranked.csv` | 按手续费、夏普比率、交易次数排序后的结果。 |
| `parameter_summary.csv` | 按单个参数聚合的中位数表现和正收益比例。 |
| `grid_trades.csv` | 各参数组合对应的交易明细。 |

当前仓库的 `results/` 目录下尚未保存 `short_grid` 输出，因此报告只记录代码逻辑，不引用网格实证结果。

## 10. 可视化输出

可视化入口是：

```bash
python3 code/visualize.py
```

默认读取：

```text
results/identification/
```

默认输出：

```text
results/figures/
```

### 10.1 龙头-跟随网络图

![龙头-跟随网络图](results/figures/leader_follower_network.png)

网络图按 `龙头品种-跟涨品种-板块` 聚合，统计出现次数和平均相关系数，默认最多展示前 60 条关系。节点按板块布局，边的粗细和出现次数相关。

### 10.2 单次事件复盘页

[打开可切换事件复盘页面](https://htmlpreview.github.io/?https://github.com/Ziyu-Ge/Futures-Linkages/blob/main/results/figures/event_review.html)

事件复盘页只展示同时存在龙头和跟随品种的事件。每个事件展示：

| 内容 | 含义 |
| --- | --- |
| 元信息 | 识别时间、交易日、龙头、板块、方向、龙头涨跌幅、跟随数量和突破阈值。 |
| 价格走势 | 事件日前后各 10 个交易日的收盘价归一化走势。 |
| 跟随列表 | 跟随品种、20 日相关系数和事件当前涨跌幅。 |

## 11. 总结

这个项目的识别逻辑可以压缩成两组公式。

龙头：

```text
向上龙头条件：
high_{t,h} > prior_20_high_t
return_{t,h} > 0
|return_{t,h}| > 4.0 * avg_abs_return_20_t
oi_change_{t,h} > 0
|oi_change_{t,h}| > 2.0 * avg_abs_oi_change_20_t

向下龙头条件：
low_{t,h} < prior_20_low_t
return_{t,h} < 0
|return_{t,h}| > 4.0 * avg_abs_return_20_t
oi_change_{t,h} < 0
|oi_change_{t,h}| > 2.0 * avg_abs_oi_change_20_t
```

跟随：

```text
group_j = group_L
direction_j = direction_L
corr(return_L_last_20_days, return_j_last_20_days) >= 0.5
sample_count >= 20
```

做空回测：

```text
entry = signal_time 之后下一根分钟 K 线 open
exit = 当个交易日最后一根分钟 K 线 close
short_return = entry / exit - 1 - 2 * fee_rate
```

最终逻辑是：

> 先在每个板块里找“最早、最强、带持仓变化”的突破品种作为龙头，再找“同板块、同方向、历史走势相似”的品种作为跟随；实证部分目前重点检验“向下龙头出现后做空跟跌品种”的日内效果。
