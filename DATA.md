# 居民反馈覆盖与服务体验分析：资料说明

用于比较社区服务邀请、居民回应和事项办理事实。所有对象均为合成匿名标识。

每个 JSON 文件均为 UTF-8 编码。空字符串表示来源没有给出该事实，不等同于零、否或业务终态。标识仅在本项目资料内有意义。

## `cases.json`

字段：id, grid, service, closed_at, outcome。共 5 条合成记录。

## `invitations.json`

字段：id, case, channel, eligible, delivered, sent_at。共 5 条合成记录。

## `responses.json`

字段：id, invitation, respondent, score, received_at, supersedes。共 3 条合成记录。

## `periods.json`

字段：id, start, end, sampling。共 2 条合成记录。

## 关系与口径提示

invitations.case 对应 cases.id；responses.invitation 对应 invitations.id；responses.supersedes 表示修正前评价。居民匿名编号用于识别同一事项中的重复反馈，不代表不同事项间相同体验。
