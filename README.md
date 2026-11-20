# 居民反馈覆盖与服务体验分析

把服务邀请、送达、回应、评价更正与案件办理事实结合起来的分析应用。所有对象均为
合成匿名标识，仅使用 Python 3.11 标准库。

## 口径承诺（与业务要求对应）

1. **分析单位是案件（事项），不是居民。** 同一居民对不同事项的体验分别计票，
   不跨事项合并成一票；`respondent` 仅用于识别同一事项内的重复与更正反馈。
2. **三层分母严格区分。** 符合邀请条件（eligible）→ 实际送达（delivered）→
   作出评价（responded）逐级成漏斗，并单列“未纳入邀请”。送达率、回收率、
   覆盖率分别用不同分母，不混用。
3. **未回应 = 未知，不是零分。** 已送达但未评价的案件进入“未知”桶，不进入
   平均分与评价分布；平均分只对当前有效评价计算。
4. **评价更正链可追溯。** `supersedes` 链上只有链头部是当前有效评价；检测到
   循环时整链作废并告警；同一案件存在多条独立链时只计一票，取最晚收到者并告警。
5. **履约事实独立。** 办结率、完结占比、结果分布只来自 `cases`，评价永远不
   替代办结；未办结案件（`closed_at` 为空）不进任何时期抽样框架。
6. **推断守卫优先于排名。** 抽样框架未登记、框架不覆盖整组、混合不同框架、
   样本不足或回收率不达标时，只给描述性统计并列明限制原因，**不生成全体
   满意度排名**。
7. **样本构成变化显式提示。** 相邻时期抽样框架不同（框架漂移）或邀请渠道集合
   变化（渠道变化）时单独标注，提醒平均分与覆盖率不可直接比较。

## 目录结构

```
community_feedback/
  models.py     领域模型与数据容器（空字符串统一转 None）
  loading.py    四表加载、结构校验（error 阻断 / warning 保留）
  feedback.py   更正链解析、异常评价隔离、案件级链路视图
  periods.py    时期归属（左闭右开，未办结归“未归期”）
  metrics.py    漏斗、评价分布、独立履约、渠道构成聚合
  guards.py     抽样框架登记、推断守卫、受限排名
  analysis.py   编排：加载→归并→聚合→守卫→排名→漂移检测
  reporting.py  text / json / 自包含 HTML 渲染（含转义与显示宽度对齐）
  cli.py        命令行入口
tests/          31 个单元测试（含端到端口径场景）
fixtures/       合成业务资料，字段说明见 DATA.md
```

## 用法

```bash
# 结构校验（阻断性错误返回非零码并逐条列出）
python3 -m community_feedback validate -f fixtures

# 文本报告（默认）
python3 -m community_feedback report -f fixtures

# JSON（机器可读，含完整漏斗、评价分布、守卫结论、框架登记表）
python3 -m community_feedback report -f fixtures --format json -o report.json

# 自包含 HTML（无外部依赖，可直接分发）
python3 -m community_feedback report -f fixtures --format html -o report.html

# 案件级邀请—送达—回应—履约链路
python3 -m community_feedback cases -f fixtures

# 调整推断门槛（默认：最少 5 票、最低回收率 50%）
python3 -m community_feedback report -f fixtures --min-responses 3 --min-response-rate 0.6
```

安装后也可使用 `community-feedback` 脚本入口（见 pyproject.toml）。

## 指标定义

| 指标 | 分子 / 分母 |
| --- | --- |
| 送达率 | 实际送达 / 符合邀请条件 |
| 回收率（eligible 口径） | 已评价 / 符合邀请条件（推断守卫使用此口径） |
| 回收率（delivered 口径） | 已评价 / 实际送达 |
| 覆盖率 | 已评价 / 全部案件 |
| 未回应·未知 | 实际送达 − 已评价（不计零分、不进平均分） |
| 已办结率 | 有 `closed_at` 的案件 / 全部案件 |
| 完结占比 | outcome=completed / 已办结案件 |

评价分布按 1–5 分列，并汇总不满（≤2）、中性（3）、满意（≥4）。被更正的历史
评价只在数据质量提示中留存，不进分布。

## 推断守卫与框架登记

`guards.FRAME_REGISTRY` 登记每种抽样框架的推断目标与覆盖规则。新增邀请机制时，
应先在登记表注册其框架标识、目标总体与成员判定，否则该框架下的所有组都会被
判定为“不支持总体推断”。

一个组必须同时满足以下条件才允许进入满意度排名：

- 抽样框架已登记，且组内每个案件都属于该框架的目标总体；
- 组内没有混合不同抽样框架，也没有无法归期的案件；
- 有效评价票数 ≥ `--min-responses`；
- 回收率（eligible 口径）≥ `--min-response-rate`。

未通过的组仍展示全部描述性统计，并在报告第五部分逐条列出限制原因。

## 数据质量分级

- **error**：缺文件、坏 JSON、字段缺失、枚举/分值非法、引用悬空、id 重复等，
  阻断分析并一次性列出全部错误；
- **warning**：不符合条件却标记送达、评价挂在未送达/不合格邀请下、更正链循环、
  多链并存等，记录保留但相关评价不进漏斗；
- **info**：已被更正的历史评价留存说明。

## 测试

```bash
python3 -m unittest discover -s tests -v
# 隔离模式（不把当前目录隐式加入路径，需显式指定顶级目录）：
python3 -I -m unittest discover -t . -s tests -v
```
