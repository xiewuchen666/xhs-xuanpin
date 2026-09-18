import argparse
import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import collector
import db

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR.parent / "web"


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

    @app.post("/api/products/collect")
    def collect():
        try:
            url = collector.validate_url((request.get_json(silent=True) or {}).get("url", ""))
            data = collector.collect_product(url)
            product_id = db.persist(url, data)
            return jsonify(ok=True, product_id=product_id, product=data)
        except (ValueError, RuntimeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except Exception:
            app.logger.exception("collect failed")
            return jsonify(ok=False, error="采集失败，请查看本地日志"), 500

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=17861)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    create_app().run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

