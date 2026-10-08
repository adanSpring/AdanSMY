#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务需求技术对接表日常跟进通报 —— 业务组 + 技术组 双模块校验

用途
----
读取金山文档在线表格「集团信息化 业务技术项目对接表」的「项目对接清单」工作表，
一次取数，同时执行【业务组填写完整性】与【技术组填报异常】两套校验，
合并成一条消息推送提醒到云之家群机器人；两段均无异常则整条不推送。

模块 A：业务组填写完整性
------------------------
1. 必填项：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期
2. 至少填一项：业务背景与痛点、需求描述与业务价值
逐行检查，不满足任一条即为异常。
- 异常行若「需求负责人」有值 → 按负责人汇总，输出「负责人：N行需求填写不完整；」，同一负责人只出现一次
- 异常行若「需求负责人」为空 → 按行号单独输出「第N行：1行需求填写不完整；」，不连续行不合并

模块 B：技术组填报异常（5 条规则）
----------------------------------
涉及列（全部按「表头名称」定位，见下方「列定位」说明）：
    技术对接人、评估结果/排期结论、评估开发完成时间、逾期状态、技术组测试结果、技术组说明备注
1. 技术对接人：必须有人名，无人名 → 「@敦志勇  共x条需求，仍未设定技术对接人；」
2. 评估结果/排期结论：仅支持「评估通过 / 评估不通过」；未填/填错 → 异常
   2.1 未填 且 技术对接人有值 且 (now - 提出日期 >= 24h) → 「@（技术对接人）  有x条需求，仍未反馈技术开发评估结果；」
   2.2 未填 且 技术对接人有值 且 (now - 提出日期 < 24h)  → 不抛异常
   2.3 填错 且 技术对接人有值 → 「@（技术对接人）  第x条需求，请按表格格式填写；」
   2.4 技术对接人无值的行 → 跳过
3. 评估开发完成时间：若 评估结果/排期结论 有值则必填，缺 → 「@（技术对接人）  有x条需求，仍未评估完成时间；」
4. 逾期状态：若 评估开发完成时间 有值 且 技术组测试结果 ≠ 通过，筛选 逾期状态 有值或为「是」的行
   → 「@敦志勇 @逄浩 🔴有x条需求，已逾期；」
5. 技术组说明备注：若 评估结果/排期结论 = 评估不通过 → 「@（技术对接人）  有x条评审不通过的需求，请明确备注说明；」
- 有技术对接人 → 统一汇总，同一人只显示一次

无异常 → 不发送任何消息

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

# ── 默认配置 ────────────────────────────────
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
}

# 模块A 必填项（内部键）
REQUIRED_FIELD_KEYS = ["system", "module", "branch", "proposer", "owner", "priority", "date"]

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

# 逾期状态「有值/为是」的判定值
OVERDUE_TRUE_VALUES = {"是", "有", "逾期", "true", "True", "TRUE", "Y", "是（逾期）"}

# 规则2.1 的时间阈值：提出日期距现在 >= 24h 才催评估结果
EVAL_REMIND_HOURS = 24

# 无需求负责人的异常行：消息开头额外艾特的跟进人（2026-09-24 新增规则）
NO_OWNER_AT = "原潮"


# ── 工具函数 ────────────────────────────────
def norm(value) -> str:
    """归一化单元格值：None、空白、零宽字符、全角空格统一视为空字符串。"""
    if value is None:
        return ""
    text = str(value)
    for ch in _BLANK_CHARS:
        text = text.replace(ch, "")
    return text.strip()


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


# ── 当日去重锁 ──────────────────────────────
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


# ── 核心校验 ────────────────────────────────
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


