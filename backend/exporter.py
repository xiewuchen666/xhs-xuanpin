from __future__ import annotations

import csv
from datetime import datetime
from io import BytesIO, StringIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


PRODUCT_COLUMNS = [
    ("title", "商品标题"),
    ("shop_name", "店铺名称"),
    ("url", "商品链接"),
    ("price", "当前价"),
    ("total_sales", "累计销量"),
    ("today", "今日新增"),
    ("rolling24", "近24小时新增"),
    ("rolling24_basis", "近24小时统计口径"),
    ("increment", "最近区间新增"),
    ("interval_hours", "最近区间时长（小时）"),
    ("updated_at", "最近更新时间"),
    ("status", "状态"),
]

SHOP_COLUMNS = [
    ("shop_name", "店铺名称"),
    ("shop_id", "店铺ID"),
    ("rating", "店铺评分"),
    ("brand_name", "品牌/账号"),
    ("brand_fans_count", "粉丝数"),
    ("brand_notes_count", "发布笔记数"),
    ("product_count", "监控商品数"),
    ("shop_today", "店铺今日新增汇总"),
    ("shop_today_coverage", "今日新增有效覆盖"),
    ("shop_rolling24", "店铺近24小时新增汇总"),
    ("shop_rolling24_coverage", "近24小时有效覆盖"),
    ("product_title", "商品标题"),
    ("product_url", "商品链接"),
    ("price", "当前价"),
    ("total_sales", "累计销量"),
    ("today", "今日新增"),
    ("rolling24", "近24小时新增"),
    ("rolling24_basis", "近24小时统计口径"),
    ("increment", "最近区间新增"),
    ("interval_hours", "最近区间时长（小时）"),
    ("updated_at", "最近更新时间"),
    ("product_status", "商品状态"),
]

MODULE_LABELS = {
    "single": "单品监控",
    "selection": "选品中心",
    "shops": "店铺监控",
}


def _columns(module: str) -> list[tuple[str, str]]:
    if module in {"single", "selection"}:
        return PRODUCT_COLUMNS
    if module == "shops":
        return SHOP_COLUMNS
    raise ValueError("无效导出模块")


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _normalized_rows(module: str, rows: Any) -> tuple[list[tuple[str, str]], list[list[Any]]]:
    columns = _columns(module)
    if not isinstance(rows, list):
        raise ValueError("导出数据格式错误")
    if len(rows) > 20000:
        raise ValueError("单次最多导出 20000 行")
    normalized: list[list[Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("导出数据格式错误")
        normalized.append([_safe_cell(item.get(key)) for key, _ in columns])
    return columns, normalized


def _filename(module: str, extension: str) -> str:
    label = MODULE_LABELS[module]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{label}-{stamp}.{extension}"


def build_csv(module: str, rows: Any) -> tuple[bytes, str, str]:
    columns, normalized = _normalized_rows(module, rows)
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([label for _, label in columns])
    writer.writerows(normalized)
    # UTF-8 BOM makes Chinese open correctly in Windows Excel without import steps.
    data = ("\ufeff" + output.getvalue()).encode("utf-8")
    return data, "text/csv; charset=utf-8", _filename(module, "csv")


def build_xlsx(module: str, rows: Any) -> tuple[bytes, str, str]:
    columns, normalized = _normalized_rows(module, rows)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = MODULE_LABELS[module]

    headers = [label for _, label in columns]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in normalized:
        sheet.append(row)

    sheet.freeze_panes = "A2"
    if sheet.max_row >= 1 and sheet.max_column >= 1:
        sheet.auto_filter.ref = sheet.dimensions

    for index, (_, label) in enumerate(columns, start=1):
        values = [label]
        for row in normalized[:500]:
            value = row[index - 1]
            if value not in (None, ""):
                values.append(str(value))
        width = min(max(max((len(v) for v in values), default=len(label)) + 2, 10), 42)
        sheet.column_dimensions[get_column_letter(index)].width = width

    key_to_index = {key: idx for idx, (key, _) in enumerate(columns, start=1)}
    for key in ("price",):
        idx = key_to_index.get(key)
        if idx:
            for cell in sheet[get_column_letter(idx)][1:]:
                cell.number_format = "0.00"
    for key in ("interval_hours",):
        idx = key_to_index.get(key)
        if idx:
            for cell in sheet[get_column_letter(idx)][1:]:
                cell.number_format = "0.0"

    output = BytesIO()
    workbook.save(output)
    return (
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _filename(module, "xlsx"),
    )


def build_export(module: str, fmt: str, rows: Any) -> tuple[bytes, str, str]:
    if fmt == "csv":
        return build_csv(module, rows)
    if fmt == "xlsx":
        return build_xlsx(module, rows)
    raise ValueError("导出格式仅支持 csv 或 xlsx")
