"""Shared, read-only metric definitions. No network access or database writes.

Legacy timestamps are interpreted as Asia/Shanghai (+08:00). A numerical
counter reading can be exact while its day/window boundary is approximate.
"""
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional

TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
PRECISION_LABELS = {"exact": "精确读数", "lower_bound": "下限值", "approximate": "近似读数", "unknown": "口径未知"}
QUALITY_LABELS = {"exact": "精确区间", "approximate": "近似区间", "missing": "不可计算", "anomaly": "异常区间"}


def now() -> datetime:
    return datetime.now(TZ)


def timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)
    except (ValueError, TypeError):
        return None


def text_time(value: Optional[datetime] = None) -> str:
    return (value or now()).astimezone(TZ).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def normalized_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
    # Reinterpret ambiguous legacy compact strings without overwriting history.
    from collector import parse_sales
    item = dict(row)
    raw = item.get("sales_raw")
    if raw:
        parsed = parse_sales(str(raw))
        item.update(parsed)
    item["_time"] = timestamp(item.get("collected_at"))
    return item


def missing(reason: str, quality: str = "missing") -> Dict[str, Any]:
    return {"value": None, "quality": quality, "reason": reason, "from_time": None, "to_time": None, "hours": None}


def exact_counter(row: Optional[Dict[str, Any]]) -> bool:
    return bool(row and row.get("sales_precision") == "exact" and row.get("total_sales") is not None and row.get("_time"))


def interval(start: Optional[Dict[str, Any]], end: Optional[Dict[str, Any]], rows: List[Dict[str, Any]], approximate: bool = False) -> Dict[str, Any]:
    if not start or not end:
        return missing("缺少区间端点采样")
    if not exact_counter(start) or not exact_counter(end):
        return missing("端点包含近似、下限或未知销量，不能计算新增")
    a, b = start["_time"], end["_time"]
    if b < a:
        return missing("采样时间顺序异常", "anomaly")
    if a == b and start.get("id") != end.get("id"):
        return missing("同秒多条记录，无法确定有效区间", "anomaly")
    # Reject a window containing a counter decrease, even if its final delta is positive.
    ordered = [r for r in rows if r.get("_time") and a <= r["_time"] <= b]
    previous = None
    for row in ordered:
        if not exact_counter(row):
            return missing("区间内存在不确定读数，无法核实计数连续性")
        if previous is not None and int(row["total_sales"]) < int(previous["total_sales"]):
            return missing("区间内累计值回退；原因待核实", "anomaly")
        previous = row
    delta = int(end["total_sales"]) - int(start["total_sales"])
    if delta < 0:
        return missing("累计值回退；原因待核实", "anomaly")
    hours = (b - a).total_seconds() / 3600
    return {"value": delta, "quality": "approximate" if approximate else "exact", "reason": "边界附近采样，不代表精确日界/整点" if approximate else "两个精确读数之差", "from_time": text_time(a), "to_time": text_time(b), "hours": hours}


