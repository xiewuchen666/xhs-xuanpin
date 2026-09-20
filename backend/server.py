import argparse
import json
import logging
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from apscheduler.schedulers.background import BackgroundScheduler

import collector
import db
import exporter
import jobs
import logging_setup
import metrics

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR.parent / "web"


def _api_error(message: str, status: int = 400):
    return jsonify(ok=False, error=message), status


def _parse_bool_setting(value) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False
    raise ValueError("开关设置必须是布尔值")


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = testing
    app.extensions["collector_worker"] = None
    app.extensions["collection_scheduler"] = None
    db.init_db()

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/app.js")
    def script():
        return send_from_directory(WEB_DIR, "app.js")

    @app.get("/health")
    def health():
        worker = app.extensions.get("collector_worker")
        return jsonify(ok=True, collector=bool(worker and worker.alive))

    @app.get("/api/runtime/status")
    def runtime_status():
        cfg = db.get_settings()
        scheduler = app.extensions.get("collection_scheduler")
        worker = app.extensions.get("collector_worker")
        scheduled = []
        if scheduler and scheduler.running:
            for scheduled_job in scheduler.get_jobs():
                scheduled.append({
                    "id": scheduled_job.id,
                    "next_run_time": (
                        scheduled_job.next_run_time.isoformat()
                        if scheduled_job.next_run_time
                        else None
                    ),
                })
        latest = jobs.list_jobs(1)
        return jsonify(
            ok=True,
            auto_enabled=cfg.get("auto_enabled") == "1",
            auto_interval_minutes=int(cfg.get("auto_interval_minutes", "60")),
            midnight_enabled=cfg.get("midnight_enabled") == "1",
            worker_alive=bool(worker and worker.alive),
            scheduler_running=bool(scheduler and scheduler.running),
            scheduled=scheduled,
            latest_job=latest[0] if latest else None,
        )

    @app.get("/api/settings")
    def settings():
        return jsonify(db.get_settings())

    @app.post("/api/settings")
    def update_settings():
        try:
            body = request.get_json(silent=True) or {}
            current = db.get_settings()
            values: dict[str, str] = {}
            if "auto_interval_minutes" in body:
                interval = int(body["auto_interval_minutes"])
                if not 5 <= interval <= 1440:
                    raise ValueError("全局采集间隔必须在 5 到 1440 分钟之间")
                values["auto_interval_minutes"] = str(interval)
            for key in ("auto_enabled", "midnight_enabled"):
                if key in body:
                    values[key] = "1" if _parse_bool_setting(body[key]) else "0"
            if not values:
                raise ValueError("没有可保存的设置")
            db.set_settings(values)
            configure_scheduler(app)
            return jsonify(ok=True, settings={**current, **values})
        except (TypeError, ValueError) as exc:
            return _api_error(str(exc))

    @app.get("/api/products")
    def products():
        return jsonify(db.list_products())

    @app.get("/api/shops")
    def shops():
        return jsonify(db.list_shops())

    @app.get("/api/shops/<path:shop_key>/products")
    def shop_products(shop_key: str):
        return jsonify(db.list_shop_products(shop_key))

    @app.get("/api/selection")
    def selection_products():
        return jsonify(db.list_selection_products())

    @app.post("/api/export")
    def export_data():
        try:
            if request.is_json:
                body = request.get_json(silent=True) or {}
            else:
                raw = request.form.get("payload", "")
                body = json.loads(raw) if raw else {}
            module = str(body.get("module") or "").strip()
            fmt = str(body.get("format") or "").strip().lower()
            rows = body.get("rows")
            data, mimetype, filename = exporter.build_export(module, fmt, rows)
            return send_file(
                BytesIO(data),
                mimetype=mimetype,
                as_attachment=True,
                download_name=filename,
                max_age=0,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return _api_error(str(exc))

    @app.post("/api/products/collect")
    def collect():
        try:
            body = request.get_json(silent=True) or {}
            scope = str(body.get("scope") or "single").strip()
            if scope not in {"single", "shop", "selection"}:
                return _api_error("无效加入范围")
            url = collector.validate_url(body.get("url", ""))
            data = collector.collect_product(url)
            existing = db.get_product_by_item_id(str(data.get("item_id") or "").strip())
            if existing:
                product_id = int(existing["id"])
                duplicate = db.join_existing_scope(product_id, scope)
                message = (
                    {
                        "single": "已加入监控",
                        "shop": "已加入店铺监控",
                        "selection": "已加入选品中心",
                    }[scope]
                    if duplicate
                    else {
                        "single": "已恢复监控",
                        "shop": "已重新加入店铺监控",
                        "selection": "已重新加入选品中心",
                    }[scope]
                )
                return jsonify(
                    ok=True,
                    product_id=product_id,
                    product=existing,
                    scope=scope,
                    duplicate=duplicate,
                    restored=not duplicate,
                    message=message,
                )
            product_id = db.persist(
                url,
                data,
                join_single=(scope == "single"),
                join_shop=(scope == "shop"),
            )
            if scope == "selection":
                db.add_selection(product_id)
            return jsonify(
                ok=True,
                product_id=product_id,
                product=data,
                scope=scope,
                duplicate=False,
                restored=False,
                message={
                    "single": "已加入监控",
                    "shop": "已加入店铺监控",
                    "selection": "已加入选品中心",
                }[scope],
            )
        except (ValueError, RuntimeError) as exc:
            return _api_error(str(exc))
        except Exception:
            app.logger.exception("collect failed")
            return _api_error("采集失败，请查看本地日志", 500)

    @app.post("/api/products/<int:product_id>/collect")
    def collect_one(product_id: int):
        try:
            product = db.get_product(product_id)
            if not product or not db.is_monitored_product(product_id):
                return _api_error("商品不在持续监控范围中", 404)
            if product.get("monitor_state") != "active":
                return _api_error("商品已暂停，请先恢复监控", 409)
            job_id = jobs.enqueue("all", product_ids=[product_id])
            return jsonify(ok=True, product_id=product_id, job_id=job_id, queued=True), 202
        except ValueError as exc:
            return _api_error(str(exc), 409 if "已有采集任务" in str(exc) else 400)

    @app.post("/api/jobs/collect")
    def collect_job():
        try:
            body = request.get_json(silent=True) or {}
            product_ids = body.get("product_ids")
            scope = str(body.get("scope") or "all").strip()
            if scope not in {"all", "single", "shop", "selection"}:
                raise ValueError("无效采集范围")
            if not isinstance(product_ids, list) or not product_ids:
                raise ValueError("请选择需要采集的商品")
            normalized = []
            for value in product_ids:
                product_id = int(value)
                if product_id not in normalized:
                    normalized.append(product_id)
            job_id = jobs.enqueue(scope, product_ids=normalized)
            return jsonify(ok=True, job_id=job_id, queued=True), 202
        except (TypeError, ValueError) as exc:
            return _api_error(str(exc))

    @app.post("/api/shops/import")
    def import_shop_products():
        try:
            body = request.get_json(silent=True) or {}
            urls = collector.extract_share_urls(body.get("text", ""))
            if not urls:
                raise ValueError("未识别到小红书商品链接；可以直接粘贴商品链接或包含链接的分享口令/分享文本")
            if len(urls) > 100:
                raise ValueError("每次最多添加 100 个商品链接")
            job_id = jobs.enqueue("shop", urls=urls, kind="import")
            return jsonify(ok=True, job_id=job_id, queued=True, count=len(urls)), 202
        except ValueError as exc:
            return _api_error(str(exc))

    @app.get("/api/jobs/<int:job_id>")
    def job_status(job_id: int):
        job = jobs.get_job(job_id)
        if not job:
            return _api_error("任务不存在", 404)
        return jsonify(ok=True, job=job)

    @app.post("/api/products/<int:product_id>/state")
    def product_state(product_id: int):
        try:
            state = str((request.get_json(silent=True) or {}).get("state", "")).strip()
            db.set_monitor_state(product_id, state)
            return jsonify(ok=True, product_id=product_id, state=state)
        except ValueError as exc:
            return _api_error(str(exc), 404 if str(exc) == "商品不存在" else 400)

    @app.delete("/api/products/<int:product_id>/monitor")
    def remove_monitor(product_id: int):
        try:
            db.remove_single_monitor(product_id)
            return jsonify(ok=True, product_id=product_id)
        except ValueError as exc:
            return _api_error(str(exc), 404)

    @app.post("/api/products/<int:product_id>/shop-monitor")
    def join_shop_monitor(product_id: int):
        try:
            shop_id = db.add_shop_monitor(product_id)
            job_id = None
            product = db.get_product(product_id)
            if product and product.get("monitor_state") == "active":
                try:
                    job_id = jobs.enqueue("shop", product_ids=[product_id])
                except ValueError:
                    job_id = None
            return jsonify(
                ok=True,
                product_id=product_id,
                shop_id=shop_id,
                in_shop_monitor=True,
                job_id=job_id,
            )
        except ValueError as exc:
            return _api_error(str(exc), 404 if str(exc) == "商品不存在" else 400)

    @app.delete("/api/products/<int:product_id>/shop-monitor")
    def leave_shop_monitor(product_id: int):
        try:
            db.remove_shop_monitor(product_id)
            return jsonify(ok=True, product_id=product_id, in_shop_monitor=False)
        except ValueError as exc:
            return _api_error(str(exc), 404)

    @app.post("/api/products/<int:product_id>/selection")
    def join_selection(product_id: int):
        try:
            db.add_selection(product_id)
            return jsonify(ok=True, product_id=product_id, in_selection_pool=True)
        except ValueError as exc:
            return _api_error(str(exc), 404)

    @app.delete("/api/products/<int:product_id>/selection")
    def leave_selection(product_id: int):
        try:
            db.remove_selection(product_id)
            return jsonify(ok=True, product_id=product_id, in_selection_pool=False)
        except ValueError as exc:
            return _api_error(str(exc), 404)

    return app


def configure_scheduler(app: Flask) -> None:
    scheduler = app.extensions.get("collection_scheduler")
    if not scheduler:
        return
    cfg = db.get_settings()
    midnight_jobs = {
        "midnight_collect_2355": (23, 55, "2355"),
        "midnight_collect_0000": (0, 0, "0000"),
        "midnight_collect_0005": (0, 5, "0005"),
        "midnight_collect_0010": (0, 10, "0010"),
    }
    for name in ("auto_collect", "midnight_collect", *midnight_jobs):
        if scheduler.get_job(name):
            scheduler.remove_job(name)

    def submit(baseline_slot: str | None = None) -> None:
        trigger = f"midnight-{baseline_slot}" if baseline_slot else "interval"
        app.logger.info("Scheduled collection trigger fired: %s", trigger)
        try:
            job_id = jobs.enqueue("all", baseline_slot=baseline_slot)
            app.logger.info(
                "Scheduled collection queued: job=%s trigger=%s",
                job_id,
                trigger,
            )
        except ValueError as exc:
            app.logger.info(
                "Scheduled collection skipped: trigger=%s reason=%s",
                trigger,
                exc,
            )

    if cfg.get("auto_enabled") == "1":
        interval = timedelta(minutes=int(cfg.get("auto_interval_minutes", "60")))
        current = metrics.now()
        last_run = metrics.timestamp(jobs.latest_successful_all_collection_at())
        next_run = last_run + interval if last_run else current
        if next_run <= current:
            submit()
            next_run = current + interval
        scheduler.add_job(
            submit,
            "interval",
            minutes=interval.total_seconds() / 60,
            start_date=next_run,
            id="auto_collect",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
        )
    if cfg.get("midnight_enabled") == "1":
        for job_id, (hour, minute, slot) in midnight_jobs.items():
            scheduler.add_job(
                submit,
                "cron",
                args=[slot],
                hour=hour,
                minute=minute,
                id=job_id,
                timezone=metrics.TZ,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=60,
            )

    app.logger.info(
        "Scheduler configured: auto_enabled=%s interval_minutes=%s midnight_enabled=%s",
        cfg.get("auto_enabled") == "1",
        cfg.get("auto_interval_minutes", "60"),
        cfg.get("midnight_enabled") == "1",
    )


def start_runtime(app: Flask) -> tuple[jobs.Worker, BackgroundScheduler]:
    worker = jobs.Worker()
    worker.start()
    app.extensions["collector_worker"] = worker
    scheduler = BackgroundScheduler(timezone=metrics.TZ)
    app.extensions["collection_scheduler"] = scheduler
    configure_scheduler(app)
    scheduler.start()
    app.logger.info("Collection runtime started: worker_alive=%s scheduler_running=%s", worker.alive, scheduler.running)
    return worker, scheduler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=17861)
    parser.add_argument(
        "--no-collector",
        action="store_true",
        help="Run the local API without worker/scheduler for isolated tests.",
    )
    args = parser.parse_args()
    log_path = logging_setup.configure_logging()
    app = create_app()
    app.logger.info(
        "Backend service starting: port=%s no_collector=%s log=%s",
        args.port,
        args.no_collector,
        log_path,
    )
    worker = None
    scheduler = None
    try:
        if not args.no_collector:
            worker, scheduler = start_runtime(app)
        app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False, threaded=True)
    except Exception:
        app.logger.exception("Backend service terminated by unhandled exception")
        raise
    finally:
        app.logger.info("Backend service shutting down")
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
        if worker:
            worker.stop()
        app.logger.info("Backend service stopped")


if __name__ == "__main__":
    main()
