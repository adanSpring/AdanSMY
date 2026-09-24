#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务组技术对接表 —— 需求填写完整性校验

用途
----
读取金山文档在线表格「集团信息化 业务技术项目对接表」的「项目对接清单」工作表，
逐行检查需求填写完整性，汇总异常结果，并推送提醒到云之家群机器人。

校验规则
--------
1. 必填项：系统名称、所属系统/模块、提出分公司、需求提出人、需求负责人、需求优先级、提出日期
2. 至少填一项：业务背景与痛点、需求描述与业务价值
逐行检查，不满足任一条即为异常。

汇总规则
--------
- 异常行若「需求负责人」有值 → 按负责人汇总，输出「负责人：N行需求填写不完整；」，同一负责人只出现一次
- 异常行若「需求负责人」为空 → 按行号单独输出「第N行：1行需求填写不完整；」，不连续行不合并
- 无异常 → 不发送任何消息

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

# 列定义（0-based，对应 A~J）
COL_SYSTEM = 0        # A 系统名称
COL_MODULE = 1        # B 所属系统/模块
COL_BRANCH = 2        # C 提出分公司
COL_PROPOSER = 3      # D 需求提出人
COL_OWNER = 4         # E 需求负责人
COL_DATE = 5          # F 提出日期
COL_BG = 6            # G 业务背景与痛点
COL_DESC = 7          # H 需求描述与业务价值
COL_PRIORITY = 8      # I 需求优先级  （注意：表头在第 2 行 I 列）

# 必填项：表头文案 → 列号
REQUIRED_FIELDS = {
    "系统名称": COL_SYSTEM,
    "所属系统/模块": COL_MODULE,
    "提出分公司": COL_BRANCH,
    "需求提出人": COL_PROPOSER,
    "需求负责人": COL_OWNER,
    "需求优先级": COL_PRIORITY,
    "提出日期": COL_DATE,
}

# 至少填一项的字段
ANY_OF_FIELDS = ["业务背景与痛点", "需求描述与业务价值"]
ANY_OF_COLS = (COL_BG, COL_DESC)

# 表头与数据起始（0-based）：第 1 行分组标题，第 2 行表头，第 3 行起为数据
HEADER_ROW_INDEX = 1
DATA_START_INDEX = 2

# ── 表头校验：列号 → 期望表头文案 ──────────────────────────
# 每次运行都会核对，防止有人在表格里插入/移动列导致校验错位却静默发出错误结果。
EXPECTED_HEADERS = {
    COL_SYSTEM: "系统名称",
    COL_MODULE: "所属系统/模块",
    COL_BRANCH: "提出分公司",
    COL_PROPOSER: "需求提出人",
    COL_OWNER: "需求负责人",
    COL_DATE: "提出日期",
    COL_BG: "业务背景与痛点",
    COL_DESC: "需求描述与业务价值",
    COL_PRIORITY: "需求优先级",
}

# 扫描范围
MAX_SCAN_ROW = 3000       # 兜底上限（正常会被动态探测的行数覆盖）
MAX_SCAN_COL = 9          # 0-based，即到 J 列
PROBE_ROWS = 20           # 探测实际行数时读取的行数窗口

# 推送重试
SEND_RETRIES = 3
SEND_BACKOFF = 3          # 秒；退避 3s → 6s → 9s

_BLANK_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff", "\xa0", "\u3000", "\r", "\n", "\t")

# 无异常通报用的花 —— 用 unicode 转义写死，避免不同编辑器/编码环节把字符弄丢
FLOWER = "\U0001F339"     # 🌹

# 无需求负责人的异常行：消息开头额外艾特的跟进人（2026-09-24 新增规则）
NO_OWNER_AT = "原潮"


# ── 工具函数 ────────────────────────────────────────────────
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
    """表头与预期不符 —— 说明表格结构变了，必须人工介入，绝不能继续校验。"""