def nearest(rows: List[Dict[str, Any]], target: datetime, tolerance_minutes: int, upper: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    candidates = [r for r in rows if exact_counter(r) and (upper is None or r["_time"] <= upper) and abs((r["_time"] - target).total_seconds()) <= tolerance_minutes * 60]
    return min(candidates, key=lambda r: (abs((r["_time"] - target).total_seconds()), r["_time"], r.get("id", 0))) if candidates else None


def boundary_metric(rows: List[Dict[str, Any]], target: datetime, end: Optional[Dict[str, Any]], tolerance: int) -> Dict[str, Any]:
    base = nearest(rows, target, tolerance, end["_time"] if end else None)
    if not base:
        return missing("缺少日界附近的精确采样（容差 %s 分钟）" % tolerance)
    if not end or end["_time"] < target:
        return missing("今日尚无有效采样")
    return interval(base, end, rows, base["_time"] != target)


def window_metric(rows: List[Dict[str, Any]], start: datetime, end: datetime, tolerance: int, as_of: datetime) -> Dict[str, Any]:
    left = nearest(rows, start, tolerance, as_of)
    right = nearest(rows, end, tolerance, as_of)
    if not left or not right:
        return missing("缺少统一窗口端点（容差 %s 分钟）；不使用旧数据冒充" % tolerance)
    return interval(left, right, rows, left["_time"] != start or right["_time"] != end)


def enrich(product: Dict[str, Any], snapshots: List[Dict[str, Any]], as_of: Optional[datetime] = None, day_tolerance: int = 5, window_tolerance: int = 30, stale_minutes: int = 120) -> Dict[str, Any]:
    p = dict(product)
    current = timestamp(as_of) or now()
    rows = [normalized_snapshot(r) for r in snapshots]
    rows = sorted([r for r in rows if r["_time"] and r["_time"] <= current], key=lambda r: (r["_time"], r.get("id", 0)))
    latest = rows[-1] if rows else None
    valid_sales = [r for r in rows if r.get("total_sales") is not None and r.get("sales_precision") in {"exact", "lower_bound", "approximate"}]
    last_sales = valid_sales[-1] if valid_sales else None
    if last_sales:
        p.update({k: last_sales.get(k) for k in ("total_sales", "sales_raw", "sales_precision")})
    else:
        p.update(total_sales=None, sales_raw=latest.get("sales_raw", "") if latest else "", sales_precision="unknown")
    p["sales_observed_at"] = last_sales.get("collected_at") if last_sales else None
    p["sales_not_updated"] = bool(latest and (not last_sales or latest.get("id") != last_sales.get("id")))
    p["latest_observed_at"] = latest.get("collected_at") if latest else None
    p["latest_raw"] = latest.get("sales_raw", "") if latest else ""
    p["price_observed_at"] = next((r.get("collected_at") for r in reversed(rows) if r.get("price") is not None), None)
    p["precision_label"] = PRECISION_LABELS.get(p.get("sales_precision"), "口径未知")
    observed = timestamp(p["sales_observed_at"])
    age = (current - observed).total_seconds() / 60 if observed else None
    p["stale"] = age is None or age > stale_minutes
    p["age_minutes"] = round(age) if age is not None else None
    midnight = datetime.combine(current.date(), datetime.min.time(), tzinfo=TZ)
    today = boundary_metric(rows, midnight, latest, day_tolerance)
    y_start = nearest(rows, midnight - timedelta(days=1), day_tolerance, current)
    y_end = nearest(rows, midnight, day_tolerance, current)
    yesterday = interval(y_start, y_end, rows, bool(y_start and y_end and (y_start["_time"] != midnight-timedelta(days=1) or y_end["_time"] != midnight))) if y_start and y_end else missing("缺少昨日或今日日界附近的精确采样")
    increment = interval(rows[-2], latest, rows[-2:]) if len(rows) >= 2 else missing("至少需要两次采样")
    if latest and not exact_counter(latest):
        increment = missing("本次销量不可用于精确差分；不沿用历史增量")
    rolling = window_metric(rows, current-timedelta(hours=24), current, window_tolerance, current)
    prior = window_metric(rows, current-timedelta(hours=48), current-timedelta(hours=24), window_tolerance, current)
    growth = None
    growth_reason = "需要连续两个有效的 24 小时窗口"
    if rolling["value"] is not None and prior["value"] is not None:
        if prior["value"] > 0:
            growth = round((rolling["value"] / prior["value"] - 1) * 100, 1)
            growth_reason = "近 24h 相对前 24h；近似端点会使增幅近似"
        elif rolling["value"] > 0:
            growth_reason = "前窗为零，本窗新增动销；不显示无穷增长率"
        else:
            growth = 0.0
            growth_reason = "两个窗口均无观测新增"
    p.update(today=today, yesterday=yesterday, increment=increment, rolling24=rolling, previous24=prior, growth_percent=growth, growth_reason=growth_reason)
    p["today_sales"], p["yesterday_sales"] = today["value"], yesterday["value"]
    p["latest_increment"], p["previous_collected_at"] = increment["value"], increment["from_time"]
    p["velocity"] = round(increment["value"] / increment["hours"], 2) if increment["value"] is not None and increment["hours"] and increment["hours"] >= 5/60 else None
    p["velocity_reason"] = "实际采样区间的平均新增/小时，不是实时速度或预测" if p["velocity"] is not None else "区间不足 5 分钟或缺少有效读数"
    p["anomaly"] = any(m["quality"] == "anomaly" for m in (today, yesterday, increment, rolling, prior))
    failed = p.get("last_attempt_status") == "failed" or (p.get("last_status") not in (None, "", "正常") and not p.get("last_attempt_status"))
    if p.get("monitor_state") == "archived":
        p["health"], p["health_label"] = "muted", "已归档"
    elif p.get("monitor_state") == "paused":
        p["health"], p["health_label"] = "muted", "已暂停"
    elif failed:
        p["health"], p["health_label"] = "danger", "最近采集失败"
    elif p["anomaly"]:
        p["health"], p["health_label"] = "danger", "累计值回退"
    elif p["sales_not_updated"]:
        p["health"], p["health_label"] = "warning", "本次销量缺失"
    elif p["stale"]:
        p["health"], p["health_label"] = "warning", "数据已过期"
    elif p["sales_precision"] != "exact":
        p["health"], p["health_label"] = "warning", p["precision_label"]
    else:
        p["health"], p["health_label"] = "success", "数据已更新"
    p["viral_score"] = None  # Legacy field is intentionally retired.
    return p


def chart_rows(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [normalized_snapshot(r) for r in snapshots]
    rows = sorted([r for r in rows if r["_time"]], key=lambda r: (r["_time"], r.get("id", 0)))
    result = []
    for i, row in enumerate(rows):
        diff = interval(rows[i-1], row, rows[i-1:i+1]) if i else missing("首个采样")
        result.append({"time": row["collected_at"], "epoch": int(row["_time"].timestamp()*1000), "value": row.get("total_sales"), "precision": row.get("sales_precision"), "raw": row.get("sales_raw", ""), "price": row.get("price"), "delta": diff["value"], "reason": diff["reason"], "from_time": diff["from_time"], "hours": diff["hours"], "anomaly": diff["quality"] == "anomaly", "midnight": bool(row.get("is_midnight"))})
    return result
