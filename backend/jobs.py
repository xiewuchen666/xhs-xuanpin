"""Durable single-worker collection queue adapted from rednote-commerce-hub.

Scheduled jobs only enqueue work. The worker owns collection execution so one
failed product does not crash a whole batch and duplicate active work is
coalesced.
"""
import logging
import re
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any

import collector as collector_module
import db

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"success", "partial", "failed", "blocked", "cancelled", "interrupted"}
BASELINE_SLOTS = {"2355"}
RETRY_DELAY_SECONDS = 30


def safe_error(exc: Exception) -> str:
    return re.sub(r"https?://\S+", "[链接]", str(exc))[:800] or type(exc).__name__


def requires_verification(message: str) -> bool:
    return any(
        term in message
        for term in ("人工安全验证", "验证码", "安全验证", "异常访问", "请完成验证")
    )


def enqueue(
    scope: str = "all",
    *,
    product_ids: list[int] | None = None,
    urls: list[str] | None = None,
    kind: str = "collect",
    is_midnight: bool = False,
    baseline_slot: str | None = None,
    parent_id: int | None = None,
) -> int:
    if scope not in {"all", "single", "shop", "selection"}:
        raise ValueError("无效采集范围")
    if kind not in {"collect", "import"}:
        raise ValueError("无效任务类型")
    if baseline_slot is not None and baseline_slot not in BASELINE_SLOTS:
        raise ValueError("无效午夜基线采样时点")
    if baseline_slot is not None:
        is_midnight = True
    elif is_midnight:
        baseline_slot = "2355"

    if kind == "import":
        if scope == "all":
            raise ValueError("导入任务必须指定监控范围")
        unique_urls: list[str] = []
        for url in urls or []:
            validated = collector_module.validate_url(url)
            if validated not in unique_urls:
                unique_urls.append(validated)
        if len(unique_urls) > 100:
            raise ValueError("每次最多导入 100 个商品链接")
        targets: list[tuple[int | None, str]] = [(None, url) for url in unique_urls]
    else:
        products = db.get_monitored_products_raw(scope)
        if product_ids is not None:
            allowed = {int(product_id) for product_id in product_ids}
            products = [product for product in products if int(product["id"]) in allowed]
        targets = [(int(product["id"]), str(product["url"])) for product in products]

    if not targets:
        raise ValueError("没有可处理的商品；请检查监控范围和暂停状态")

    with closing(db.connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            """
            SELECT i.product_id,i.url,i.job_id,j.kind,j.scope,j.is_midnight,j.baseline_slot
            FROM job_items i
            JOIN jobs j ON j.id=i.job_id
            WHERE j.status IN ('queued','running')
              AND i.status IN ('queued','running')
            """
        ).fetchall()
        if kind == "import":
            active = [
                row
                for row in active
                if row["kind"] == "import" and row["scope"] == scope
            ]
        elif is_midnight:
            active = [
                row
                for row in active
                if bool(row["is_midnight"]) and row["baseline_slot"] == baseline_slot
            ]
        else:
            active = [row for row in active if not bool(row["is_midnight"])]
        active_ids = {int(row["product_id"]) for row in active if row["product_id"] is not None}
        active_urls = {str(row["url"]) for row in active}
        filtered = [
            (product_id, url)
            for product_id, url in targets
            if (product_id is None or product_id not in active_ids) and url not in active_urls
        ]
        if not filtered:
            target_ids = {product_id for product_id, _ in targets if product_id is not None}
            target_urls = {url for _, url in targets}
            existing = next(
                (
                    row["job_id"]
                    for row in active
                    if (row["product_id"] is not None and int(row["product_id"]) in target_ids)
                    or str(row["url"]) in target_urls
                ),
                None,
            )
            if existing is not None:
                logger.info(
                    "Queue request coalesced into existing job: job=%s kind=%s scope=%s",
                    existing,
                    kind,
                    scope,
                )
                return int(existing)
            raise ValueError("目标商品已有采集任务")

        job_id = int(
            conn.execute(
                """
                INSERT INTO jobs(kind,scope,created_at,is_midnight,baseline_slot,parent_id)
                VALUES(?,?,?,?,?,?)
                """,
                (kind, scope, db.now_text(), int(is_midnight), baseline_slot, parent_id),
            ).lastrowid
        )
        conn.executemany(
            "INSERT INTO job_items(job_id,product_id,url) VALUES(?,?,?)",
            [(job_id, product_id, url) for product_id, url in filtered],
        )
        logger.info(
            "Job queued: job=%s kind=%s scope=%s items=%s midnight=%s slot=%s parent=%s",
            job_id,
            kind,
            scope,
            len(filtered),
            is_midnight,
            baseline_slot,
            parent_id,
        )
        return job_id


