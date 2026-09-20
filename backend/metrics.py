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


def midnight_actions(rows: List[Dict[str, Any]]) -> Dict[int, str]:
    """Hold dense midnight drops until 00:10 or a recovery confirms 23:55."""
    groups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        day = str(row.get("baseline_day") or "")
        slot = str(row.get("baseline_slot") or "")
        if day and slot and exact_counter(row):
            groups.setdefault(day, {})[slot] = row

    actions: Dict[int, str] = {}
    for slots in groups.values():
        before, at_midnight = slots.get("2355"), slots.get("0000")
        if not before or not at_midnight or int(at_midnight["total_sales"]) >= int(before["total_sales"]):
            continue

        validators = [slots[slot] for slot in ("0005", "0010") if slot in slots]
        recovered = next(
            (row for row in validators if int(row["total_sales"]) >= int(before["total_sales"])),
            None,
        )
        if recovered:
            for row in [at_midnight, *validators]:
                if row["_time"] < recovered["_time"] and int(row["total_sales"]) < int(before["total_sales"]):
                    actions[id(row)] = "ignore"
        elif "0010" not in slots:
            for row in [at_midnight, *validators]:
                actions[id(row)] = "hold"
        else:
            actions[id(at_midnight)] = "reset"
    return actions


def resolve_counter_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classify exact counter readings without rewriting raw snapshots.

    A single reading below the last confirmed baseline is held as a pending
    rollback. If a later exact reading recovers to or above the baseline, the
    pending reading is ignored for delta calculations. If the next exact
    reading is still below the old baseline, the second low reading becomes a
    new baseline segment.
    """
    resolved = [dict(row) for row in rows]
    actions = midnight_actions(resolved)
    stable: Optional[Dict[str, Any]] = None
    pending: Optional[Dict[str, Any]] = None
    segment = 0

    for row in resolved:
        if not exact_counter(row):
            continue
        action = actions.get(id(row))
        if action == "ignore":
            row["_counter_state"] = "ignored_drop"
            row["_counter_segment"] = segment
            continue
        if action == "hold":
            row["_counter_state"] = "pending_drop"
            row["_counter_segment"] = segment
            continue
        if action == "reset" and stable is not None:
            segment += 1
            row["_counter_state"] = "reset_baseline"
            row["_counter_segment"] = segment
            stable = row
            pending = None
            continue
        value = int(row["total_sales"])
        if stable is None:
            row["_counter_state"] = "stable"
            row["_counter_segment"] = segment
            stable = row
            continue

        baseline = int(stable["total_sales"])
        if value >= baseline:
            if pending is not None:
                pending["_counter_state"] = "ignored_drop"
                pending["_counter_segment"] = segment
                pending = None
            row["_counter_state"] = "stable"
            row["_counter_segment"] = segment
            stable = row
            continue

        if pending is None:
            row["_counter_state"] = "pending_drop"
            row["_counter_segment"] = segment
            pending = row
            continue

        # Two consecutive exact readings remain below the last confirmed
        # baseline: confirm a reset, but start the new segment at the second
        # low reading so the first low never becomes a false growth baseline.
        pending["_counter_state"] = "reset_evidence"
        pending["_counter_segment"] = segment
        segment += 1
        row["_counter_state"] = "reset_baseline"
        row["_counter_segment"] = segment
        stable = row
        pending = None

    return resolved


def effective_counter_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("_counter_state") in {"stable", "reset_baseline"}
    ]


def interval(start: Optional[Dict[str, Any]], end: Optional[Dict[str, Any]], rows: List[Dict[str, Any]], approximate: bool = False) -> Dict[str, Any]:
    if not start or not end:
        return missing("缺少区间端点采样")
    if not exact_counter(start) or not exact_counter(end):
        return missing("端点包含近似、下限或未知销量，不能计算新增")

    start_state = start.get("_counter_state")
    end_state = end.get("_counter_state")
    if start_state == "pending_drop" or end_state == "pending_drop":
        return missing("销量回落待确认；暂不参与新增计算", "anomaly")
    if start_state not in {"stable", "reset_baseline"} or end_state not in {"stable", "reset_baseline"}:
        return missing("端点处于销量回落确认过程中，不能计算新增", "anomaly")
    if start.get("_counter_segment") != end.get("_counter_segment"):
        return missing("区间内发生销量基线重置；不能跨重置点计算新增")

    a, b = start["_time"], end["_time"]
    if b < a:
        return missing("采样时间顺序异常", "anomaly")
    if a == b and start.get("id") != end.get("id"):
        return missing("同秒多条记录，无法确定有效区间", "anomaly")

    ordered = [r for r in rows if r.get("_time") and a <= r["_time"] <= b]
    for row in ordered:
        if not exact_counter(row):
            return missing("区间内存在不确定读数，无法核实计数连续性")
        state = row.get("_counter_state")
        if state == "pending_drop":
            return missing("销量回落待确认；暂不参与新增计算", "anomaly")
        if state in {"ignored_drop", "reset_evidence"}:
            continue
        if state == "reset_baseline" and row.get("_counter_segment") != start.get("_counter_segment"):
            return missing("区间内发生销量基线重置；不能跨重置点计算新增")

    delta = int(end["total_sales"]) - int(start["total_sales"])
    if delta < 0:
        return missing("累计值回退待确认；暂不计算新增", "anomaly")
    hours = (b - a).total_seconds() / 3600
    return {
        "value": delta,
        "quality": "approximate" if approximate else "exact",
        "reason": "边界附近采样，不代表精确日界/整点" if approximate else "已确认基线之间的精确读数之差",
        "from_time": text_time(a),
        "to_time": text_time(b),
        "hours": hours,
    }


def nearest(rows: List[Dict[str, Any]], target: datetime, tolerance_minutes: int, upper: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    candidates = [r for r in rows if exact_counter(r) and (upper is None or r["_time"] <= upper) and abs((r["_time"] - target).total_seconds()) <= tolerance_minutes * 60]
    return min(candidates, key=lambda r: (abs((r["_time"] - target).total_seconds()), r["_time"], r.get("id", 0))) if candidates else None


def boundary_metric(
    rows: List[Dict[str, Any]],
    effective: List[Dict[str, Any]],
    target: datetime,
    end: Optional[Dict[str, Any]],
    tolerance: int,
) -> Dict[str, Any]:
    base = nearest(effective, target, tolerance, end["_time"] if end else None)
    if not base:
        return missing("缺少日界附近的已确认采样（容差 %s 分钟）" % tolerance)
    if not end or end["_time"] < target:
        return missing("今日尚无有效采样")
    return interval(base, end, rows, base["_time"] != target)


def window_metric(
    rows: List[Dict[str, Any]],
    effective: List[Dict[str, Any]],
    start: datetime,
    end: datetime,
    tolerance: int,
    as_of: datetime,
) -> Dict[str, Any]:
    left = nearest(effective, start, tolerance, as_of)
    right = nearest(effective, end, tolerance, as_of)
    if not left or not right:
        return missing("缺少统一窗口端点（容差 %s 分钟）；不使用旧数据冒充" % tolerance)
    return interval(left, right, rows, left["_time"] != start or right["_time"] != end)


def joined_metric(
    rows: List[Dict[str, Any]],
    effective: List[Dict[str, Any]],
    latest: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not rows or not effective or not latest or rows[0] is not effective[0]:
        return missing("首次采集不是可用于差分的精确销量")
    first = effective[0]
    if latest.get("_counter_state") != "stable" or first.get("_counter_segment") != 0 or latest.get("_counter_segment") != 0:
        return missing("加入后区间存在销量回落或基线重置")
    result = interval(first, latest, rows)
    if result["value"] is not None:
        result.update(
            partial=True,
            partial_label="加入后",
            reason="监控未满完整统计窗口；按加入后的首次采集计算",
        )
    return result


def recent_increment(
    rows: List[Dict[str, Any]],
    effective: List[Dict[str, Any]],
    latest: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not latest:
        return missing("至少需要两次采样")
    if not exact_counter(latest):
        return missing("本次销量不可用于精确差分；不沿用历史增量")

    state = latest.get("_counter_state")
    if state == "pending_drop":
        return missing("销量回落待确认；等待下一次采样确认", "anomaly")
    if state == "reset_baseline":
        return missing("销量基线已重置；等待下一次有效采样")
    if state != "stable":
        return missing("当前采样不能作为新增计算端点", "anomaly")

    segment = latest.get("_counter_segment")
    previous = next(
        (
            row
            for row in reversed(effective)
            if row is not latest
            and row.get("_counter_segment") == segment
            and row["_time"] <= latest["_time"]
        ),
        None,
    )
    if not previous:
        return missing("当前基线段至少需要两次有效采样")
    return interval(previous, latest, rows)


def enrich(product: Dict[str, Any], snapshots: List[Dict[str, Any]], as_of: Optional[datetime] = None, day_tolerance: int = 5, window_tolerance: int = 30, stale_minutes: int = 120) -> Dict[str, Any]:
    p = dict(product)
    current = timestamp(as_of) or now()
    rows = [normalized_snapshot(r) for r in snapshots]
    rows = sorted(
        [r for r in rows if r["_time"] and r["_time"] <= current],
        key=lambda r: (r["_time"], r.get("id", 0)),
    )
    rows = resolve_counter_rows(rows)
    effective = effective_counter_rows(rows)
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
    today = boundary_metric(rows, effective, midnight, latest, day_tolerance)
    if today["value"] is None and rows and rows[0]["_time"] >= midnight:
        joined_today = joined_metric(rows, effective, latest)
        if joined_today["value"] is not None:
            today = joined_today
    y_start = nearest(effective, midnight - timedelta(days=1), day_tolerance, current)
    y_end = nearest(effective, midnight, day_tolerance, current)
    yesterday = (
        interval(
            y_start,
            y_end,
            rows,
            bool(
                y_start
                and y_end
                and (
                    y_start["_time"] != midnight - timedelta(days=1)
                    or y_end["_time"] != midnight
                )
            ),
        )
        if y_start and y_end
        else missing("缺少昨日或今日日界附近的已确认采样")
    )
    increment = recent_increment(rows, effective, latest)
    window_end = latest["_time"] if latest else current
    history_hours = (window_end - rows[0]["_time"]).total_seconds() / 3600 if rows and latest else 0
    rolling = (
        joined_metric(rows, effective, latest)
        if history_hours < 24
        else window_metric(
            rows,
            effective,
            window_end - timedelta(hours=24),
            window_end,
            window_tolerance,
            current,
        )
    )
    prior = window_metric(
        rows,
        effective,
        window_end - timedelta(hours=48),
        window_end - timedelta(hours=24),
        window_tolerance,
        current,
    )

    latest_counter_state = latest.get("_counter_state") if latest else None
    if latest_counter_state == "pending_drop":
        today = missing("销量回落待确认；等待下一次采样确认", "anomaly")
        rolling = missing("销量回落待确认；等待下一次采样确认", "anomaly")
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
    p["counter_state"] = latest_counter_state or "unknown"
    p["anomaly"] = any(m["quality"] == "anomaly" for m in (today, yesterday, increment, rolling, prior))
    failed = p.get("last_attempt_status") == "failed" or (p.get("last_status") not in (None, "", "正常") and not p.get("last_attempt_status"))
    if p.get("monitor_state") == "archived":
        p["health"], p["health_label"] = "muted", "已归档"
    elif p.get("monitor_state") == "paused":
        p["health"], p["health_label"] = "muted", "已暂停"
    elif failed:
        p["health"], p["health_label"] = "danger", "最近采集失败"
    elif latest_counter_state == "pending_drop":
        p["health"], p["health_label"] = "warning", "销量回落待确认"
    elif latest_counter_state == "reset_baseline":
        p["health"], p["health_label"] = "warning", "销量基线已重置"
    elif p["anomaly"]:
        p["health"], p["health_label"] = "danger", "计数区间异常"
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
    rows = resolve_counter_rows(rows)
    effective = effective_counter_rows(rows)
    result = []
    for row in rows:
        state = row.get("_counter_state")
        if state == "pending_drop":
            diff = missing("销量回落待确认；等待下一次采样确认", "anomaly")
        elif state in {"ignored_drop", "reset_evidence"}:
            diff = missing("销量回落采样已排除，不参与新增计算", "anomaly")
        elif state == "reset_baseline":
            diff = missing("销量基线已重置；从此采样重新开始")
        elif state == "stable":
            previous = next(
                (
                    candidate
                    for candidate in reversed(effective)
                    if candidate is not row
                    and candidate.get("_counter_segment") == row.get("_counter_segment")
                    and candidate["_time"] <= row["_time"]
                ),
                None,
            )
            diff = interval(previous, row, rows) if previous else missing("首个采样")
        else:
            diff = missing("该采样不能用于精确新增计算")
        result.append({
            "time": row["collected_at"],
            "epoch": int(row["_time"].timestamp() * 1000),
            "value": row.get("total_sales"),
            "precision": row.get("sales_precision"),
            "raw": row.get("sales_raw", ""),
            "price": row.get("price"),
            "delta": diff["value"],
            "reason": diff["reason"],
            "from_time": diff["from_time"],
            "hours": diff["hours"],
            "anomaly": diff["quality"] == "anomaly",
            "counter_state": state or "unknown",
            "midnight": bool(row.get("is_midnight")),
        })
    return result


def sales_trend(
    snapshots: List[Dict[str, Any]],
    as_of: Optional[datetime] = None,
    day_tolerance: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build daily and hourly sales series from the existing counter rules."""
    current = timestamp(as_of) or now()
    source = [snapshot for snapshot in snapshots if (timestamp(snapshot.get("collected_at")) or current) <= current]
    rows = [normalized_snapshot(row) for row in source]
    rows = sorted([row for row in rows if row["_time"]], key=lambda row: (row["_time"], row.get("id", 0)))
    rows = resolve_counter_rows(rows)
    effective = effective_counter_rows(rows)

    daily = []
    for offset in range(29, -1, -1):
        day = current.date() - timedelta(days=offset)
        start = datetime.combine(day, datetime.min.time(), tzinfo=TZ)
        finish = start + timedelta(days=1)
        end = (
            rows[-1]
            if day == current.date() and rows and rows[-1]["_time"] >= start
            else nearest(effective, finish, day_tolerance, current)
        )
        base = nearest(effective, start, day_tolerance, current)
        metric = interval(base, end, rows, bool(base and base["_time"] != start)) if base and end else missing("缺少日界附近的有效采样")
        joined = bool(rows and effective and rows[0] is effective[0] and start <= rows[0]["_time"] < finish)
        if metric["value"] is None and joined and end:
            metric = interval(effective[0], end, rows)
            if metric["value"] is not None:
                metric.update(partial=True, reason="监控首日按加入后的首次采集计算")
        if metric["value"] is not None and day == current.date():
            metric["partial"] = True
            metric["reason"] = "今日截至最近一次有效采集，尚未形成完整自然日"
        daily.append({
            "date": day.isoformat(),
            "label": day.strftime("%m-%d"),
            **metric,
        })

    cutoff = current - timedelta(hours=24)
    hourly = []
    for point in chart_rows(source):
        point_time = timestamp(point["time"])
        if not point_time or point_time < cutoff or point_time > current:
            continue
        hours = point.get("hours")
        value = point.get("delta")
        regular_interval = value is not None and hours is not None and 0.5 <= hours <= 1.5
        reason = point["reason"]
        if value is not None and not regular_interval:
            reason = "实际采集间隔为 %.1f 小时，不作为单小时销量点" % hours
        hourly.append({
            **point,
            "label": point_time.strftime("%H:%M"),
            "value": value if regular_interval else None,
            "reason": reason,
        })
    return {"daily": daily, "hourly": hourly}
