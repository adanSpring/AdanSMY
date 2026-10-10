#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务需求技术对接表日常跟进通报 —— 三段式校验（业务组 / 技术组 / 验收上线）

用途
----
读取金山文档在线表格「集团信息化 业务技术项目对接表」的「项目对接清单」工作表，
一次取数，依次执行三段校验，合并成一条消息推送提醒到云之家群机器人。

  一、【需求收集阶段】异常通报   ← 业务组填写完整性
  二、【技术评估/开发阶段】异常通报 ← 技术组 5 条规则
  三、【验收上线阶段】异常通报   ← 业务开发清单验收 6 条规则 + 验收结果清单统计
  四、【变更与操作合规】         ← 更新列内容提醒 + 不合规操作通报

三段均无异常时，整条消息**简化为**：表头（标题/链接/条数/时间）+ 空行 + 一句
「各项开发项进度无异常，奖励每人一朵小红花🌹」+ 空行，**不再展开三段**。

（2026-10-10 新增第四段【变更与操作合规】：
D1 更新列内容提醒 —— **不比对上一版本**，「更新列内容」非空且不含「YC已更新」即报警；
D2 不合规操作通报 —— 仍比对上一版本，「评估开发完成时间」被改且未走变更流程即通报。
第四段**仅在有异常时显示**；「简化版」的触发条件为**四段全无异常**。）

第一段：业务组填写完整性
------------------------
1. 必填项：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期
2. 至少填一项：业务背景与痛点、需求描述与业务价值
逐行检查，不满足任一条即为异常。
- 异常行若「需求负责人」有值 → 按负责人合并成一行，同行艾特并带行号后缀：
   「@张三：N行需求填写不完整（第2、4、5行）；」（同一负责人只出现一次）
- 异常行若「需求负责人」为空 → 合并成一条，艾特逄浩、原潮（顿号连接）并带行号后缀：
   「@逄浩、@原潮：N行需求填写不完整（第3、8行）；」
- 行号统一用 _rows_suffix() 渲染：一个「第」起头、顿号连列、末尾一个「行」。

第二段：技术组填报异常（5 条规则）
----------------------------------
涉及列（全部按「表头名称」定位，见下方「列定位」说明）：
    技术对接人、评估结果/排期结论、评估开发完成时间、逾期状态、技术组测试结果、技术组说明备注
1. 技术对接人：必须有人名，无人名 → 「@敦志勇  共x条需求，仍未设定技术对接人（第…行）；」
2. 评估结果/排期结论：仅支持「评估通过 / 评估不通过」；未填/填错 → 异常
   2.1 未填 且 技术对接人有值 且 (now - 提出日期 >= 24h) → 「@（技术对接人）：有x条需求，仍未反馈技术开发评估结果（第…行）；」
   2.2 未填 且 技术对接人有值 且 (now - 提出日期 < 24h)  → 不抛异常
   2.3 填错 且 技术对接人有值 → 「@（技术对接人）：有x条需求，请按表格格式填写（第…行）；」
   2.4 技术对接人无值的行 → 跳过
3. 评估开发完成时间：**仅当「评估结果/排期结论」=「评估通过」时**才必填，缺 → 「@（技术对接人）：有x条需求，仍未评估完成时间（第…行）；」
   （评估不通过的需求本就无需排期完成时间，不再报异常）
4. 逾期状态：若 评估开发完成时间 有值 且 技术组测试结果 ≠ 通过，
   再筛「逾期状态」**有值且不等于「未逾期」**的行（表格实际只填「未逾期」或留空）
   → 「@敦志勇 @逄浩 🔴有x条需求，已逾期（第…行）；」
5. 技术组说明备注：若 评估结果/排期结论 = 评估不通过 **且 技术组说明备注为空**
   → 「@（技术对接人）：有x条评审不通过的需求，请明确备注说明（第…行）；」
   （已填备注说明的需求不再催办）
- 有技术对接人 → 统一汇总，同一人只出现一次；每条同行艾特 + 行号后缀
- 技术对接人姓名做尾随数字归一化（「沈腾1」→「沈腾」），避免同一人被拆成两个 @对象

第三段：验收上线阶段（业务开发清单验收，6 条规则）
--------------------------------------------------
始终输出「■ 验收结果清单」统计块（总计/已通过/验收中/不通过）；
（第 3 行标签为「验收中」：统计口径 = 验收结果∈{验收中,待验收,空} 的合计）
有异常时追加「■ 异常结果」，6 条规则均同行艾特 + 行号后缀：
1. 测试通过 且 验收结果∈{待验收,验收中,空} → 「@需求负责人：有x条开发需求，请尽快完成验收（第…行）；」
   （验收结果为空视为待验收）
2. 验收结果=通过 且 实际上线时间空 且 闭环完成≠是 → 「…请尽快确认上线时间、闭环（第…行）；」
3. 验收结果=不通过 且 验收说明空 → 「…验收不通过，需要备注验收不通过原因（第…行）；」
4. 验收结果=不通过 且 评估结果=评估通过 → 「@技术对接人：有x条开发需求验收不通过，请尽快完成优化（第…行）；」
5. 评估结果=评估不通过 且 验收结果∉{通过,不通过} → 「…技术组反馈暂无法进行开发，请尽快确认需求方案（第…行）；」
6. 评估结果=评估不通过 且 验收结果=不通过 → 「@逄浩、@原潮 有x条开发需求，业务和技术组均存在疑问，需领导决策（第…行）；」
兜底：若异常明细行的需求负责人 / 技术对接人为空，则艾特原潮（NO_OWNER_AT）。

第四段：变更与操作合规（第四段，2 条规则）
------------------------------------------
基准：与去重锁同目录的 `version-snapshot.json`（「知识库」），保存上一版本每行的
「更新列内容」与「评估开发完成时间」；每轮比对后立即回写为最新版本。
「更新列内容」列缺失 → 本段整体跳过。
1. 【更新列内容提醒】**不比对上一版本**：只要「更新列内容」非空 且 不含「YC已更新」
   → 「@原潮：需求（第…行）申请变更列内容，请尽快更新！」（区块标题「■ 异常提醒」）
   · 该规则只看当前行自身状态，即使首次运行无快照也照常生效。
2. 【不合规操作通报】**仍需比对上一版本**：评估开发完成时间较上一版本变化，
   且 更新列内容 为空或不含「YC已更新」→ 「@（技术对接人，无则原潮）：需求（第…行）请勿直接修改开发完成时间！」
   （区块标题「🔴 异常通报」；上一版本为空、当前补填 → 不算异常）
   · 豁免：上一版本评估开发完成时间为空、当前有值（视为正常补填），不算异常。
- **本段无异常 → 整段不显示**（不输出标题、不输出小红花）；只有存在异常时才出现。

版式约定（重要）
----------------
三段标题后**不空行**，紧跟下一行内容（`一、【…】` 下一行直接是 `■ 异常结果` 或小红花）。
段与段之间用一个空行分隔（由 render_message 统一处理）。

列定位（重要）
--------------
本脚本不写死任何 A/B/C… 列号。启动时先读第 2 行表头，建立「表头名 → 实际列号」
映射，全程按名称取值。列顺序被调整也能正确定位；若任一必需列名在表头中找不到，
直接报错退出（exit 4），由人工确认表格后再重跑 —— 绝不静默错位、产出错误名单。

用法
----
    # 完整流程：拉取表格 → 校验 → 推送（有异常才推）
    python3 check_missing_fields.py

    # 只校验不推送（本地调试）
    python3 check_missing_fields.py --dry-run

    # 指定表格与群机器人
    python3 check_missing_fields.py --table-url "https://www.kdocs.cn/l/xxx" \
                                   --webhook "https://www.yunzhijia.com/gateway/robot/webhook/send?..."

    # 从已保存的 range-data JSON 离线校验
    python3 check_missing_fields.py --from-json ./samples/range_data.json --dry-run

环境变量
--------
    KDOCS_TABLE_URL    在线表格链接（等价于 --table-url）
    YZJ_WEBHOOK        云之家群机器人 Webhook（等价于 --webhook）
    KDOCS_FILE_ID      已知 file_id 时可直接指定，跳过链接解析
    KDOCS_SHEET_ID     「项目对接清单」工作表 id，默认 3
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# ── 默认配置 ────────────────────────────────────────────────
DEFAULT_TABLE_URL = "https://www.kdocs.cn/l/cchYxqp30FkG"
DEFAULT_SHEET_ID = 3           # 「项目对接清单」
DEFAULT_SHEET_NAME = "项目对接清单"

