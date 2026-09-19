"""Flask application factory and JSON API for the dashboard."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from sqlalchemy import Engine

from src.application import PipelineRunner
from src.reports import ReportFilters, build_report
from src.reports.data import _json_default

from .service import DashboardService


def create_dashboard_app(engine: Engine, *, runner: PipelineRunner | None = None) -> Flask:
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
            updated = service.update_settings(scope, identifier, request.get_json(silent=True))
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

    return app