def recover_interrupted() -> None:
    # Never replay an old midnight task as though it still happened at 00:00.
    with closing(db.connect()) as conn, conn:
        now = db.now_text()
        conn.execute(
            """
            UPDATE job_items
            SET status='interrupted',message='服务停止，未自动重试',finished_at=?
            WHERE status IN ('queued','running')
              AND job_id IN (SELECT id FROM jobs WHERE status IN ('queued','running'))
            """,
            (now,),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status='interrupted',error='服务停止；如需补采应作为普通采样重新执行',finished_at=?
            WHERE status IN ('queued','running')
            """,
            (now,),
        )


def get_job(job_id: int) -> dict[str, Any] | None:
    with closing(db.connect()) as conn, conn:
        raw = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not raw:
            return None
        result = dict(raw)
        result["items"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT i.*,p.title
                FROM job_items i
                LEFT JOIN products p ON p.id=i.product_id
                WHERE i.job_id=?
                ORDER BY i.id
                """,
                (job_id,),
            )
        ]
        return result


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with closing(db.connect()) as conn, conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT j.*,
                       COUNT(i.id) AS total,
                       SUM(CASE WHEN i.status='success' THEN 1 ELSE 0 END) AS succeeded,
                       SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN i.status='skipped' THEN 1 ELSE 0 END) AS skipped,
                       SUM(CASE WHEN i.status NOT IN ('queued','running') THEN 1 ELSE 0 END) AS done
                FROM jobs j
                LEFT JOIN job_items i ON i.job_id=j.id
                GROUP BY j.id
                ORDER BY j.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]


def latest_successful_all_collection_at() -> str | None:
    with closing(db.connect()) as conn:
        row = conn.execute(
            """
            SELECT created_at FROM jobs
            WHERE kind='collect' AND scope='all' AND status='success' AND is_midnight=0
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        return str(row["created_at"]) if row else None


def cancel(job_id: int) -> None:
    with closing(db.connect()) as conn, conn:
        now = db.now_text()
        conn.execute(
            "UPDATE jobs SET cancel_requested=1 WHERE id=? AND status IN ('queued','running')",
            (job_id,),
        )
        conn.execute(
            """
            UPDATE job_items
            SET status='cancelled',message='用户取消',finished_at=?
            WHERE job_id=? AND status='queued'
            """,
            (now, job_id),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status='cancelled',finished_at=?
            WHERE id=? AND status='queued'
            """,
            (now, job_id),
        )


def retry(job_id: int) -> int:
    job = get_job(job_id)
    if not job or job["status"] in {"queued", "running"}:
        raise ValueError("任务不存在或仍在执行")
    remaining = [
        item
        for item in job["items"]
        if item["status"] in {"failed", "cancelled", "interrupted"}
    ]
    if not remaining:
        raise ValueError("没有可重试项目")
    # Retried midnight work is always an ordinary observation.
    if job["kind"] == "import":
        return enqueue(
            job["scope"],
            urls=[str(item["url"]) for item in remaining],
            kind="import",
            parent_id=job_id,
            is_midnight=False,
        )
    return enqueue(
        job["scope"],
        product_ids=[
            int(item["product_id"])
            for item in remaining
            if item.get("product_id") is not None
        ],
        parent_id=job_id,
        is_midnight=False,
    )


def baseline_day(created_at: str, slot: str | None) -> str:
    day = datetime.fromisoformat(created_at).date()
    if slot == "2355":
        day += timedelta(days=1)
    return day.isoformat()