# 快速通道：已知 file_id 时可直接拉数，省掉「解析链接」「查工作表」两次往返。
# 实测取数耗时约 2.2s → 1.1s。若直连失败会自动回退到按链接解析的完整链路。
DEFAULT_FILE_ID = "2yRGboxQH9MLz2kbTHNErx8PtTCNR8GcJ"

# ── 列定位：按「表头名称」动态取列，不再依赖固定字母/列号 ──────────
# 表格列表头名称是稳定标识；列顺序偶尔会被调整，若按固定字母/列号取值，
# 一旦有人插列或挪列，就会把「技术对接人」当成「需求负责人」，静默产出
# 错误名单 —— 比任务直接失败更危险。
# 因此：启动时先读表头行，建立「表头名 → 实际列号」映射，全程按名称取值。
# 若任一必需列名在表头中找不到 → 直接报错退出（exit 4），由人工确认后改表/改脚本。

# 字段名（内部键）→ 表头文案（必须与表格中的表头文字完全一致）
FIELD_HEADERS = {
    "system":     "系统名称",
    "module":     "所属系统/模块",
    "branch":     "提出分公司",
    "proposer":   "需求提出人",
    "owner":      "需求负责人",
    "date":       "提出日期",
    "bg":         "业务背景与痛点",
    "desc":       "需求描述与业务价值",
    "priority":   "需求优先级",
    "tech":       "技术对接人",
    "eval_done":  "评估开发完成时间",
    "eval_result": "评估结果/排期结论",
    "overdue":    "逾期状态",
    "tech_test":  "技术组测试结果",
    "tech_note":  "技术组说明备注",
    # ―― 验收上线阶段（业务开发清单验收）――
    "accept_result": "业务组验收结果",
    "accept_note":   "验收说明",
    "accept_date":   "验收日期",
    "accept_person": "验收人",
    "online_time":   "实际上线时间",
    "online_effect": "实际上线效果",
    "closed_loop":   "闭环完成",
    # ―― 变更与操作合规（第四段）――
    "update_col":    "更新列内容",
}

# 模块A 必填项（内部键）
REQUIRED_FIELD_KEYS = ["system", "module", "branch", "proposer", "owner", "priority", "date"]

# 允许缺失的列（缺失时跳过对应校验，不触发 exit 4）：
# 「更新列内容」是第四段（变更与操作合规）专用列，若被改名/删除只跳过第四段。
OPTIONAL_FIELD_KEYS = {"update_col"}

# 模块A 至少填一项（内部键）
ANY_OF_KEYS = ["bg", "desc"]

# 表头与数据起始（0-based）：第 1 行分组标题，第 2 行表头，第 3 行起为数据
HEADER_ROW_INDEX = 1
DATA_START_INDEX = 2

# 扫描范围
MAX_SCAN_ROW = 3000       # 兜底上限（正常会被动态探测的行数覆盖）
MAX_SCAN_COL = 40         # 0-based 兜底列宽（列位置会变，放宽扫描范围；实际列由名称定位）
PROBE_ROWS = 20           # 探测实际行数时读取的行数窗口

# 推送重试
SEND_RETRIES = 3
SEND_BACKOFF = 3          # 秒；退避 3s → 6s → 9s

_BLANK_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff", "\xa0", "\u3000", "\r", "\n", "\t")

# 无异常通报用的花 —— 用 unicode 转义写死，避免不同编辑器/编码环节把字符弄丢
FLOWER = "\U0001F339"     # 🌹

# 逾期状态标签（规则4）
OVERDUE_DOT = "\U0001F534"   # 🔴

# 技术组固定艾特人
TECH_AT_NOMISS = "敦志勇"    # 规则1：未设定技术对接人，艾特敦志勇
TECH_AT_OVERDUE = ["敦志勇", "逄浩"]   # 规则4：逾期，艾特敦志勇 + 逄浩

# 评估结果/排期结论 允许的取值
EVAL_RESULT_OK = "评估通过"
EVAL_RESULT_FAIL = "评估不通过"
EVAL_RESULT_ALLOWED = {EVAL_RESULT_OK, EVAL_RESULT_FAIL}

# 技术组测试结果「通过」的判定值（用于规则4：不为通过才可能逾期）
TECH_TEST_PASS_VALUES = {"通过", "UAT通过", "测试通过"}

# 逾期状态：精确排除值 —— 等于「未逾期」的行一律不算逾期
# （表格实际只填「未逾期」或留空，不存在「是/逾期」这类真值，
#   因此判定逻辑为：有值 且 不等于「未逾期」→ 视为逾期。
#   绝不能再把「非空」直接当逾期，否则「未逾期」会被误报。）
OVERDUE_EXCLUDE_VALUES = {"未逾期", "未超期", "否", "N", "no", "No", "NO"}

# 技术对接人姓名归一化：剥离尾随数字（如「沈腾1」→「沈腾」），
# 避免同一人因表格里多写了个序号而被拆成两个 @对象。
# 只剥「末尾的纯数字」，不影响「张婉妮/刘新英」这类斜杠多人写法。
TECH_NAME_STRIP_TAIL_DIGITS = True

# 规则2.1 的时间阈值：提出日期距现在 >= 24h 才催评估结果
EVAL_REMIND_HOURS = 24

# 无需求负责人的异常行：消息开头额外艾特的跟进人（2026-09-24 新增规则）
NO_OWNER_AT = "原潮"

# 两段共用的结尾提示语（业务组 / 技术组统一用同一句）
FOOTER_NOTE = "注意：请尽快完善并跟进处理各自的需求任务～"

# ―― 验收上线阶段（业务开发清单验收）――
# 业务组验收结果 允许的取值
ACCEPT_PASS = "通过"
ACCEPT_FAIL = "不通过"
# 规则1 触发条件：验收结果 ∈ {待验收, 验收中} 或为空（空值视为待验收）
ACCEPT_PENDING_VALUES = {"待验收", "验收中", "待验收中", "待验证", ""}

# 闭环完成「是」的判定值
CLOSED_TRUE_VALUES = {"是", "已完成", "闭环", "true", "True", "TRUE", "Y"}

# 规则6 艾特：业务与技术组均有疑问，需领导决策
LEADER_AT = ["逄浩", "原潮"]

# ―― 第四段【变更与操作合规】――
# 更新列内容提醒：**不比对上一版本** —— 更新列内容 非空 且 不含「YC已更新」→ 艾特原潮，提醒尽快更新
UPDATE_CHANGE_AT = "原潮"
UPDATE_CHANGE_MSG = "申请变更列内容，请尽快更新！"

# 不合规操作通报：**需比对上一版本** —— 评估开发完成时间较上一版本变化，且更新列内容 为空/不含 YC已更新 → 异常
# （上一版本评估完成时间为空、当前有值 → 视为正常补填，不算异常）
YC_UPDATED_TOKEN = "YC已更新"    # 更新列内容中的合规标记（含此串即视为已走变更流程）
INVALID_MODIFY_MSG = "请勿直接修改开发完成时间！"

# 第四段两区块标题
CHG_UPDATE_BLOCK_TITLE = "■ 异常提醒"    # D1 区块（更新列内容提醒）
CHG_INVALID_BLOCK_TITLE = "🔴 异常通报"   # D2 区块（不合规操作通报）

# 无异常时展示的「小红花」文案（前三段各一句）
# 注意：第四段（变更与操作合规）无异常时整段不显示，故无需小红花文案。
FLOWER_NOTE_COLLECT = "业务组表现优异，今日无异常，奖励一朵小红花🌹"
FLOWER_NOTE_TECH = "技术组表现优异，今日无异常，奖励一朵小红花🌹"
FLOWER_NOTE_ACCEPT = "各项开发项进度无异常，奖励每人一朵小红花🌹"


# ── 工具函数 ────────────────────────────────────────────────
def norm(value) -> str:
    """归一化单元格值：None、空白、零宽字符、全角空格统一视为空字符串。"""
    if value is None:
        return ""
    text = str(value)
    for ch in _BLANK_CHARS:
        text = text.replace(ch, "")
    return text.strip()


