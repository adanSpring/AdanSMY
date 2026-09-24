# 云端定时任务配置记录（Cli-业务组技术对接表填报异常通报）

> 导出时间：2026-09-24；导出来源：WorkBuddy 云端定时任务（云上模式，云端沙箱执行，不依赖本机开机）

## 基本信息

- **名称**：Cli-业务组技术对接表填报异常通报
- **任务 ID**：`cloud:9872735`
- **状态**：ACTIVE
- **调度**：recurring，每天 17:00（云之家群每天必收到一条消息：有异常走模板 A，无异常走模板 B 小红花通报）
- **工作目录（cwds）**：云端沙箱（无本机目录）
- **Skill 来源**：本仓库（`main` 分支），任务启动时拉取 `SKILL.md`、`README.md`、`scripts/check_missing_fields.py`

## 执行环境

- **Skill 拉取兜底**：沙箱内 GitHub 域名 TLS 握手失败（DNS 被拦）时，改走 `https://api.github.com/repos/adanSpring/AdanSMY/contents/<path>?ref=main`（contents API，已验证可用），base64 解码后落盘
- **金山文档授权**：运行前校验 `kdocs-cli auth status`；`authenticated: false` 时输出告警并终止本次任务，不重试、不编造结果
- **推送凭据**：云之家群机器人 Webhook 通过环境变量 `YZJ_WEBHOOK` 注入。**token 不入库**（本文已脱敏），与 README「免责与安全」一节声明一致

## 自动化 prompt（原文收录，凭据已脱敏）

```text
执行「业务组技术对接表填写异常巡检」任务。本任务每天只推送一条消息。

## 一、获取 Skill（按顺序尝试）
1. 从 GitHub 仓库拉取：https://github.com/adanSpring/AdanSMY
   若沙箱内 GitHub 域名 TLS 握手失败（DNS 被拦），改用直连 IP + contents API：
   # 用 python 通过 contents API 拉取（走 api.github.com，已验证可用）：
   # GET https://api.github.com/repos/adanSpring/AdanSMY/contents/<path>?ref=main
   # 以 base64 解码 content 字段写入本地
   需要拉取的文件：SKILL.md、README.md、scripts/check_missing_fields.py
2. 若拉取失败，任务 prompt 已内嵌完整校验规则与模板，直接用内嵌逻辑执行，不必强依赖仓库。

## 二、前置检查
校验金山文档授权：`kdocs-cli auth status`。
若 `authenticated: false`，输出告警「金山文档授权已失效，请重新执行 kdocs-cli auth login」并终止本次任务，不要重试、不要编造结果。

## 三、执行巡检
export PATH="$PATH:/root/.local/bin"
YZJ_WEBHOOK="https://www.yunzhijia.com/gateway/robot/webhook/send?yzjtype=0&yzjtoken=<已脱敏，任务环境变量注入>" \
  python3 scripts/check_missing_fields.py
- 表格链接：https://www.kdocs.cn/l/cchYxqp30FkG
- 工作表：项目对接清单（sheetId=3，file_id=2yRGboxQH9MLz2kbTHNErx8PtTCNR8GcJ）
- 脚本默认启用快速通道（约 0.7~1.3s），失败会自动回退完整链路
- **脚本内置当日去重锁 + flock 跨进程互斥**：推送前先落盘当日锁再发消息；当天再次运行会打印「⏭️ 今日已推送过，跳过本次推送」并直接退出。这是预期行为，**不要加 --force 绕过**，也不要重复调用推送。

## 四、退出码处理（重要）
脚本退出码有明确含义，请按以下方式处理，不要一律当成成功：
| 退出码 | 含义 | 你要做的事 |
|---|---|---|
| 0 | 正常（含已推送、今日已跳过） | 记录摘要即可 |
| 2 | 未读取到任何数据 | 报告异常原因（链接/权限/网络），不推送 |
| 3 | 推送失败 | 报告「推送失败」，说明当日锁已保留不可重复推，需人工确认后 --force 补发 |
| 4 | 表头校验失败 | **立即报告表格列结构可能已变更**，附上脚本打印的列差异，等待人工处理，禁止绕过 |

## 五、校验规则（不得改动）
- 必填项（缺任一即异常）：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期
- 至少填一项（两项全空即异常）：业务背景与痛点、需求描述与业务价值
- 逐行检查；整行全空的行跳过，不计入需求条数

## 六、汇总规则（不得改动）
- 异常行有需求负责人 → 按负责人归并，`负责人：N行需求填写不完整；`，同一人只出现一次
- 异常行无需求负责人 → 按 Excel 真实行号单列 `第N行：1行需求填写不完整；`，不连续的行不合并
- 消息开头逐行艾特所有有异常的负责人
- 「共 N 条需求」必须实时统计

## 七、输出模板（逐字使用，不得增删版式）
**两种结果都要推送**：有异常走模板 A，无异常走模板 B。

模板 A（有异常）：
【业务组技术对接表填写异常提醒】
在线表格：https://www.kdocs.cn/l/cchYxqp30FkG
对接清单：共 {实时统计} 条需求
检查时间：YYYY-MM-DD HH:MM

@负责人A @负责人B
■ 异常结果
负责人A：N行需求填写不完整；
第N行：1行需求填写不完整；

■ 异常检查规则
必填项：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期；
至少填一项：业务背景与痛点、需求描述与业务价值；

注意：请尽快完善业务组需求文档的补充；

模板 B（无异常）：
【业务组技术对接表填写异常提醒】
在线表格：https://www.kdocs.cn/l/cchYxqp30FkG
对接清单：共 {实时统计} 条需求
检查时间：YYYY-MM-DD HH:MM

业务组表现优异，今日无异常，奖励一朵小红花🌹

> 模板 B 不含 @ 艾特行，也不含「异常结果」「异常检查规则」两段。

## 八、重要约束
- **每天最多推送一条消息**，不得重复推送
- 不要自行新增消息、补充说明或调整模板
- 执行后记录结果摘要（有效需求条数、异常行数、异常负责人名单、退出码、实际推送的是模板 A 还是 B），供追溯。
```

## 行为要点（与仓库其他文档的关系）

- **每天最多一条消息**：脚本级当日去重锁（`~/.cache/intake-check/send-state.json`）+ `flock` 跨进程互斥，双重保证；任务重试/补跑自动跳过
- **退出码语义**：`0` 正常 / `2` 未读到数据 / `3` 推送失败 / `4` 表头校验失败，处理约定见 prompt 第四节，机制详见 `SKILL.md`
- **模板 A/B** 逐字使用，不得增删版式；实现见 `scripts/check_missing_fields.py`，样例数据见 `samples/range_data.sample.json`
- 本文件是**任务配置快照**；执行与排错文档以 `SKILL.md` / `README.md` 为准
