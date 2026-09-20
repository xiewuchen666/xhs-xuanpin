import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.schedulers.background import BackgroundScheduler

import db
import jobs
import metrics
import server


def payload(item_id: str, observed_at: str, sales: int = 100) -> dict:
    return {
        "item_id": item_id,
        "title": "商品-" + item_id,
        "image_url": "",
        "shop_id": "shop-" + item_id,
        "shop_name": "店铺-" + item_id,
        "price": 19.9,
        "total_sales": sales,
        "sales_raw": f"已售{sales}",
        "sales_precision": "exact",
        "observed_at": observed_at,
    }


class PhaseThreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xhs-xuanpin-phase3-")
        self.old_dir, self.old_path = db.DATA_DIR, db.DB_PATH
        db.DATA_DIR = Path(self.temp.name)
        db.DB_PATH = db.DATA_DIR / "phase3.db"
        db.init_db()

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH = self.old_dir, self.old_path
        self.temp.cleanup()

    def add_single(self, item_id: str, sales: int = 100) -> int:
        return db.persist(
            f"https://xiaohongshu.com/goods-detail/{item_id}",
            payload(item_id, "2026-09-18 10:00:00", sales),
        )

    def add_selection_only(self, item_id: str, sales: int = 100) -> int:
        product_id = db.persist(
            f"https://xiaohongshu.com/goods-detail/{item_id}",
            payload(item_id, "2026-09-18 10:00:00", sales),
            join_single=False,
        )
        db.add_selection(product_id)
        return product_id

    def add_shop_only(self, item_id: str, sales: int = 100) -> int:
        product_id = db.persist(
            f"https://xiaohongshu.com/goods-detail/{item_id}",
            payload(item_id, "2026-09-18 10:00:00", sales),
            join_single=False,
            join_shop=True,
        )
        return product_id

    def test_default_settings_and_scheduler_match_phase3_contract(self):
        settings = db.get_settings()
        self.assertEqual(settings["auto_enabled"], "1")
        self.assertEqual(settings["auto_interval_minutes"], "60")
        self.assertEqual(settings["midnight_enabled"], "1")
        self.assertEqual(settings["day_tolerance_minutes"], "5")
        self.assertEqual(settings["window_tolerance_minutes"], "30")

        app = server.create_app(testing=True)
        scheduler = BackgroundScheduler(timezone=metrics.TZ)
        app.extensions["collection_scheduler"] = scheduler
        server.configure_scheduler(app)
        self.assertEqual(
            {scheduled.id for scheduled in scheduler.get_jobs()},
            {
                "auto_collect",
                "midnight_collect_2355",
            },
        )

    def test_scheduler_restart_keeps_anchor_and_immediately_catches_up_when_overdue(self):
        with closing(db.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO jobs(kind,scope,status,created_at,started_at,finished_at)
                VALUES('collect','all','success',?,?,?)
                """,
                (
                    "2026-09-20 07:55:17",
                    "2026-09-20 07:55:17",
                    "2026-09-20 07:55:43",
                ),
            )

        app = server.create_app(testing=True)
        scheduler = BackgroundScheduler(timezone=metrics.TZ)
        app.extensions["collection_scheduler"] = scheduler
        with (
            mock.patch("server.metrics.now", return_value=datetime(2026, 9, 20, 8, 34, tzinfo=metrics.TZ)),
            mock.patch("server.jobs.enqueue") as enqueue,
        ):
            server.configure_scheduler(app)
        enqueue.assert_not_called()
        self.assertEqual(
            scheduler.get_job("auto_collect").trigger.start_date,
            datetime(2026, 9, 20, 8, 55, 17, tzinfo=metrics.TZ),
        )

        overdue_scheduler = BackgroundScheduler(timezone=metrics.TZ)
        app.extensions["collection_scheduler"] = overdue_scheduler
        with (
            mock.patch("server.metrics.now", return_value=datetime(2026, 9, 20, 9, 10, tzinfo=metrics.TZ)),
            mock.patch("server.jobs.enqueue", return_value=7) as enqueue,
        ):
            server.configure_scheduler(app)
        enqueue.assert_called_once_with("all", baseline_slot=None)
        self.assertEqual(
            overdue_scheduler.get_job("auto_collect").trigger.start_date,
            datetime(2026, 9, 20, 10, 10, tzinfo=metrics.TZ),
        )

    def test_all_scope_is_deduped_union_and_excludes_paused(self):
        shared = self.add_single("shared")
        db.add_selection(shared)
        selection_only = self.add_selection_only("selection-only")
        shop_only = self.add_shop_only("shop-only")
        paused = self.add_single("paused")
        db.set_monitor_state(paused, "paused")

        job_id = jobs.enqueue("all")
        item_ids = [item["product_id"] for item in jobs.get_job(job_id)["items"]]
        self.assertEqual(item_ids, [shared, selection_only, shop_only])

    def test_only_2355_is_a_valid_midnight_baseline_slot(self):
        self.add_single("dense-midnight")

        first = jobs.enqueue("all", baseline_slot="2355")

        self.assertEqual(jobs.get_job(first)["baseline_slot"], "2355")
        with self.assertRaisesRegex(ValueError, "无效午夜基线采样时点"):
            jobs.enqueue("all", baseline_slot="0000")

    def test_queued_item_is_rechecked_and_skipped_after_pause(self):
        product_id = self.add_single("pause-after-queue")
        job_id = jobs.enqueue("all")
        db.set_monitor_state(product_id, "paused")

        with mock.patch.object(jobs.collector_module, "collect_product") as collect_mock:
            self.assertTrue(jobs.process_next())
        collect_mock.assert_not_called()
        job = jobs.get_job(job_id)
        self.assertEqual(job["status"], "success")
        self.assertEqual(job["items"][0]["status"], "skipped")

    def test_one_product_failure_does_not_stop_normal_batch(self):
        first = self.add_single("first")
        second = self.add_selection_only("second")
        job_id = jobs.enqueue("all")
        attempts = {"first": 0, "second": 0}

        def fake_collect(url: str):
            if url.endswith("/first"):
                attempts["first"] += 1
                raise RuntimeError("未捕获到商品详情数据，可能是链接失效、登录态不足或页面接口发生变化")
            attempts["second"] += 1
            return payload("second", "2026-09-18 11:00:00", 130)

        with mock.patch("jobs.time.sleep") as sleep:
            self.assertTrue(jobs.process_next(fake_collect))
        job = jobs.get_job(job_id)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(
            [item["status"] for item in job["items"]],
            ["failed", "success"],
        )
        self.assertEqual(db.snapshot_count(first), 1)
        self.assertEqual(db.snapshot_count(second), 2)
        failed = db.get_product(first)
        self.assertEqual(failed["last_attempt_status"], "failed")
        self.assertNotEqual(failed["last_attempt_at"], failed["last_collected_at"])
        failed_view = next(product for product in db.list_products() if product["id"] == first)
        self.assertEqual(failed_view["health_label"], "采集失败")
        self.assertEqual(attempts, {"first": 2, "second": 1})
        sleep.assert_called_once_with(30)

    def test_transient_product_failure_retries_after_30_seconds(self):
        product_id = self.add_single("retry")
        job_id = jobs.enqueue("all")
        attempts = 0

        def flaky(_url: str):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary collection failure")
            return payload("retry", "2026-09-18 11:00:00", 130)

        with mock.patch("jobs.time.sleep") as sleep:
            self.assertTrue(jobs.process_next(flaky))

        self.assertEqual(jobs.get_job(job_id)["status"], "success")
        self.assertEqual(db.snapshot_count(product_id), 2)
        self.assertEqual(attempts, 2)
        sleep.assert_called_once_with(30)

    def test_product_failure_log_redacts_url(self):
        self.add_single("redacted-log")
        jobs.enqueue("all")

        def fail_with_url(_url: str):
            raise RuntimeError("failed https://example.com/item?xsec_token=secret")

        with (
            mock.patch("jobs.time.sleep"),
            self.assertLogs(jobs.logger, level="WARNING") as captured,
        ):
            self.assertTrue(jobs.process_next(fail_with_url))

        output = "\n".join(captured.output)
        self.assertIn("failed [链接]", output)
        self.assertNotIn("xsec_token", output)

    def test_verification_failure_blocks_remaining_batch(self):
        self.add_single("verify-a")
        self.add_single("verify-b")
        job_id = jobs.enqueue("all")

        def blocked(_url: str):
            raise RuntimeError("小红书要求人工安全验证")

        with mock.patch("jobs.time.sleep") as sleep:
            self.assertTrue(jobs.process_next(blocked))
        job = jobs.get_job(job_id)
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(
            [item["status"] for item in job["items"]],
            ["failed", "cancelled"],
        )
        sleep.assert_not_called()

    def test_midnight_sample_is_marked_and_retry_is_ordinary(self):
        product_id = self.add_single("midnight")
        job_id = jobs.enqueue("all", is_midnight=True, baseline_slot="2355")
        with closing(db.connect()) as conn, conn:
            conn.execute(
                "UPDATE jobs SET created_at='2026-09-18 23:55:00' WHERE id=?",
                (job_id,),
            )
        self.assertTrue(
            jobs.process_next(
                lambda _url: payload("midnight", "2026-09-18 23:55:01", 120)
            )
        )
        with closing(db.connect()) as conn:
            latest = conn.execute(
                """
                SELECT is_midnight,baseline_day,baseline_slot
                FROM snapshots
                WHERE product_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (product_id,),
            ).fetchone()
        self.assertEqual(latest["is_midnight"], 1)
        self.assertEqual(latest["baseline_day"], "2026-09-19")
        self.assertEqual(latest["baseline_slot"], "2355")

        another = self.add_single("interrupted")
        interrupted_job = jobs.enqueue("all", product_ids=[another], is_midnight=True)
        jobs.recover_interrupted()
        self.assertEqual(jobs.get_job(interrupted_job)["status"], "interrupted")
        retry_job = jobs.retry(interrupted_job)
        self.assertEqual(jobs.get_job(retry_job)["is_midnight"], 0)

    def test_selection_only_product_supports_manual_collect_pause_and_resume(self):
        product_id = self.add_selection_only("selection-api")
        app = server.create_app(testing=True)
        client = app.test_client()

        updated = payload("selection-api", "2026-09-18 11:00:00", 145)
        response = client.post(f"/api/products/{product_id}/collect", json={})
        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        self.assertTrue(jobs.process_next(lambda _url: updated))
        self.assertEqual(jobs.get_job(job_id)["status"], "success")
        self.assertEqual(db.snapshot_count(product_id), 2)

        response = client.post(
            f"/api/products/{product_id}/state",
            json={"state": "paused"},
        )
        self.assertEqual(response.status_code, 200)
        response = client.post(f"/api/products/{product_id}/collect", json={})
        self.assertEqual(response.status_code, 409)

        response = client.post(
            f"/api/products/{product_id}/state",
            json={"state": "active"},
        )
        self.assertEqual(response.status_code, 200)

    def test_batch_collect_api_queues_one_worker_job(self):
        first = self.add_single("batch-first")
        second = self.add_selection_only("batch-second")
        app = server.create_app(testing=True)
        client = app.test_client()

        response = client.post(
            "/api/jobs/collect",
            json={"product_ids": [first, second, first]},
        )
        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        job = jobs.get_job(job_id)
        self.assertEqual([item["product_id"] for item in job["items"]], [first, second])

    def test_adding_selection_does_not_silently_resume_paused_product(self):
        product_id = self.add_single("paused-selection")
        db.set_monitor_state(product_id, "paused")
        db.add_selection(product_id)
        self.assertTrue(db.is_in_selection(product_id))
        self.assertEqual(db.get_product(product_id)["monitor_state"], "paused")

    def test_missing_observation_does_not_erase_last_known_sales(self):
        product_id = self.add_single("preserve-sales", sales=321)
        missing = payload("preserve-sales", "2026-09-18 11:00:00", sales=0)
        missing["price"] = None
        missing["total_sales"] = None
        missing["sales_raw"] = ""
        missing["sales_precision"] = "unknown"
        db.persist(
            "https://xiaohongshu.com/goods-detail/preserve-sales",
            missing,
            join_single=False,
            expected_product_id=product_id,
        )
        product = db.get_product(product_id)
        self.assertEqual(product["total_sales"], 321)
        self.assertEqual(product["price"], 19.9)
        with closing(db.connect()) as conn:
            latest = conn.execute(
                "SELECT total_sales,sales_precision FROM snapshots WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()
        self.assertIsNone(latest["total_sales"])
        self.assertEqual(latest["sales_precision"], "unknown")

    def test_settings_api_validates_interval(self):
        app = server.create_app(testing=True)
        client = app.test_client()

        response = client.post(
            "/api/settings",
            json={"auto_interval_minutes": 4},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.get_settings()["auto_interval_minutes"], "60")

        response = client.post(
            "/api/settings",
            json={
                "auto_interval_minutes": 30,
                "auto_enabled": False,
                "midnight_enabled": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        settings = db.get_settings()
        self.assertEqual(settings["auto_interval_minutes"], "30")
        self.assertEqual(settings["auto_enabled"], "0")
        self.assertEqual(settings["midnight_enabled"], "1")


if __name__ == "__main__":
    unittest.main()