def norm_tech_name(value) -> str:
    """技术对接人姓名归一化：在 norm() 基础上剥离尾随纯数字。

    表格里同一个人常被写成「沈腾」和「沈腾1」两种，若不归一化，
    同一个人会被拆成两个 @对象，消息里出现重复条目。
    只剥「末尾的纯数字」，「张婉妮/刘新英」这类斜杠多人写法不受影响。
    """
    text = norm(value)
    if not text or not TECH_NAME_STRIP_TAIL_DIGITS:
        return text
    stripped = re.sub(r"\d+$", "", text).strip()
    return stripped or text      # 全数字的极端情况保留原值，避免变成空串


def build_grid(cells) -> dict:
    """把 kdocs rangeData 稀疏单元格数组转成 grid[row][col] = cellText。

    注意：get_range_data 只返回「有值」的单元格，必须按 originRow/originCol
    精确索引，绝不能按下标顺序对齐，否则会整行错位。
    """
    grid: dict[int, dict[int, str]] = {}
    for cell in cells:
        row = cell.get("originRow")
        col = cell.get("originCol")
        if row is None or col is None:
            continue
        grid.setdefault(int(row), {})[int(col)] = cell.get("cellText", "") or ""
    return grid


class HeaderMismatch(RuntimeError):
    """必需列名在表头中找不到 —— 表格结构变了，必须人工介入，绝不能继续校验。"""


def resolve_columns(cells) -> dict:
    """按「表头名称」定位各字段的实际列号，返回 {field_key: col_index}。

    这是全脚本唯一决定「哪一列是什么」的地方：
      - 读第 HEADER_ROW_INDEX 行表头；
      - 用字段的中文表头文案去匹配，命中即取该列的真实列号；
      - 任一必需列名匹配不到 → 抛 HeaderMismatch（由 main 捕获后 exit 4）。

    这样列顺序即便被调整，也能正确定位；列名找不到则明确报错，绝不静默错位。
    """
    grid = build_grid(cells)
    header_row = grid.get(HEADER_ROW_INDEX, {})
    if not header_row:
        raise HeaderMismatch(
            f"第 {HEADER_ROW_INDEX + 1} 行未读到表头，表格结构可能已变更。"
        )

    # 表头文案（归一化后）→ 列号；同名多列取最先出现的一列
    name_to_col: dict[str, int] = {}
    for col in sorted(header_row):
        text = norm(header_row.get(col, ""))
        if text and text not in name_to_col:
            name_to_col[text] = col

    mapping: dict[str, int] = {}
    missing: list[str] = []
    for key, header in FIELD_HEADERS.items():
        col = name_to_col.get(header)
        if col is None:
            # 「更新列内容」为第四段（变更与操作合规）专用列：缺失时不硬失败，
            # 仅跳过第四段校验（见 check_rows 中 update_col 缺省处理）。
            if key in OPTIONAL_FIELD_KEYS:
                continue
            missing.append(header)
        else:
            mapping[key] = col

    if missing:
        found = "、".join(sorted(name_to_col)) or "（空）"
        raise HeaderMismatch(
            "以下必需列名未在表头中找到：\n"
            + "\n".join(f"   - 「{m}」" for m in missing)
            + f"\n   本次读到的表头为：{found}\n"
            + "   请确认表格列名是否被改名/删除；确认后修正表格或脚本 FIELD_HEADERS 再重跑。"
        )
    return mapping


def detect_last_row(file_id: str, sheet_id: int) -> int:
    """动态探测数据区实际最后一行（0-based），避免固定拉取 3000 行的浪费。"""
    payload = {
        "file_id": file_id,
        "sheetId": sheet_id,
        "range": {"rowFrom": 0, "rowTo": PROBE_ROWS, "colFrom": 0, "colTo": MAX_SCAN_COL},
    }
    try:
        out = run_kdocs(
            ["sheet", "get-range-data", json.dumps(payload, ensure_ascii=False),
             "--silent", "--compact"],
            timeout=60,
        )
        obj = parse_first_json(out)
        detail = obj.get("detail") or obj.get("data", {}).get("detail", {})
        rows = [int(c["originRow"]) for c in detail.get("rangeData", [])
                if c.get("originRow") is not None]
        if rows:
            # 探测窗口内最大行 + 余量，留出表格增长空间
            return min(max(rows) + 200, MAX_SCAN_ROW)
    except Exception:  # noqa: BLE001 - 探测失败就退回全量上限，不影响主流程
        pass
    return MAX_SCAN_ROW


def run_kdocs(args: list[str], timeout: int = 120) -> str:
    """调用 kdocs-cli 并返回 stdout。

    若 kdocs-cli 不在 PATH 中，会尝试几个常见安装位置后再报错。
    """
    exe = _find_kdocs_cli()
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "未找到 kdocs-cli。请先安装：bash scripts/setup.sh（金山文档 Skill 内置脚本），"
            f"或确认 PATH 已包含安装目录（默认 ~/.local/bin）。当前 PATH={os.environ.get('PATH','')}"
        ) from None
    if proc.returncode != 0:
        raise RuntimeError(f"kdocs-cli 执行失败（exit {proc.returncode}）：{proc.stderr.strip()[:500]}")
    return proc.stdout


def _find_kdocs_cli() -> str:
    """定位 kdocs-cli 可执行文件，兼容 PATH 未包含安装目录的情况。"""
    import shutil

    found = shutil.which("kdocs-cli")
    if found:
        return found
    for cand in (
        os.path.expanduser("~/.local/bin/kdocs-cli"),
        "/usr/local/bin/kdocs-cli",
        "/usr/bin/kdocs-cli",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    # 都没找到：交回裸命令名，由 subprocess 抛 FileNotFoundError 统一报错
    return "kdocs-cli"


def parse_first_json(text: str) -> dict:
    """kdocs-cli 的 JSON 输出后可能追加升级提示，用 raw_decode 只取第一个对象。"""
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"未在输出中找到 JSON：{text[:300]}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


# ── 当日去重锁 ──────────────────────────────────────────────
# 保证「每天只推送一次」：即使任务被重试、手动补跑或多人共用同一环境，
# 同一天内也只推送第一条，后续运行只做校验、不再发消息。
LOCK_DIR = os.path.expanduser(os.getenv("CHECK_LOCK_DIR", "~/.cache/intake-check"))
LOCK_FILE = os.path.join(LOCK_DIR, "send-state.json")


def _load_state(lock_file: str) -> dict:
    try:
        with open(lock_file, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def already_sent_today(today: str, lock_file: str = LOCK_FILE) -> tuple[bool, str]:
    """检查今天是否已经推送过。返回 (是否已推送, 上次推送时间)。"""
    state = _load_state(lock_file)
    if state.get("last_sent_date") == today:
        return True, state.get("last_sent_at", "")
    return False, ""


def mark_sent_today(today: str, at: str, msg_id: str = "",
                    lock_file: str = LOCK_FILE) -> None:
    """记录今天已推送，写入去重锁。"""
    os.makedirs(os.path.dirname(lock_file) or ".", exist_ok=True)
    state = _load_state(lock_file)
    state["last_sent_date"] = today
    state["last_sent_at"] = at
    state["last_msg_id"] = msg_id
    tmp = lock_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, lock_file)   # 原子写入，避免并发读到半截文件


# ── 版本快照（第四段 D2【不合规操作通报】的比对基准）────────────────
# 「知识库」= 与去重锁同目录的 schema 快照文件：保存「上一版本」每行的
# 「更新列内容」与「评估开发完成时间」。每轮比对完立即回写为最新版本，
# 使下一次运行以「本次」为基准，从而稳定识别「较上一次核验的版本」的变化。
SNAPSHOT_FILE = os.path.join(LOCK_DIR, "version-snapshot.json")


def load_snapshot(snapshot_file: str = SNAPSHOT_FILE) -> dict | None:
    """读取上一版本快照。返回 {行号(str): {"update_col":…, "eval_done":…}}；不存在返回 None。"""
    if not os.path.exists(snapshot_file):
        return None
    try:
        with open(snapshot_file, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    rows = data.get("rows") if isinstance(data, dict) else None
    return rows if isinstance(rows, dict) else None


def save_snapshot(rows: dict, snapshot_file: str = SNAPSHOT_FILE) -> None:
    """把本轮快照回写为最新版本（原子写入）。"""
    if not rows:
        return
    os.makedirs(os.path.dirname(snapshot_file) or ".", exist_ok=True)
    payload = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "col": FIELD_HEADERS["update_col"],
        "rows": rows,
    }
    tmp = snapshot_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, snapshot_file)