def verify_headers(cells) -> list[str]:
    """核对表头文案，返回问题列表（空列表表示通过）。

    若有人在表格里插入/移动/重命名列，列索引会整体错位。此时若继续按固定
    列号校验，会把「技术对接人」当成「需求负责人」，静默产出**错误**的异常
    名单 —— 比任务直接失败更危险。因此这里做强制拦截。
    """
    grid = build_grid(cells)
    header_row = grid.get(HEADER_ROW_INDEX, {})
    if not header_row:
        raise HeaderMismatch(
            f"第 {HEADER_ROW_INDEX + 1} 行未读到表头，表格结构可能已变更。"
        )

    problems = []
    for col, expected in sorted(EXPECTED_HEADERS.items()):
        actual = norm(header_row.get(col, ""))
        if actual != expected:
            col_letter = chr(ord("A") + col)
            problems.append(
                f"{col_letter} 列：期望「{expected}」，实际「{actual or '（空）'}」"
            )
    return problems


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
def check_rows(cells, now: datetime | None = None) -> dict:
    """逐行校验，返回结构化结果。"""
    now = now or datetime.now()
    grid = build_grid(cells)

    data_rows = sorted(r for r in grid if r >= DATA_START_INDEX)

    total = 0
    abnormal = []          # [(excel_row, owner, missing_fields)]
    label = str(now.year - 1)
    for row_idx in data_rows:
        row = grid.get(row_idx, {})
        # 整行（A~J）全空 → 非需求行，跳过且不计入总数
        if all(norm(row.get(c, "")) == "" for c in range(MAX_SCAN_COL + 1)):
            continue
        # 上一自然年的数据属于历史归档，不再催办
        if label in str(row.get(COL_DATE, "")):
            continue
        total += 1

        missing = []
        for label, col in REQUIRED_FIELDS.items():
            if norm(row.get(col, "")) == "":
                missing.append(label)
        if all(norm(row.get(c, "")) == "" for c in ANY_OF_COLS):
            missing.append("／".join(ANY_OF_FIELDS) + "（至少填一项）")

        if missing:
            excel_row = row_idx + 1        # 0-based → Excel 真实行号
            owner = norm(row.get(COL_OWNER, ""))
            abnormal.append((excel_row, owner, missing))

    # 汇总：有负责人 → 按负责人归并；无负责人 → 按行号单独列出
    owner_map: dict[str, list[int]] = {}
    no_owner_rows: list[int] = []
    for excel_row, owner, _ in abnormal:
        if owner:
            owner_map.setdefault(owner, []).append(excel_row)
        else:
            no_owner_rows.append(excel_row)

    return {
        "total": total,
        "abnormal": abnormal,
        "owner_map": owner_map,
        "no_owner_rows": sorted(no_owner_rows),
        "check_time": now.strftime("%Y-%m-%d %H:%M"),
    }


def render_message(result: dict, table_url: str) -> str | None:
    """按约定模板渲染群消息文本。

    - 有异常 → 渲染「异常提醒」模板
    - 无异常 → 渲染「表现优异」模板（每日必发一条，用于确认巡检确实跑过）
    """
    owner_map = result["owner_map"]
    no_owner_rows = result["no_owner_rows"]

    if not owner_map and not no_owner_rows:
        # 无异常：发一条「小红花」通报。
        # 好处是每天必有一条消息 —— 群里看不到消息就知道任务挂了，而不是「今天刚好没问题」。
        return "\n".join([
            "【业务组技术对接表填写异常提醒】",
            f"在线表格：{table_url}",
            f"对接清单：共 {result['total']} 条需求",
            f"检查时间：{result['check_time']}",
            "",
            f"业务组表现优异，今日无异常，奖励一朵小红花{FLOWER}",
        ])

    lines = [
        "【业务组技术对接表填写异常提醒】",
        f"在线表格：{table_url}",
        f"对接清单：共 {result['total']} 条需求",
        f"检查时间：{result['check_time']}",
        "",
    ]

    # 逐行艾特所有有异常的需求负责人；
    # 若存在「无需求负责人」的异常行，额外艾特 NO_OWNER_AT（原潮）跟进
    at_names = list(owner_map)
    if no_owner_rows and NO_OWNER_AT not in owner_map:
        at_names.append(NO_OWNER_AT)
    at_line = " ".join(f"@{name}" for name in at_names)
    if at_line:
        lines.append(at_line)

    lines.append("■ 异常结果")
    # 有负责人：同一负责人汇总为一行
    for name, rows in owner_map.items():
        lines.append(f"{name}：{len(rows)}行需求填写不完整；")
    # 无负责人：按行号逐行列出，不合并
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

    # 1.5) 表头校验 —— 表格结构漂移必须硬失败，绝不带着错误列映射继续跑。
    try:
        header_problems = verify_headers(cells)
    except HeaderMismatch as exc:
        print(f"❌ 表头校验失败：{exc}", file=sys.stderr)
        print("   请人工确认表格列结构后再运行（本次不做任何校验与推送）。", file=sys.stderr)
        return 4
    if header_problems:
        print("❌ 表头与预期不符，已中止（防止按错误列号产出错误名单）：", file=sys.stderr)
        for p in header_problems:
            print(f"   - {p}", file=sys.stderr)
        print("   若确为表格改版，请更新脚本中的 EXPECTED_HEADERS / 列定义后重跑。",
              file=sys.stderr)
        return 4

    # 2) 校验
    result = check_rows(cells)
    has_issue = bool(result["owner_map"] or result["no_owner_rows"])
    print(f"有效需求条数：{result['total']}")
    print(f"异常行数：{len(result['abnormal'])}")
    if result["owner_map"]:
        print("异常负责人：" + "、".join(f"{k}({len(v)}行)" for k, v in result["owner_map"].items()))
    if result["no_owner_rows"]:
        print("无负责人异常行：" + "、".join(f"第{r}行" for r in result["no_owner_rows"]))

    # 3) 渲染（有异常 → 异常提醒；无异常 → 小红花通报。两种情况都要发）
    message = render_message(result, args.table_url)
    if message is None:
        # 只有 total=0 这类极端情况才会走到这里：没读到任何需求行，不发消息
        print("\n⚠️ 未统计到任何需求行，不发送消息。")
        return 0

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60)
    print("\n[模式] " + ("异常提醒" if has_issue else "无异常通报（小红花）"))

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
