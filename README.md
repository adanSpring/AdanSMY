# 业务组技术对接表填写异常巡检

对金山文档在线表格「集团信息化 业务技术项目对接表」的 **`项目对接清单`** 工作表做逐行完整性巡检，
把填写不完整的行按需求负责人汇总，渲染成固定模板推送到**云之家群机器人**；全部填写完整时**静默不发**。

## 校验规则

| 规则 | 内容 |
|---|---|
| **必填项（7 项，缺任一即异常）** | 系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期 |
| **至少填一项（2 项全空即异常）** | 业务背景与痛点、需求描述与业务价值 |

## 汇总规则

- 异常行**有负责人** → 按负责人归并：`负责人：N行需求填写不完整；`（同一人只出现一次）
- 异常行**无负责人** → 按行号单列：`第N行：1行需求填写不完整；`（不连续行不合并）
- 消息开头**逐行艾特**所有有异常的负责人
- **无异常 → 不发送消息**

## 快速开始

```bash
# 1) 金山文档授权（首次或 Token 过期时）
kdocs-cli auth status
kdocs-cli auth login

# 2) 只校验不推送（推荐先跑）
python3 scripts/check_missing_fields.py --dry-run

# 3) 正式执行：拉表 → 校验 → 有异常则推送到群
YZJ_WEBHOOK="https://www.yunzhijia.com/gateway/robot/webhook/send?yzjtype=0&yzjtoken=xxx" \
  python3 scripts/check_missing_fields.py
```

## 依赖

- **kdocs-cli** —— 金山文档 CLI（读取在线表格）
  ```bash
  bash scripts/setup.sh          # 金山文档官方 Skill 内置的安装脚本
  # 或确认 PATH 包含 ~/.local/bin
  ```
- **Python 3.8+** —— 脚本仅用标准库（`json` / `urllib` / `subprocess`），无第三方依赖
- **云之家群机器人 Webhook** —— 通过 `--webhook` 或环境变量 `YZJ_WEBHOOK` 传入

## 参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--table-url` | 在线表格链接 | `https://www.kdocs.cn/l/cchYxqp30FkG` |
| `--webhook` | 云之家群机器人 Webhook | 环境变量 `YZJ_WEBHOOK` |
| `--file-id` | 直接指定 file_id，跳过链接解析 | 内置默认值 / 环境变量 `KDOCS_FILE_ID` |
| `--sheet-id` | 工作表 id | `3`（`项目对接清单`） |
| `--no-fast-path` | 禁用快速通道，强制走完整解析链路 | 关闭 |
| `--force` | 忽略当日去重锁，强制推送（人工重发用） | 关闭 |
| `--lock-file` | 去重锁文件路径 | `~/.cache/intake-check/send-state.json` |
| `--from-json` | 离线模式：从已保存的 range-data JSON 读取 | — |
| `--dry-run` | 只校验不推送 | 关闭 |
| `--save-json` | 保存本次拉取的数据，便于回放核对 | — |

## 每天只推送一次

脚本内置**当日去重锁**：推送成功后记录日期，当天再次运行会直接跳过推送。

| 场景 | 行为 |
|---|---|
| 每天 17:00 正常触发 | 推送 1 条 |
| 任务重试 / 补跑 / 手动触发 | **跳过推送**，群里无重复消息 |
| 跨天后再次运行 | 自动恢复推送 |
| 需要人工重发 | 加 `--force` |

```bash
# 人工强制重发
python3 scripts/check_missing_fields.py --force
```

## 性能

默认启用**快速通道**：直接使用内置 `file_id` 拉取数据，省掉「解析链接」与「查工作表」两次 API 往返。

| 路径 | 实测耗时 |
|---|---|
| 快速通道（默认） | **约 0.7s** |
| 完整链路（`--no-fast-path`） | 约 3.2s |

快速通道失败（`file_id` 失效、表格被替换等）会**自动回退**到完整链路，不会中断任务。

## 环境变量

| 变量 | 用途 |
|---|---|
| `KDOCS_TABLE_URL` | 在线表格链接 |
| `YZJ_WEBHOOK` | 云之家群机器人 Webhook |
| `KDOCS_FILE_ID` | 直接指定 file_id |
| `KDOCS_SHEET_ID` | 工作表 id |

## 目录结构

```
.
├── SKILL.md                          # Skill 主文档（含排错要点）
├── README.md                         # 本文件
├── scripts/
│   └── check_missing_fields.py       # 巡检脚本（核心）
└── samples/
    └── range_data.sample.json        # 样例数据（结构参考，可离线回放）
```

## 定时执行

每天 **17:00** 跑一次。在 WorkBuddy 云端定时任务中配置：

- **调度**：`每天 17:00`（`FREQ=DAILY;BYHOUR=17;BYMINUTE=0`，时区 `Asia/Shanghai`）
- **执行内容**：调用 `kdocs-missing-fields-check` Skill，拉表校验后按模板推送到云之家群
- **前置**：确保金山文档 Token 有效、`YZJ_WEBHOOK` 已在任务环境中配置

## 已知坑（务必先读）

1. **`get_range_data` 返回稀疏单元格数组** —— 必须按 `originRow`/`originCol` 建立坐标索引；
   按下标顺序对齐或做 `[:N]` 截断预览会**整行错位**，得出错误结论。
2. **行号 = Excel 真实行号** —— 第 1 行分组标题、**第 2 行表头**、**第 3 行起为数据**。
3. **kdocs-cli 输出尾部可能追加升级提示** —— 需用 `raw_decode()` 取第一个 JSON 对象。
4. **空值需归一化** —— 零宽字符、全角空格、换行都要清洗，否则漏判。
5. **遇 `429001`/`429002` 立即停止请求**，按响应中的恢复时间等待，禁止连续重试。

## 免责与安全

- 只读取指定表格的 `项目对接清单` 工作表，**不写入、不修改**任何单元格
- Webhook 与 Token 不硬编码在仓库中，通过环境变量或命令行传入
- Token 由 `kdocs-cli` 的密钥链管理，本仓库不存储任何凭据