def resolve_file_id(table_url: str, explicit_file_id: str | None = None) -> str:
    """从在线表格链接解析 file_id。"""
    if explicit_file_id:
        return explicit_file_id
    out = run_kdocs(["drive", "read-file", f"url={table_url}", "--silent", "--compact"])
    obj = parse_first_json(out)
    file_id = obj.get("file_id") or obj.get("data", {}).get("file_id")
    if not file_id:
        raise RuntimeError(f"未能从链接解析出 file_id：{table_url}")
    return file_id


def find_sheet_id(file_id: str, sheet_name: str, sheet_id: int | None) -> int:
    """定位目标工作表的 sheetId。"""
    if sheet_id is not None:
        return sheet_id
    out = run_kdocs(["sheet", "get-sheets-info", f"file_id={file_id}", "--silent", "--compact"])
    obj = parse_first_json(out)
    sheets = (
        obj.get("detail", {}).get("sheetsInfo")
        or obj.get("data", {}).get("detail", {}).get("sheetsInfo")
        or []
    )
    for s in sheets:
        if norm(s.get("sheetName")) == sheet_name:
            return int(s["sheetId"])
    names = [s.get("sheetName") for s in sheets]
    raise RuntimeError(f"未找到工作表「{sheet_name}」，当前工作表：{names}")


def fetch_all(file_id: str, sheet_id: int, row_to: int = MAX_SCAN_ROW) -> list:
    """读取「项目对接清单」数据区域（含表头），返回 rangeData 单元格数组。"""
    payload = {
        "file_id": file_id,
        "sheetId": sheet_id,
        "range": {
            "rowFrom": 0,
            "rowTo": row_to,
            "colFrom": 0,
            "colTo": MAX_SCAN_COL,
        },
    }
    out = run_kdocs(
        ["sheet", "get-range-data", json.dumps(payload, ensure_ascii=False), "--silent", "--compact"],
        timeout=180,
    )
    obj = parse_first_json(out)
    detail = obj.get("detail") or obj.get("data", {}).get("detail", {})
    return detail.get("rangeData", []) or []