def check_rows(cells, cols: dict, now: datetime | None = None) -> dict:
    """逐行校验业务组 + 技术组，返回结构化结果。

    cols：由 resolve_columns(cells) 得到的 {field_key: col_index} 列映射，
          全程按名称定位的列号取值。
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

        # ── 模块 A：业务组填写完整性 ──
        missing = []
        for key in REQUIRED_FIELD_KEYS:
            if norm(row.get(cols[key], "")) == "":
                missing.append(FIELD_HEADERS[key])
        if all(norm(row.get(cols[k], "")) == "" for k in ANY_OF_KEYS):
            missing.append("／".join(FIELD_HEADERS[k] for k in ANY_OF_KEYS) + "（至少填一项）")
        if missing:
            owner = norm(row.get(c_owner, ""))
            abnormal.append((excel_row, owner, missing))

        # ── 模块 B：技术组填报异常 ──
        tech = norm(row.get(c_tech, ""))
        eval_result = norm(row.get(c_eval_result, ""))
        eval_done = norm(row.get(c_eval_done, ""))
        overdue_val = norm(row.get(c_overdue, ""))
        tech_test = norm(row.get(c_tech_test, ""))
        tech_note = norm(row.get(c_tech_note, ""))
        propose_date = _parse_date(row.get(c_date, ""))

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
                # 规则3：已评估（评估通过 / 评估不通过）→ 评估完成时间必填
                if not eval_done:
                    tech_no_done.append((excel_row, tech))

            # 规则4：有评估完成时间 且 技术组测试结果不为通过 → 看逾期状态
            if eval_done and tech_test not in TECH_TEST_PASS_VALUES:
                if overdue_val and (overdue_val in OVERDUE_TRUE_VALUES or len(overdue_val) > 0):
                    tech_overdue.append(excel_row)

            # 规则5：评估结果 = 评估不通过 → 异常
            if eval_result == EVAL_RESULT_FAIL:
                tech_reject.append((excel_row, tech, tech_note))

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
    }


def _render_business(result: dict, table_url: str) -> str | None:
    """渲染模块 A（业务组）段落；无异常返回 None。"""
    owner_map = result["owner_map"]
    no_owner_rows = result["no_owner_rows"]
    if not owner_map and not no_owner_rows:
        return None

    lines = [
        "【业务组技术对接表填写异常提醒】",
        f"在线表格：{table_url}",
        f"对接清单：共 {result['total']} 条需求",
        f"检查时间：{result['check_time']}",
        "",
    ]

    at_names = list(owner_map)
    if no_owner_rows and NO_OWNER_AT not in owner_map:
        at_names.append(NO_OWNER_AT)
    at_line = " ".join(f"@{name}" for name in at_names)
    if at_line:
        lines.append(at_line)

    lines.append("■ 异常结果")
    for name, rows in owner_map.items():
        lines.append(f"{name}：{len(rows)}行需求填写不完整；")
    for excel_row in no_owner_rows:
        lines.append(f"第{excel_row}行：1行需求填写不完整；")

    lines += [
        "",
        "■ 异常检查规则",
        "必填项：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期；",
        "至少填一项：业务背景与痛点、需求描述与业务价值；",
        "",
        "注意：请尽快完善业务组需求文档的补充；",
    ]
    return "\n".join(lines)


def _render_technical(result: dict, table_url: str) -> str | None:
    """渲染模块 B（技术组）段落；无异常返回 None。"""
    has_any = any([
        result["tech_missing_tech"], result["tech_no_eval"], result["tech_bad_eval"],
        result["tech_no_done"], result["tech_overdue"], result["tech_reject"],
    ])
    if not has_any:
        return None

    lines = [
        "【技术组需求对接表填写异常提醒】",
        f"在线表格：{table_url}",
        f"对接清单：共 {result['total']} 条需求",
        f"检查时间：{result['check_time']}",
        "",
        "■ 异常结果",
    ]

    # 规则1：无技术对接人 → 艾特敦志勇
    if result["tech_missing_tech"]:
        n = len(result["tech_missing_tech"])
        lines.append(f"@{TECH_AT_NOMISS}  共{n}条需求，仍未设定技术对接人；")

    # 规则2.1：未反馈评估结果 → 按技术对接人汇总
    if result["tech_no_eval"]:
        at_line = " ".join(f"@{t}" for t in result["tech_no_eval"])
        lines.append(at_line)
        for t, rows in result["tech_no_eval"].items():
            lines.append(f"{t}：有{len(rows)}条需求，仍未反馈技术开发评估结果；")

    # 规则2.3：评估结果填错 → 按技术对接人汇总，列出具体行号
    if result["tech_bad_eval"]:
        at_line = " ".join(f"@{t}" for t in result["tech_bad_eval"])
        lines.append(at_line)
        for t, rows in result["tech_bad_eval"].items():
            row_desc = "、".join(f"第{r}条" for r in rows)
            lines.append(f"{t}：{row_desc}需求，请按表格格式填写；")

    # 规则3：缺评估完成时间 → 按技术对接人汇总
    if result["tech_no_done"]:
        at_line = " ".join(f"@{t}" for t in result["tech_no_done"])
        lines.append(at_line)
        for t, rows in result["tech_no_done"].items():
            lines.append(f"{t}：有{len(rows)}条需求，仍未评估完成时间；")

    # 规则4：逾期 → 艾特敦志勇 + 逄浩
    if result["tech_overdue"]:
        at_line = " ".join(f"@{t}" for t in TECH_AT_OVERDUE)
        lines.append(f"{at_line} {OVERDUE_DOT}有{len(result['tech_overdue'])}条需求，已逾期；")

    # 规则5：评审不通过 → 按技术对接人汇总
    if result["tech_reject"]:
        at_line = " ".join(f"@{t}" for t in result["tech_reject"])
        lines.append(at_line)
        for t, rows in result["tech_reject"].items():
            lines.append(f"{t}：有{len(rows)}条评审不通过的需求，请明确备注说明；")

    lines += [
        "以此类推",
        "",
        "注意：请技术组同事尽快完善业务需求文档的填报；",
    ]
    return "\n".join(lines)


def render_message(result: dict, table_url: str) -> str | None:
    """按约定模板渲染群消息文本（业务组 + 技术组两段）。

    - 任一段有异常 → 该段渲染；两段都无异常 → 返回 None（不推送）
    - 两段之间空一行
    """
    seg_business = _render_business(result, table_url)
    seg_technical = _render_technical(result, table_url)

    segments = [s for s in (seg_business, seg_technical) if s]
    if not segments:
        return None
    return "\n\n".join(segments)


# ── 推送 ────────────────────────────────────
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


# ── 主流程 ──────────────────────────────────
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
    result = check_rows(cells, cols)
    has_biz_issue = bool(result["owner_map"] or result["no_owner_rows"])
    has_tech_issue = any([
        result["tech_missing_tech"], result["tech_no_eval"], result["tech_bad_eval"],
        result["tech_no_done"], result["tech_overdue"], result["tech_reject"],
    ])
    print(f"有效需求条数：{result['total']}")
    print("── 模块A 业务组 ──")
    print(f"异常行数：{len(result['abnormal'])}")
    if result["owner_map"]:
        print("异常负责人：" + "、".join(f"{k}({len(v)}行)" for k, v in result["owner_map"].items()))
    if result["no_owner_rows"]:
        print("无负责人异常行：" + "、".join(f"第{r}行" for r in result["no_owner_rows"]))
    print("── 模块B 技术组 ──")
    print(f"未设技术对接人：{len(result['tech_missing_tech'])} 行")
    print(f"未反馈评估结果：{sum(len(v) for v in result['tech_no_eval'].values())} 行")
    print(f"评估结果填错：{sum(len(v) for v in result['tech_bad_eval'].values())} 行")
    print(f"缺评估完成时间：{sum(len(v) for v in result['tech_no_done'].values())} 行")
    print(f"已逾期：{len(result['tech_overdue'])} 行")
    print(f"评审不通过：{sum(len(v) for v in result['tech_reject'].values())} 行")

    # 3) 渲染（业务组 / 技术组两段；两段都无异常 → 不发）
    message = render_message(result, args.table_url)
    if message is None:
        print("\n✅ 业务组、技术组均无异常，按约定不推送任何消息。")
        return 0

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60)
    print("\n[模式] " + " + ".join(
        [x for x, ok in (("业务组异常", has_biz_issue), ("技术组异常", has_tech_issue)) if ok]
    ))

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