def process_next(collect_fn=None) -> bool:
    collect_fn = collect_fn or collector_module.collect_product
    with closing(db.connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        raw = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status='queued' AND cancel_requested=0
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if not raw:
            return False
        job = dict(raw)
        conn.execute(
            "UPDATE jobs SET status='running',started_at=? WHERE id=?",
            (db.now_text(), job["id"]),
        )

    logger.info(
        "Job started: job=%s kind=%s scope=%s midnight=%s",
        job["id"],
        job["kind"],
        job["scope"],
        bool(job["is_midnight"]),
    )
    blocked = False
    while True:
        with closing(db.connect()) as conn, conn:
            current = conn.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if not current or current["cancel_requested"]:
                break
            item_raw = conn.execute(
                """
                SELECT * FROM job_items
                WHERE job_id=? AND status='queued'
                ORDER BY id
                LIMIT 1
                """,
                (job["id"],),
            ).fetchone()
            if not item_raw:
                break
            item = dict(item_raw)
            conn.execute(
                "UPDATE job_items SET status='running',started_at=? WHERE id=?",
                (db.now_text(), item["id"]),
            )

        try:
            if job["kind"] == "collect":
                product = db.get_product(int(item["product_id"]))
                eligible_ids = {
                    int(product_row["id"])
                    for product_row in db.get_monitored_products_raw(job["scope"])
                }
                if (
                    not product
                    or product.get("monitor_state") != "active"
                    or int(item["product_id"]) not in eligible_ids
                ):
                    with closing(db.connect()) as conn, conn:
                        conn.execute(
                            """
                            UPDATE job_items
                            SET status='skipped',
                                message='商品已暂停或移出持续监控范围',
                                finished_at=?
                            WHERE id=?
                            """,
                            (db.now_text(), item["id"]),
                        )
                    continue

            try:
                data = collect_fn(str(item["url"]))
            except Exception as first_error:
                first_message = safe_error(first_error)
                if requires_verification(first_message):
                    raise
                logger.warning(
                    "Job item first attempt failed; retrying in %ss: job=%s item=%s reason=%s",
                    RETRY_DELAY_SECONDS,
                    job["id"],
                    item["id"],
                    first_message,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                data = collect_fn(str(item["url"]))
                logger.info(
                    "Job item retry succeeded: job=%s item=%s",
                    job["id"],
                    item["id"],
                )

            if job["kind"] == "import":
                existing = db.get_product_by_item_id(
                    str(data.get("item_id") or "").strip()
                )
                if existing:
                    product_id = int(existing["id"])
                    duplicate = db.join_existing_scope(product_id, str(job["scope"]))
                    message = (
                        {
                            "single": "已加入监控",
                            "shop": "已加入店铺监控",
                            "selection": "已加入选品中心",
                        }[job["scope"]]
                        if duplicate
                        else {
                            "single": "已恢复监控",
                            "shop": "已重新加入店铺监控",
                            "selection": "已重新加入选品中心",
                        }[job["scope"]]
                    )
                    with closing(db.connect()) as conn, conn:
                        conn.execute(
                            """
                            UPDATE job_items
                            SET product_id=?,status=?,message=?,finished_at=?
                            WHERE id=?
                            """,
                            (
                                product_id,
                                "skipped" if duplicate else "success",
                                message,
                                db.now_text(),
                                item["id"],
                            ),
                        )
                    continue

                product_id = db.persist(
                    str(item["url"]),
                    data,
                    join_single=(job["scope"] == "single"),
                    join_shop=(job["scope"] == "shop"),
                    is_midnight=False,
                )
                if job["scope"] == "selection":
                    db.add_selection(product_id)
            else:
                product_id = int(item["product_id"])
                db.persist(
                    str(item["url"]),
                    data,
                    join_single=False,
                    expected_product_id=product_id,
                    is_midnight=bool(job["is_midnight"]),
                    baseline_day=baseline_day(str(job["created_at"]), job.get("baseline_slot")),
                    baseline_slot=job.get("baseline_slot"),
                )

            with closing(db.connect()) as conn, conn:
                conn.execute(
                    """
                    UPDATE job_items
                    SET product_id=?,status='success',message='已保存观测记录',finished_at=?
                    WHERE id=?
                    """,
                    (product_id, db.now_text(), item["id"]),
                )
            logger.info(
                "Job item succeeded: job=%s item=%s product=%s",
                job["id"],
                item["id"],
                product_id,
            )
        except Exception as exc:
            message = safe_error(exc)
            logger.warning("Job %s item %s failed: %s", job["id"], item["id"], message)
            if item.get("product_id"):
                db.mark_product_error(int(item["product_id"]), message)
            with closing(db.connect()) as conn, conn:
                conn.execute(
                    """
                    UPDATE job_items
                    SET status='failed',message=?,finished_at=?
                    WHERE id=?
                    """,
                    (message, db.now_text(), item["id"]),
                )
            if requires_verification(message):
                blocked = True
                logger.error(
                    "Job blocked by verification requirement: job=%s item=%s reason=%s",
                    job["id"],
                    item["id"],
                    message,
                )
                break

    with closing(db.connect()) as conn, conn:
        current = conn.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if not current:
            return True
        if blocked or current["cancel_requested"]:
            conn.execute(
                """
                UPDATE job_items
                SET status='cancelled',message=?,finished_at=?
                WHERE job_id=? AND status='queued'
                """,
                (
                    "需先人工处理验证/登录，再手动重试"
                    if blocked
                    else "用户取消",
                    db.now_text(),
                    job["id"],
                ),
            )
        counts = {
            str(row["status"]): int(row["n"])
            for row in conn.execute(
                "SELECT status,COUNT(*) n FROM job_items WHERE job_id=? GROUP BY status",
                (job["id"],),
            )
        }
        if blocked:
            status = "blocked"
            error = "需要人工处理验证或登录；本任务已停止"
        elif current["cancel_requested"]:
            status = "cancelled"
            error = None
        elif counts.get("failed") and counts.get("success"):
            status = "partial"
            error = None
        elif counts.get("failed"):
            status = "failed"
            error = None
        else:
            status = "success"
            error = None
        conn.execute(
            "UPDATE jobs SET status=?,finished_at=?,error=? WHERE id=?",
            (status, db.now_text(), error, job["id"]),
        )

    logger.info(
        "Job finished: job=%s status=%s success=%s failed=%s skipped=%s cancelled=%s",
        job["id"],
        status,
        counts.get("success", 0),
        counts.get("failed", 0),
        counts.get("skipped", 0),
        counts.get("cancelled", 0),
    )
    return True


class Worker:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        recover_interrupted()
        self.thread = threading.Thread(
            target=self._run,
            name="xhs-xuanpin-collector",
            daemon=True,
        )
        self.thread.start()
        logger.info("Collection worker thread started")

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = process_next()
            except Exception:
                logger.exception("Collection worker error")
                worked = False
            self.stop_event.wait(0.15 if worked else 0.8)

    def stop(self) -> None:
        logger.info("Collection worker stop requested")
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        logger.info("Collection worker stopped: alive=%s", self.alive)

    @property
    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