def fetch_with_fallback(table_url: str, sheet_id: int,
                        file_id: str | None, sheet_name: str) -> tuple[list, str]:
    """取数：优先走快速通道（已知 file_id），失败则回退到完整解析链路。

    快速通道省掉「解析链接」+「查工作表」两次 API 往返，实测约 2.2s → 1.1s。
    行数先动态探测（避免固定拉 3000 行），探测失败则退回全量上限。
    返回 (cells, file_id)。
    """
    if file_id:
        try:
            row_to = detect_last_row(file_id, sheet_id)
            cells = fetch_all(file_id, sheet_id, row_to)
            if cells:
                return cells, file_id
            print("⚠️ 快速通道返回空数据，回退到完整链路…", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - 任何异常都回退，保证任务不中断
            print(f"⚠️ 快速通道失败（{exc}），回退到完整链路…", file=sys.stderr)

    resolved_id = resolve_file_id(table_url)
    real_sheet_id = find_sheet_id(resolved_id, sheet_name, None)
    row_to = detect_last_row(resolved_id, real_sheet_id)
    return fetch_all(resolved_id, real_sheet_id, row_to), resolved_id


# ── 核心校验 ────────────────────────────────────────────────
def _parse_date(text: str) -> datetime | None:
    """尽力解析提出日期。支持 2026-09-20 / 2026/9/20 / 2026.09.20 等。"""
    text = norm(text)
    if not text:
        return None
    cleaned = text.replace("年", "-").replace("月", "-").replace("日", "")
    cleaned = cleaned.replace("/", "-").replace(".", "-")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def check_rows(cells, cols: dict, now: datetime | None = None,
               prev_snapshot: dict | None = None) -> dict:
    """逐行校验业务组 + 技术组 + 验收上线 + 变更与操作合规，返回结构化结果。

    cols：由 resolve_columns(cells) 得到的 {field_key: col_index} 列映射，
          全程按名称定位的列号取值。
    prev_snapshot：上一版本快照 {excel_row: {"update_col":…, "eval_done":…}}，
          用于第四段 D2【不合规操作通报】的版本对比；为 None 时跳过 D2（首次运行）。
          （D1【更新列内容提醒】不看快照，始终生效。）
    """
    now = now or datetime.now()
    grid = build_grid(cells)

    data_rows = sorted(r for r in grid if r >= DATA_START_INDEX)

    # 预取列号（按名称定位的结果）
    c_date = cols["date"]
    c_owner = cols["owner"]
    c_tech = cols["tech"]
    c_eval_result = cols["eval_result"]
    c_eval_done = cols["eval_done"]
    c_overdue = cols["overdue"]
    c_tech_test = cols["tech_test"]
    c_tech_note = cols["tech_note"]
    # ―― 验收上线阶段 ――
    c_accept_result = cols["accept_result"]
    c_accept_note = cols["accept_note"]
    c_online_time = cols["online_time"]
    c_closed_loop = cols["closed_loop"]
    # ―― 第四段：变更与操作合规（更新列内容为可选列）――
    c_update_col = cols.get("update_col")

    total = 0
    abnormal = []          # 业务组：[(excel_row, owner, missing_fields)]
    label = str(now.year - 1)
    # 技术组异常累积容器
    tech_missing_tech = []          # 规则1：无技术对接人 → [excel_row]
    tech_no_eval = []               # 规则2.1：未填评估结果且超24h → [(excel_row, tech)]
    tech_bad_eval = []              # 规则2.3：填错评估结果 → [(excel_row, tech)]
    tech_no_done = []               # 规则3：缺评估完成时间 → [(excel_row, tech)]
    tech_overdue = []               # 规则4：逾期 → [excel_row]
    tech_reject = []                # 规则5：评审不通过 → [(excel_row, tech, note)]
    # ―― 验收上线阶段 异常累积容器 ――
    # 每条异常记为 (excel_row, at_name, text)，at_name 为应@的人（负责人/技术对接人/原潮兜底）
    acc_wait_accept = []            # 规则1：测试通过但未验收 → [(row, at, owner)]
    acc_confirm_online = []         # 规则2：已验收通过但未确认上线/闭环 → [(row, at, owner)]
    acc_no_note = []                # 规则3：验收不通过但无验收说明 → [(row, at, owner)]
    acc_redo = []                   # 规则4：验收不通过且技术评估通过 → [(row, at, tech)]
    acc_undecided = []              # 规则5：技术评估不通过且验收未定 → [(row, at, owner)]
    acc_leader = []                 # 规则6：双方均疑问 → [(row, "逄浩/原潮", "")]
    # ―― 第四段【变更与操作合规】异常累积容器 ――
    chg_update = []                 # 更新列内容有变化 → [(excel_row, at, "")]，艾特原潮
    chg_invalid = []                # 评估完成时间被违规修改 → [(excel_row, at, tech)]，艾特技术对接人
    # 第四段版本对比只能在「有上一版本快照」时进行；无快照则整体跳过（首次运行）
    prev = prev_snapshot if isinstance(prev_snapshot, dict) else None
    compare_enabled = bool(prev) and c_update_col is not None

    # 本轮快照：每行 {update_col, eval_done}，供下一轮比对
    cur_snapshot: dict[str, dict[str, str]] = {}

    for row_idx in data_rows:
        row = grid.get(row_idx, {})
        # 整行全空 → 非需求行，跳过且不计入总数
        if all(norm(row.get(c, "")) == "" for c in range(MAX_SCAN_COL + 1)):
            continue
        # 上一自然年的数据属于历史归档，不再催办
        if label in str(row.get(c_date, "")):
            continue
        total += 1
        excel_row = row_idx + 1        # 0-based → Excel 真实行号

        owner = norm(row.get(c_owner, ""))
        tech = norm_tech_name(row.get(c_tech, ""))      # 尾随数字归一化（沈腾1→沈腾）
        eval_result = norm(row.get(c_eval_result, ""))
        eval_done = norm(row.get(c_eval_done, ""))
        overdue_val = norm(row.get(c_overdue, ""))
        tech_test = norm(row.get(c_tech_test, ""))
        tech_note = norm(row.get(c_tech_note, ""))
        propose_date = _parse_date(row.get(c_date, ""))

        # ── 模块 A：业务组填写完整性 ──
        missing = []
        for key in REQUIRED_FIELD_KEYS:
            if norm(row.get(cols[key], "")) == "":
                missing.append(FIELD_HEADERS[key])
        if all(norm(row.get(cols[k], "")) == "" for k in ANY_OF_KEYS):
            missing.append("／".join(FIELD_HEADERS[k] for k in ANY_OF_KEYS) + "（至少填一项）")
        if missing:
            abnormal.append((excel_row, owner, missing))

        # ── 模块 B：技术组填报异常 ──
        # 规则1：技术对接人必须有人名
        if not tech:
            tech_missing_tech.append(excel_row)

        # 规则2 / 3 / 4 / 5：仅在「有技术对接人」时判定（规则2.4 无对接人则跳过）
        if tech:
            eval_filled = eval_result != ""
            eval_valid = eval_result in EVAL_RESULT_ALLOWED

            if not eval_filled:
                # 规则2.1 / 2.2：未填评估结果，按提出日期是否满 24h 决定是否催办
                if propose_date is not None:
                    elapsed_h = (now - propose_date).total_seconds() / 3600.0
                    if elapsed_h >= EVAL_REMIND_HOURS:
                        tech_no_eval.append((excel_row, tech))
                # 若提出日期缺失/无法解析：无法判断 24h，按宽松处理不催办
            elif not eval_valid:
                # 规则2.3：填错
                tech_bad_eval.append((excel_row, tech))
            else:
                # 规则3：**仅当「评估结果 = 评估通过」时**才要求填评估完成时间。
                # 「评估不通过」的需求本就无需排期完成时间，不再因此报异常。
                if eval_result == EVAL_RESULT_OK and not eval_done:
                    tech_no_done.append((excel_row, tech))

            # 规则4：有评估完成时间 且 技术组测试结果不为通过 → 再看逾期状态
            # 判定：逾期状态「有值」且「不等于未逾期」才算逾期。
            if eval_done and tech_test not in TECH_TEST_PASS_VALUES:
                if overdue_val and overdue_val not in OVERDUE_EXCLUDE_VALUES:
                    tech_overdue.append(excel_row)

            # 规则5：评估结果 = 评估不通过 **且「技术组说明备注」为空** → 异常
            # （填了备注说明的不再催办，避免已说明原因的需求被反复提醒）
            if eval_result == EVAL_RESULT_FAIL and tech_note == "":
                tech_reject.append((excel_row, tech, tech_note))

        # ── 模块 C：验收上线阶段（业务开发清单验收）──
        accept_result = norm(row.get(c_accept_result, ""))
        accept_note = norm(row.get(c_accept_note, ""))
        online_time = norm(row.get(c_online_time, ""))
        closed_loop = norm(row.get(c_closed_loop, ""))

        is_eval_pass = (eval_result == EVAL_RESULT_OK)
        is_eval_fail = (eval_result == EVAL_RESULT_FAIL)
        is_test_pass = (tech_test in TECH_TEST_PASS_VALUES)
        is_accept_pass = (accept_result == ACCEPT_PASS)
        is_accept_fail = (accept_result == ACCEPT_FAIL)
        is_accept_pending = (accept_result in ACCEPT_PENDING_VALUES or accept_result == "")
        is_closed = (closed_loop in CLOSED_TRUE_VALUES)

        # 规则1：技术组测试结果=通过 且 验收结果∈{待验收,空} → @需求负责人
        if is_test_pass and is_accept_pending:
            acc_wait_accept.append((excel_row, owner or NO_OWNER_AT, owner))
        # 规则2：验收结果=通过 且 实际上线时间空 且 闭环完成≠是 → @需求负责人
        if is_accept_pass and online_time == "" and not is_closed:
            acc_confirm_online.append((excel_row, owner or NO_OWNER_AT, owner))
        # 规则3：验收结果=不通过 且 验收说明空 → @需求负责人
        if is_accept_fail and accept_note == "":
            acc_no_note.append((excel_row, owner or NO_OWNER_AT, owner))
        # 规则4：验收结果=不通过 且 评估结果=评估通过 → @技术对接人
        if is_accept_fail and is_eval_pass:
            acc_redo.append((excel_row, tech or NO_OWNER_AT, tech))
        # 规则5：评估结果=评估不通过 且 验收结果∉{通过,不通过} → @需求负责人
        if is_eval_fail and not is_accept_pass and not is_accept_fail:
            acc_undecided.append((excel_row, owner or NO_OWNER_AT, owner))
        # 规则6：评估结果=评估不通过 且 验收结果=不通过 → @逄浩 @原潮
        if is_eval_fail and is_accept_fail:
            acc_leader.append(excel_row)

        # ── 模块 D：变更与操作合规（第四段）──
        # 规则D1【更新列内容提醒】：**不比对上一版本** ——
        #   只要「更新列内容」列非空、且不含「YC已更新」串 → 抛异常，艾特原潮。
        #   （该规则只看当前行自身状态，即使首次运行无快照也应生效，故独立于 compare_enabled。）
        if c_update_col is not None:
            update_col = norm(row.get(c_update_col, ""))
            if update_col and YC_UPDATED_TOKEN not in update_col:
                chg_update.append((excel_row, UPDATE_CHANGE_AT, ""))

        # 规则D2【不合规操作通报】：**仍需与上一版本快照比对** ——
        #   评估开发完成时间较上一版本变化，且 更新列内容 未走变更流程 → 艾特技术对接人。
        #   - 变化：当前 ≠ 上一版本
        #   - 豁免：上一版本为空（视为正常补填）
        #   - 合规：更新列内容含「YC已更新」
        if compare_enabled:
            prev_row = prev.get(str(excel_row)) or prev.get(excel_row) or {}
            prev_done = norm(prev_row.get("eval_done", ""))
            update_col = norm(row.get(c_update_col, "")) if c_update_col is not None else ""
            if eval_done != prev_done and prev_done != "" \
                    and YC_UPDATED_TOKEN not in update_col:
                chg_invalid.append((excel_row, tech or NO_OWNER_AT, tech))

        # 记录本轮快照（无论是否可比对，都持续更新为最新版本）
        if c_update_col is not None:
            cur_snapshot[str(excel_row)] = {
                "update_col": norm(row.get(c_update_col, "")),
                "eval_done": norm(row.get(c_eval_done, "")),
            }

    # 汇总：有负责人 → 按负责人归并；无负责人 → 按行号单独列出
    owner_map: dict[str, list[int]] = {}
    no_owner_rows: list[int] = []
    for excel_row, owner, _ in abnormal:
        if owner:
            owner_map.setdefault(owner, []).append(excel_row)
        else:
            no_owner_rows.append(excel_row)

    # 技术组汇总：按技术对接人归并（同一人只出现一次）
    def _group_tech(pairs: list[tuple[int, str]]) -> dict[str, list[int]]:
        m: dict[str, list[int]] = {}
        for excel_row, t in pairs:
            m.setdefault(t, []).append(excel_row)
        return m

    # 验收阶段汇总：按 @对象 归并（同一人只出现一次）
    def _group_acc(pairs: list[tuple[int, str, str]]) -> dict[str, list[int]]:
        m: dict[str, list[int]] = {}
        for excel_row, at, _ in pairs:
            m.setdefault(at, []).append(excel_row)
        return m

    # 第四段汇总：按 @对象 归并（同一人只出现一次）
    chg_update_map = _group_acc(chg_update)
    chg_invalid_map = _group_acc(chg_invalid)

    # 验收结果清单统计（按「业务组验收结果」列归类）
    # pending 口径 = 非「通过」且非「不通过」的全部行（即 {验收中, 待验收, 空} 合计），
    # 展示标签为「验收中」。
    acc_stats = {"total": total, "pass": 0, "pending": 0, "fail": 0}
    for row_idx in data_rows:
        row = grid.get(row_idx, {})
        if all(norm(row.get(c, "")) == "" for c in range(MAX_SCAN_COL + 1)):
            continue
        if label in str(row.get(c_date, "")):
            continue
        ar = norm(row.get(c_accept_result, ""))
        if ar == ACCEPT_PASS:
            acc_stats["pass"] += 1
        elif ar == ACCEPT_FAIL:
            acc_stats["fail"] += 1
        else:
            acc_stats["pending"] += 1

    return {
        "total": total,
        "abnormal": abnormal,
        "owner_map": owner_map,
        "no_owner_rows": sorted(no_owner_rows),
        "check_time": now.strftime("%Y-%m-%d %H:%M"),
        # 技术组
        "tech_missing_tech": tech_missing_tech,
        "tech_no_eval": _group_tech(tech_no_eval),
        "tech_bad_eval": _group_tech(tech_bad_eval),
        "tech_no_done": _group_tech(tech_no_done),
        "tech_overdue": tech_overdue,
        "tech_reject": _group_tech([(r, t) for r, t, _ in tech_reject]),
        # 验收上线阶段
        "acc_stats": acc_stats,
        "acc_wait_accept": _group_acc(acc_wait_accept),
        "acc_confirm_online": _group_acc(acc_confirm_online),
        "acc_no_note": _group_acc(acc_no_note),
        "acc_redo": _group_acc(acc_redo),
        "acc_undecided": _group_acc(acc_undecided),
        "acc_leader": sorted(acc_leader),
        # 变更与操作合规（第四段）
        "chg_update": chg_update_map,      # {原潮: [行号]}
        "chg_invalid": chg_invalid_map,    # {技术对接人: [行号]}
        "chg_compare_enabled": compare_enabled,
        "cur_snapshot": cur_snapshot,      # 本轮最新快照，供回写
    }


def _rows_suffix(rows: list[int]) -> str:
    """把行号列表渲染成「（第2、4、5行）」后缀：一个「第」起头、顿号连列、末尾一个「行」。

    单行 → （第2行）；多行 → （第2、4、5行）；无行号 → 空串。
    """
    if not rows:
        return ""
    return "（第" + "、".join(str(r) for r in rows) + "行）"


def _render_collect(result: dict) -> str:
    """渲染「一、【需求收集阶段】异常通报」段落（业务组填写完整性）。

    规则（2026-10-08 调整）：
      - 不再单独一行艾特，改为「@负责人：N行需求填写不完整（第x、y行）；」同一行
      - 有负责人 → 按负责人归并，每条带全部行号
      - 无负责人 → 所有无负责人的行合并成一条，艾特逄浩 + 原潮
      - 无异常 → 只输出「小红花」一句（不显示异常检查规则）
    """
    lines = ["一、【需求收集阶段】异常通报"]

    owner_map = result["owner_map"]
    no_owner_rows = result["no_owner_rows"]
    has_any = bool(owner_map or no_owner_rows)

    if not has_any:
        # 标题紧跟小红花（保持与有异常场景「标题后直接接内容」一致）
        lines += [FLOWER_NOTE_COLLECT, ""]
        return "\n".join(lines)

    lines.append("■ 异常结果")
    for name, rows in owner_map.items():
        lines.append(f"@{name}：{len(rows)}行需求填写不完整{_rows_suffix(rows)}；")
    # 无负责人：合并成一条，艾特 逄浩、原潮（顿号连接）
    if no_owner_rows:
        at_line = "、".join(f"@{n}" for n in LEADER_AT)
        lines.append(f"{at_line}：{len(no_owner_rows)}行需求填写不完整{_rows_suffix(no_owner_rows)}；")

    lines += [
        "",
        "■ 异常检查规则",
        "必填项：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期；",
        "至少填一项：业务背景与痛点、需求描述与业务价值；",
    ]
    return "\n".join(lines)


def _render_tech_stage(result: dict) -> str:
    """渲染「二、【技术评估/开发阶段】异常通报」段落（技术组 5 条规则）。

    规则：
      - 有异常 → ■ 异常结果（逐条规则差异）
      - 无异常 → 只输出「小红花」一句
    """
    lines = ["二、【技术评估/开发阶段】异常通报"]

    has_any = any([
        result["tech_missing_tech"], result["tech_no_eval"], result["tech_bad_eval"],
        result["tech_no_done"], result["tech_overdue"], result["tech_reject"],
    ])
    if not has_any:
        # 标题紧跟小红花（保持与有异常场景「标题后直接接内容」一致）
        lines += [FLOWER_NOTE_TECH, ""]
        return "\n".join(lines)

    lines.append("■ 异常结果")

    # 规则1：无技术对接人 → 艾特敦志勇（带行号）
    if result["tech_missing_tech"]:
        rows = result["tech_missing_tech"]
        lines.append(f"@{TECH_AT_NOMISS}  共{len(rows)}条需求，仍未设定技术对接人{_rows_suffix(rows)}；")

    # 规则2.1：未反馈评估结果 → 「@技术对接人：有N条需求，仍未反馈技术开发评估结果（第x、y条）；」
    for t, rows in result["tech_no_eval"].items():
        lines.append(f"@{t}：有{len(rows)}条需求，仍未反馈技术开发评估结果{_rows_suffix(rows)}；")

    # 规则2.3：评估结果填错 → 带行号
    for t, rows in result["tech_bad_eval"].items():
        lines.append(f"@{t}：有{len(rows)}条需求，请按表格格式填写{_rows_suffix(rows)}；")

    # 规则3：缺评估完成时间 → 带行号
    for t, rows in result["tech_no_done"].items():
        lines.append(f"@{t}：有{len(rows)}条需求，仍未评估完成时间{_rows_suffix(rows)}；")

    # 规则4：逾期 → 艾特敦志勇 + 逄浩（带行号）
    if result["tech_overdue"]:
        rows = result["tech_overdue"]
        at_line = " ".join(f"@{t}" for t in TECH_AT_OVERDUE)
        lines.append(f"{at_line} {OVERDUE_DOT}有{len(rows)}条需求，已逾期{_rows_suffix(rows)}；")

    # 规则5：评审不通过 → 带行号
    for t, rows in result["tech_reject"].items():
        lines.append(f"@{t}：有{len(rows)}条评审不通过的需求，请明确备注说明{_rows_suffix(rows)}；")

    return "\n".join(lines)


def _render_accept_stage(result: dict) -> str:
    """渲染「三、【验收上线阶段】异常通报」段落（业务开发清单验收）。

    规则：
      - 始终输出「■ 验收结果清单」统计块（只要跑就输出）
      - 有异常 → ■ 异常结果（6 条规则差异，每条同行艾特 + 行号）
      - 无异常 → 统计块 + 小红花
    """
    lines = ["三、【验收上线阶段】异常通报"]

    s = result["acc_stats"]
    lines += [
        "■ 验收结果清单",
        f"总计：{s['total']}条开发需求",
        f"已通过：{s['pass']}条",
        f"验收中：{s['pending']}条",
        f"不通过：{s['fail']}条",
    ]

    has_any = any([
        result["acc_wait_accept"], result["acc_confirm_online"], result["acc_no_note"],
        result["acc_redo"], result["acc_undecided"], result["acc_leader"],
    ])
    if not has_any:
        # 统计块后空一行再给小红花
        lines += ["", FLOWER_NOTE_ACCEPT, ""]
        return "\n".join(lines)

    lines += ["", "■ 异常结果"]

    # 规则1：测试通过但未验收 → @需求负责人（带行号）
    for a, rows in result["acc_wait_accept"].items():
        lines.append(f"@{a}：有{len(rows)}条开发需求，请尽快完成验收{_rows_suffix(rows)}；")

    # 规则2：已验收通过但未确认上线时间/闭环 → @需求负责人（带行号）
    for a, rows in result["acc_confirm_online"].items():
        lines.append(f"@{a}：有{len(rows)}条开发需求已验收通过，请尽快确认上线时间、闭环{_rows_suffix(rows)}；")

    # 规则3：验收不通过但无验收说明 → @需求负责人（带行号）
    for a, rows in result["acc_no_note"].items():
        lines.append(f"@{a}：有{len(rows)}条开发需求，验收不通过，需要备注验收不通过原因{_rows_suffix(rows)}；")

    # 规则4：验收不通过且技术评估通过 → @技术对接人（带行号）
    for a, rows in result["acc_redo"].items():
        lines.append(f"@{a}：有{len(rows)}条开发需求验收不通过，请尽快完成优化{_rows_suffix(rows)}；")

    # 规则5：技术评估不通过且验收未定 → @需求负责人（带行号）
    for a, rows in result["acc_undecided"].items():
        lines.append(f"@{a}：有{len(rows)}条开发需求，技术组反馈暂无法进行开发，请尽快确认需求方案{_rows_suffix(rows)}；")

    # 规则6：双方均有疑问 → @逄浩、@原潮（顿号连接，带行号）
    if result["acc_leader"]:
        at_line = "、".join(f"@{t}" for t in LEADER_AT)
        lines.append(f"{at_line} 有{len(result['acc_leader'])}条开发需求，业务和技术组均存在疑问，需领导决策{_rows_suffix(result['acc_leader'])}；")

    return "\n".join(lines)


def _render_change_stage(result: dict) -> str:
    """渲染「四、【变更与操作合规】」段落（第四段）。

    规则：
      - D1【更新列内容提醒】：**不比对上一版本** ——「更新列内容」非空且不含「YC已更新」
        → 「@原潮：需求（第…行）申请变更列内容，请尽快更新！」（区块标题「■ 异常提醒」）
      - D2【不合规操作通报】：仍比对上一版本 ——「评估开发完成时间」较上一版本变化，
        且「更新列内容」为空/不含「YC已更新」
        → 「@（技术对接人，无则原潮）：需求（第…行）请勿直接修改开发完成时间！」
        （区块标题「🔴 异常通报」）
      - **无异常 → 整段不显示**（返回空串，不输出标题也不输出小红花）——
        与一/二/三段不同：第四段只在有异常时才出现。
    """
    chg_update = result.get("chg_update") or {}
    chg_invalid = result.get("chg_invalid") or {}
    has_any = bool(chg_update or chg_invalid)

    if not has_any:
        # 第四段无异常 → 整段省略（不输出标题、不输出小红花）
        return ""

    lines = ["四、【变更与操作合规】"]

    # D1 区块：更新列内容提醒（标题「■ 异常提醒」）
    if chg_update:
        lines.append(CHG_UPDATE_BLOCK_TITLE)
        for a, rows in chg_update.items():
            lines.append(f"@{a}：需求{_rows_suffix(rows)}{UPDATE_CHANGE_MSG}")

    # D2 区块：不合规操作通报（标题「🔴 异常通报」）
    if chg_invalid:
        lines.append(CHG_INVALID_BLOCK_TITLE)
        for a, rows in chg_invalid.items():
            lines.append(f"@{a}：需求{_rows_suffix(rows)}{INVALID_MODIFY_MSG}")

    return "\n".join(lines)


def render_message(result: dict, table_url: str) -> str | None:
    """按约定模板渲染群消息文本（三段式）。

    模板结构（有异常时，三段明细）：
        【业务需求技术对接表跟进异常提醒】
        在线表格：…
        对接清单：共 N 条需求
        检查时间：…

        一、【需求收集阶段】异常通报
        （有异常→@+异常结果+检查规则；无异常→小红花）

        二、【技术评估/开发阶段】异常通报
        （有异常→异常结果；无异常→小红花）

        三、【验收上线阶段】异常通报
        （验收结果清单 + 异常结果）

        注意：请尽快完善并跟进处理各自的需求任务～

    三段全无异常时（简化版，不再展开三段）：
        【业务需求技术对接表跟进异常提醒】
        在线表格：…
        对接清单：共 N 条需求
        检查时间：…

        各项开发项进度无异常，奖励每人一朵小红花🌹
        （空行结尾，不输出三段与小标题）

    第四段（变更与操作合规）的显示规则（与其他段不同）：
        **只有存在异常时才显示**；无异常则整段省略（不输出标题、也不输出小红花）。
        即：一/二/三段无异常时显示各自小红花；第四段无异常时直接不出现。
        若四段全无异常，则整条消息走「简化版」（见上）。
    """
    header = "\n".join([
        "【业务需求技术对接表跟进异常提醒】",
        f"在线表格：{table_url}",
        f"对接清单：共 {result['total']} 条需求",
        f"检查时间：{result['check_time']}",
    ])

    # 判定三段是否全无异常
    has_collect = bool(result["owner_map"] or result["no_owner_rows"])
    has_tech = any([
        result["tech_missing_tech"], result["tech_no_eval"], result["tech_bad_eval"],
        result["tech_no_done"], result["tech_overdue"], result["tech_reject"],
    ])
    has_acc = any([
        result["acc_wait_accept"], result["acc_confirm_online"], result["acc_no_note"],
        result["acc_redo"], result["acc_undecided"], result["acc_leader"],
    ])
    has_chg = any([
        result.get("chg_update"), result.get("chg_invalid"),
    ])

    # 四段全无异常 → 简化版：仅表头 + 小红花一句 + 空行结尾
    if not (has_collect or has_tech or has_acc or has_chg):
        return header + "\n\n" + FLOWER_NOTE_ACCEPT + "\n"

    seg1 = _render_collect(result)
    seg2 = _render_tech_stage(result)
    seg3 = _render_accept_stage(result)
    seg4 = _render_change_stage(result)   # 无异常时返回空串

    def _trim(seg: str) -> str:
        # 去掉段首尾多余空行，避免与段间分隔叠加成多个空行
        return seg.strip("\n")

    # 第四段只在有异常时出现：无异常（空串）则不参与拼接，
    # 避免多出一个空行/分隔符，也保证四段全清时不会出现空标题。
    parts = [header, _trim(seg1), _trim(seg2), _trim(seg3)]
    if _trim(seg4):
        parts.append(_trim(seg4))
    parts.append(FOOTER_NOTE)
    return "\n\n".join(parts)


# ── 推送 ────────────────────────────────────────────────────
def _post_once(webhook: str, content: str, timeout: int = 30) -> dict:
    """单次推送尝试。"""
    body = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw}
    if not parsed.get("success", parsed.get("errorCode") == 0):
        # 业务级失败（如 token 失效）——重试也没用，直接抛出让上层决定
        raise SendFailed(f"云之家推送失败：{raw[:300]}")
    return parsed


