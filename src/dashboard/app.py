"""Flask application factory and JSON API for the dashboard."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, render_template, request
from sqlalchemy import Engine

from src.application import PipelineRunner
from src.reports import ReportFilters, build_report, products_csv, products_xlsx
from src.reports.data import _json_default
from src.sources import build_registry, load_source_catalog

from .service import DashboardService


def create_dashboard_app(
    engine: Engine,
    *,
    runner: PipelineRunner | None = None,
    catalog_path: Path | None = None,
) -> Flask:
    app = Flask(__name__)
    service = DashboardService(engine)

    @app.get("/")
    def index() -> str:
        return render_template("dashboard.html")

    @app.get("/health")
    def health() -> Any:
        return jsonify(status="ok")

    @app.get("/api/filters")
    def filters() -> Any:
        return jsonify(service.filters())

    @app.get("/api/overview")
    def overview() -> Any:
        return jsonify(service.overview(request.args.get("organization"), request.args.get("source")))

    @app.get("/api/products")
    def products() -> Any:
        selected = {key: request.args.get(key, "") for key in ("organization", "source", "category", "brand", "search")}
        return jsonify(service.products(selected, limit=request.args.get("limit", 200, type=int)))

    @app.get("/api/products/<int:product_id>/history")
    def product_history(product_id: int) -> Any:
        history = service.product_history(product_id)
        return (jsonify(history), 200) if history else (jsonify(error="product not found"), 404)

    @app.get("/api/runs")
    def runs() -> Any:
        return jsonify(service.runs(request.args.get("organization"), request.args.get("source")))

    @app.get("/api/errors")
    def errors() -> Any:
        return jsonify(service.errors(request.args.get("organization"), request.args.get("source")))

    @app.post("/api/sources/<source_id>/run")
    def run_source(source_id: str) -> Any:
        if runner is None:
            return jsonify(error="manual runs are not available"), 503
        if source_id not in runner.registry.ids():
            return jsonify(error="source not found"), 404
        outcome = runner.run(source_id)
        return jsonify(asdict(outcome)), 200 if outcome.status != "failed" else 502

    @app.get("/api/settings")
    def settings() -> Any:
        return jsonify(service.settings(request.args.get("organization"), request.args.get("source")))

    @app.put("/api/settings/<scope>/<identifier>")
    def update_settings(scope: str, identifier: str) -> Any:
        if scope not in {"organization", "source"}:
            return jsonify(error="scope must be organization or source"), 400
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise ValueError("settings must be an object")
            updated = service.update_settings(scope, identifier, payload)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return (jsonify(settings=updated), 200) if updated is not None else (jsonify(error="record not found"), 404)

    @app.get("/api/export")
    def export() -> Response:
        filters = ReportFilters(
            organization_id=request.args.get("organization"),
            source_id=request.args.get("source"),
            category=request.args.get("category"),
            brand=request.args.get("brand"),
            currency=request.args.get("currency"),
        )
        content = json.dumps(asdict(build_report(engine, filters)), default=_json_default, ensure_ascii=False, indent=2)
        return Response(
            content,
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=monitoring-report.json"},
        )

    @app.get("/api/export/<file_format>")
    def export_file(file_format: str) -> Any:
        filters = ReportFilters(
            organization_id=request.args.get("organization"),
            source_id=request.args.get("source"),
            category=request.args.get("category"),
            brand=request.args.get("brand"),
        )
        rows = build_report(engine, filters).products
        if file_format == "csv":
            return Response(
                products_csv(rows),
                mimetype="text/csv; charset=utf-8",
                headers={"Content-Disposition": "attachment; filename=products.csv"},
            )
        if file_format == "xlsx":
            return Response(
                products_xlsx(rows),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=products.xlsx"},
            )
        return jsonify(error="format must be csv or xlsx"), 400

    @app.post("/api/sources")
    def add_source() -> Any:
        if runner is None or catalog_path is None:
            return jsonify(error="source management is not available"), 503
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise ValueError("source configuration must be an object")
            source = _source_payload(payload, runner.catalog)
            candidate = {"organizations": [], "sources": [source]}
            current = json.loads(catalog_path.read_text(encoding="utf-8"))
            candidate["organizations"] = current.get("organizations", [])
            candidate["sources"] = [*current.get("sources", []), source]
            temporary = catalog_path.with_suffix(".candidate.json")
            temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                catalog = load_source_catalog(temporary)
                probe_registry = build_registry(catalog)
                result = probe_registry.get(source["id"]).collect(max_pages=1)
                if not result.products:
                    detail = result.stats.errors[0] if result.stats.errors else "selectors found no products"
                    raise ValueError(f"source test failed: {detail}")
                new_adapter = probe_registry.get(source["id"])
            finally:
                temporary.unlink(missing_ok=True)
            catalog_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
            runner.registry.register(new_adapter)
            runner.catalog = catalog
            if runner.repository:
                runner.repository.sync_catalog(catalog)
            return jsonify(source_id=source["id"], products_found=len(result.products)), 201
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return jsonify(error=str(exc)), 400

    return app


def _source_payload(payload: dict[str, Any], catalog: Any) -> dict[str, Any]:
    source_id = str(payload.get("id", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", source_id):
        raise ValueError("ID must contain 2-63 lowercase letters, numbers, or hyphens")
    if source_id in {source.source_id for source in catalog.sources}:
        raise ValueError("source ID already exists")
    organization_id = str(payload.get("organization_id", "")).strip()
    catalog.organization(organization_id)
    name = str(payload.get("name", "")).strip()
    urls = payload.get("page_urls")
    selectors = payload.get("selectors")
    if not name or not isinstance(urls, list) or not urls:
        raise ValueError("name and at least one page URL are required")
    clean_urls = [str(url).strip() for url in urls if str(url).strip()]
    if not clean_urls or any(urlparse(url).scheme not in {"http", "https"} for url in clean_urls):
        raise ValueError("only HTTP and HTTPS page URLs are supported")
    if not isinstance(selectors, dict):
        raise ValueError("CSS selectors are required")
    return {
        "id": source_id,
        "organization_id": organization_id,
        "name": name,
        "type": "html",
        "adapter": "configurable_html",
        "base_url": clean_urls[0],
        "default_currency": str(payload.get("default_currency") or "USD").upper(),
        "schedule": str(payload.get("schedule") or "0 */6 * * *"),
        "timeout_seconds": 15,
        "max_retries": 2,
        "active": True,
        "settings": {"page_urls": clean_urls, "selectors": selectors},
    }
