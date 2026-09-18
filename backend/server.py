import argparse
import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import collector
import db

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR.parent / "web"


def _api_error(message: str, status: int = 400):
    return jsonify(ok=False, error=message), status


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = testing
    db.init_db()

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/app.js")
    def script():
        return send_from_directory(WEB_DIR, "app.js")

    @app.get("/health")
    def health():
        return jsonify(ok=True)

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

    @app.post("/api/products/collect")
    def collect():
        try:
            body = request.get_json(silent=True) or {}
            scope = str(body.get("scope") or "single").strip()
            if scope not in {"single", "selection"}:
                return _api_error("无效加入范围")
            url = collector.validate_url(body.get("url", ""))
            data = collector.collect_product(url)
            product_id = db.persist(url, data, join_single=(scope == "single"))
            if scope == "selection":
                db.add_selection(product_id)
            return jsonify(ok=True, product_id=product_id, product=data, scope=scope)
        except (ValueError, RuntimeError) as exc:
            return _api_error(str(exc))
        except Exception:
            app.logger.exception("collect failed")
            return _api_error("采集失败，请查看本地日志", 500)

    @app.post("/api/products/<int:product_id>/collect")
    def collect_one(product_id: int):
        try:
            product = db.get_product(product_id)
            if not product or not db.is_in_single_monitor(product_id):
                return _api_error("商品不在单品监控中", 404)
            if product.get("monitor_state") != "active":
                return _api_error("商品已暂停，请先恢复监控", 409)

            url = collector.validate_url(product.get("url", ""))
            data = collector.collect_product(url)
            db.persist(
                url,
                data,
                join_single=False,
                expected_product_id=product_id,
            )
            return jsonify(ok=True, product_id=product_id, product=data)
        except (ValueError, RuntimeError) as exc:
            return _api_error(str(exc))
        except Exception:
            app.logger.exception("collect one failed")
            return _api_error("采集失败，请查看本地日志", 500)

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=17861)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    create_app().run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