class SendFailed(RuntimeError):
    """云之家推送失败（业务级，重试无意义）。"""


@contextlib.contextmanager
def _send_lock(lock_file: str):
    """跨进程互斥，避免并发运行抢跑导致重复推送（LOCK_NB 抢不到就直接跳过）。"""
    import fcntl

    os.makedirs(os.path.dirname(lock_file) or ".", exist_ok=True)
    fd = os.open(lock_file + ".pid", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def send_to_yzj(webhook: str, content: str, timeout: int = 30,
                retries: int = SEND_RETRIES) -> tuple[dict, list[str]]:
    """带重试退避的推送。返回 (响应, 告警列表)。

    网络类错误（超时、连接失败）会重试；业务级失败（token 失效等）不重试。
    全部失败时返回 (None, 告警)，**不抛异常**，避免任务因推送失败而整体崩溃。
    """
    warnings: list[str] = []
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            return _post_once(webhook, content, timeout), warnings
        except SendFailed as exc:
            # 业务级失败：重试无意义
            warnings.append(f"推送被拒（不重试）：{exc}")
            return None, warnings
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                wait = SEND_BACKOFF * attempt
                print(f"⚠️ 第 {attempt} 次推送失败（{last_err}），{wait}s 后重试…", file=sys.stderr)
                time.sleep(wait)
    warnings.append(f"推送失败（已重试 {retries} 次）：{last_err}")
    return None, warnings


# ── 主流程 ──────────────────────────────────────────────────
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="业务组技术对接表填写完整性校验与异常提醒",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--table-url", default=os.getenv("KDOCS_TABLE_URL", DEFAULT_TABLE_URL),
                        help="在线表格链接")
    parser.add_argument("--webhook", default=os.getenv("YZJ_WEBHOOK", ""),
                        help="云之家群机器人 Webhook；为空则只校验不推送")
    parser.add_argument("--file-id", default=os.getenv("KDOCS_FILE_ID"),
                        help="直接指定 file_id，跳过链接解析")
    parser.add_argument("--sheet-id", type=int,
                        default=int(os.getenv("KDOCS_SHEET_ID", DEFAULT_SHEET_ID)),
                        help=f"工作表 id（默认 {DEFAULT_SHEET_ID} = {DEFAULT_SHEET_NAME}）")
    parser.add_argument("--from-json", help="离线模式：从已保存的 range-data JSON 读取")
    parser.add_argument("--no-fast-path", action="store_true",
                        help="禁用快速通道，强制走「解析链接 → 查工作表 → 拉数」完整链路")
    parser.add_argument("--force", action="store_true",
                        help="忽略当日去重锁，强制推送（用于人工重发）")
    parser.add_argument("--lock-file", default=LOCK_FILE,
                        help=f"去重锁文件路径（默认 {LOCK_FILE}）")
    parser.add_argument("--snapshot-file", default=SNAPSHOT_FILE,
                        help=f"版本快照文件路径（第四段比对基准，默认 {SNAPSHOT_FILE}）")
    parser.add_argument("--dry-run", action="store_true", help="只校验不推送")
    parser.add_argument("--save-json", help="把本次拉取的 range-data 存到该路径，便于回放")
    args = parser.parse_args(argv)

    # 1) 取数
    if args.from_json:
        payload = json.load(open(args.from_json, encoding="utf-8"))
        cells = payload.get("detail", {}).get("rangeData", payload.get("rangeData", []))
    else:
        # 快速通道优先：显式 --file-id / 环境变量 → 内置 DEFAULT_FILE_ID
        quick_file_id = args.file_id or os.getenv("KDOCS_FILE_ID") or DEFAULT_FILE_ID
        if args.no_fast_path:
            quick_file_id = None
        cells, _ = fetch_with_fallback(
            args.table_url, args.sheet_id, quick_file_id, DEFAULT_SHEET_NAME
        )
        if args.save_json:
            json.dump({"detail": {"rangeData": cells}},
                      open(args.save_json, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)

    if not cells:
        print("❌ 未读取到任何单元格数据，请检查表格链接、权限或网络。", file=sys.stderr)
        return 2

    # 1.5) 按「表头名称」定位各列 —— 任一必需列名找不到必须硬失败，绝不静默错位。
    try:
        cols = resolve_columns(cells)
    except HeaderMismatch as exc:
        print(f"❌ 列定位失败：{exc}", file=sys.stderr)
        print("   本次不做任何校验与推送。请人工确认表格列名后再运行。", file=sys.stderr)
        return 4
    print("列定位（按表头名称）：" + "、".join(
        f"{FIELD_HEADERS[k]}={chr(ord('A') + cols[k])}列" for k in FIELD_HEADERS if k in cols
    ))

    # 2) 校验
    prev_snapshot = load_snapshot(args.snapshot_file)
    result = check_rows(cells, cols, prev_snapshot=prev_snapshot)
    if result.get("chg_compare_enabled"):
        print("版本比对：已加载上一版本快照，第四段【变更与操作合规】的 D2 已启用。")
    else:
        print("版本比对：无上一版本快照（首次运行）或「更新列内容」列缺失，第四段 D2 跳过（D1 不受影响）。")
    has_biz_issue = bool(result["owner_map"] or result["no_owner_rows"])
    has_tech_issue = any([
        result["tech_missing_tech"], result["tech_no_eval"], result["tech_bad_eval"],
        result["tech_no_done"], result["tech_overdue"], result["tech_reject"],
    ])
    has_acc_issue = any([
        result["acc_wait_accept"], result["acc_confirm_online"], result["acc_no_note"],
        result["acc_redo"], result["acc_undecided"], result["acc_leader"],
    ])
    has_chg_issue = any([result.get("chg_update"), result.get("chg_invalid")])
    print(f"有效需求条数：{result['total']}")
    print("── 一、需求收集阶段（业务组）──")
    print(f"异常行数：{len(result['abnormal'])}")
    if result["owner_map"]:
        print("异常负责人：" + "、".join(f"{k}({len(v)}行)" for k, v in result["owner_map"].items()))
    if result["no_owner_rows"]:
        print("无负责人异常行：" + "、".join(f"第{r}行" for r in result["no_owner_rows"]))
    print("── 二、技术评估/开发阶段（技术组）──")
    print(f"未设技术对接人：{len(result['tech_missing_tech'])} 行")
    print(f"未反馈评估结果：{sum(len(v) for v in result['tech_no_eval'].values())} 行")
    print(f"评估结果填错：{sum(len(v) for v in result['tech_bad_eval'].values())} 行")
    print(f"缺评估完成时间：{sum(len(v) for v in result['tech_no_done'].values())} 行")
    print(f"已逾期：{len(result['tech_overdue'])} 行")
    print(f"评审不通过：{sum(len(v) for v in result['tech_reject'].values())} 行")
    print("── 三、验收上线阶段（业务开发清单验收）──")
    s = result["acc_stats"]
    print(f"验收结果清单：总计 {s['total']} 条，已通过 {s['pass']}，验收中 {s['pending']}，不通过 {s['fail']}")
    print(f"规则1 待验收：{sum(len(v) for v in result['acc_wait_accept'].values())} 行")
    print(f"规则2 待确认上线/闭环：{sum(len(v) for v in result['acc_confirm_online'].values())} 行")
    print(f"规则3 缺验收说明：{sum(len(v) for v in result['acc_no_note'].values())} 行")
    print(f"规则4 验收不通过待优化：{sum(len(v) for v in result['acc_redo'].values())} 行")
    print(f"规则5 待确认需求方案：{sum(len(v) for v in result['acc_undecided'].values())} 行")
    print(f"规则6 需领导决策：{len(result['acc_leader'])} 行")
    print("── 四、变更与操作合规（第四段）──")
    print(f"D1 变更列内容提醒（不比对快照）：{sum(len(v) for v in result.get('chg_update', {}).values())} 行")
    print(f"D2 不合规修改开发完成时间（比对快照）：{sum(len(v) for v in result.get('chg_invalid', {}).values())} 行")

    # 3) 渲染（四段式；四段均无异常时仍推送，走「简化版」仅表头 + 小红花）
    message = render_message(result, args.table_url)

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60)
    print("\n[模式] " + " | ".join(
        [x for x, ok in (
            ("一、需求收集阶段异常", has_biz_issue),
            ("二、技术评估/开发阶段异常", has_tech_issue),
            ("三、验收上线阶段异常", has_acc_issue),
            ("四、变更与操作合规异常", has_chg_issue),
        ) if ok] or ["四段均无异常（简化版：仅表头 + 小红花）"]
    ))

    # 3.5) 回写版本快照（「知识库」更新为本次最新版本），供下一轮比对。
    #      无论是否推送、是否 dry-run 都回写，保证基准持续推进。
    save_snapshot(result.get("cur_snapshot") or {}, args.snapshot_file)
    if result.get("cur_snapshot"):
        print(f"   已回写版本快照：{args.snapshot_file}（下一轮以此为基准）")

    # 4) 推送（含「当日只推一次」去重保护）
    if args.dry_run or not args.webhook:
        if not args.webhook and not args.dry_run:
            print("\n⚠️ 未提供 --webhook，已跳过推送。")
        else:
            print("\n[DRY-RUN] 已跳过推送。")
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    lock_file = args.lock_file

    with _send_lock(lock_file) as acquired:
        if not acquired:
            print(f"\n⏭️  已有另一次巡检正在推送（锁 {lock_file}.pid 被占用），本次跳过。")
            return 0

        if not args.force:
            sent, at = already_sent_today(today, lock_file)
            if sent:
                print(f"\n⏭️  今日（{today}）已于 {at} 推送过，跳过本次推送，避免重复打扰。")
                print("   如需强制重发，加 --force。")
                return 0

        # 先占坑：写入当日锁再推送。
        # 宁可「推失败但锁住了」（可人工 --force 补发），也不要「推成功了却没锁住」
        # —— 后者在任务重试时会重复打扰群里所有人。
        mark_sent_today(today, datetime.now().strftime("%Y-%m-%d %H:%M"), "", lock_file)

        resp, warnings = send_to_yzj(args.webhook, message)
        if resp is None:
            for w in warnings:
                print(f"❌ {w}", file=sys.stderr)
            print("   已保留当日锁，如需人工补发请加 --force。", file=sys.stderr)
            return 3

        msg_id = resp.get("data", {}).get("msgId", "")
        mark_sent_today(today, datetime.now().strftime("%Y-%m-%d %H:%M"), msg_id, lock_file)
        print(f"\n✅ 已推送到群：msgId={msg_id}")
        print(f"   已记录去重锁：{lock_file}（今日不再重复推送）")
        return 0


if __name__ == "__main__":
    sys.exit(main())
