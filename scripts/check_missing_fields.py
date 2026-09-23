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
import json
import os
import re
import subprocess
import sys
import tempfile
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

# 扫描的最大行数（表格实际数据到第 127 行附近，留足余量）
MAX_SCAN_ROW = 3000
MAX_SCAN_COL = 9      # 0-based，即到 J 列

_BLANK_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff", "\xa0", "\u3000", "\r", "\n", "\t")


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


def run_kdocs(args: list[str], timeout: int = 120) -> str:
    """调用 kdocs-cli 并返回 stdout。"""
    try:
        proc = subprocess.run(
            ["kdocs-cli", *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "未找到 kdocs-cli。请先安装：bash scripts/setup.sh（金山文档 Skill 内置脚本），"
            "或确认 PATH 已包含安装目录（默认 ~/.local/bin）。"
        )
    if proc.returncode != 0:
        raise RuntimeError(f"kdocs-cli 执行失败（exit {proc.returncode}）：{proc.stderr.strip()[:500]}")
    return proc.stdout


def parse_first_json(text: str) -> dict:
    """kdocs-cli 的 JSON 输出后可能追加升级提示，用 raw_decode 只取第一个对象。"""
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"未在输出中找到 JSON：{text[:300]}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


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
    返回 (cells, file_id)。
    """
    if file_id:
        try:
            cells = fetch_all(file_id, sheet_id)
            if cells:
                return cells, file_id
            print("⚠️ 快速通道返回空数据，回退到完整链路…", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - 任何异常都回退，保证任务不中断
            print(f"⚠️ 快速通道失败（{exc}），回退到完整链路…", file=sys.stderr)

    resolved_id = resolve_file_id(table_url)
    real_sheet_id = find_sheet_id(resolved_id, sheet_name, None)
    return fetch_all(resolved_id, real_sheet_id), resolved_id


# ── 核心校验 ────────────────────────────────────────────────
def check_rows(cells, now: datetime | None = None) -> dict:
    """逐行校验，返回结构化结果。"""
    now = now or datetime.now()
    grid = build_grid(cells)

    data_rows = sorted(r for r in grid if r >= DATA_START_INDEX)

    total = 0
    abnormal = []          # [(excel_row, owner, missing_fields)]
    for row_idx in data_rows:
        row = grid.get(row_idx, {})
        # 整行（A~J）全空 → 非需求行，跳过且不计入总数
        if all(norm(row.get(c, "")) == "" for c in range(MAX_SCAN_COL + 1)):
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
    """按约定模板渲染群消息文本；无异常返回 None（不发送）。"""
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

    # 逐行艾特所有有异常的需求负责人
    at_line = " ".join(f"@{name}" for name in owner_map)
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
def send_to_yzj(webhook: str, content: str, timeout: int = 30) -> dict:
    """推送文本到云之家群机器人。"""
    import urllib.request

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
        raise RuntimeError(f"云之家推送失败：{raw[:300]}")
    return parsed


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

    # 2) 校验
    result = check_rows(cells)
    print(f"有效需求条数：{result['total']}")
    print(f"异常行数：{len(result['abnormal'])}")
    if result["owner_map"]:
        print("异常负责人：" + "、".join(f"{k}({len(v)}行)" for k, v in result["owner_map"].items()))
    if result["no_owner_rows"]:
        print("无负责人异常行：" + "、".join(f"第{r}行" for r in result["no_owner_rows"]))

    # 3) 渲染
    message = render_message(result, args.table_url)
    if message is None:
        print("\n✅ 全部填写完整，无异常，不发送消息。")
        return 0

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60)

    # 4) 推送
    if args.dry_run or not args.webhook:
        if not args.webhook and not args.dry_run:
            print("\n⚠️ 未提供 --webhook，已跳过推送。")
        else:
            print("\n[DRY-RUN] 已跳过推送。")
        return 0

    resp = send_to_yzj(args.webhook, message)
    print(f"\n✅ 已推送到群：msgId={resp.get('data', {}).get('msgId')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
