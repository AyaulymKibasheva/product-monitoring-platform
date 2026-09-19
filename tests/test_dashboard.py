from datetime import datetime, timezone
from decimal import Decimal
import json

import responses

from sqlalchemy import create_engine

from src.dashboard import create_dashboard_app
from src.application import PipelineRunner
from src.database import ProductRepository, create_schema
from src.models import Availability, Organization, Product, SourceDefinition, SourceType
from src.sources import SourceCatalog, SourceRunResult, SourceRunStats
from src.sources import SourceRegistry
from src.validation import ProductValidator


def dashboard_client():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    catalog = SourceCatalog(
        organizations=(Organization("org", "Acme Company"),),
        sources=(SourceDefinition("api", "org", "Supplier API", SourceType.API, "fake"),),
    )
    repository.sync_catalog(catalog)
    first = Product(
        organization_id="org", source_id="api", external_id="p-1", name="Universal Widget",
        category="Equipment", brand="Acme", price=Decimal("100"), currency="USD",
        availability=Availability.IN_STOCK, url="https://example.test/p-1",
        collected_at=datetime.now(timezone.utc), sku="W-1",
    )
    second = Product(
        organization_id="org", source_id="api", external_id="p-1", name="Universal Widget",
        category="Equipment", brand="Acme", price=Decimal("90"), currency="USD",
        availability=Availability.OUT_OF_STOCK, url="https://example.test/p-1",
        collected_at=datetime.now(timezone.utc), sku="W-1",
    )
    for product in (first, second):
        result = SourceRunResult("org", "api", [product], SourceRunStats(records_found=1, records_processed=1))
        repository.save_run(result, ProductValidator().validate_batch([product]), started_at=datetime.now(timezone.utc))
    app = create_dashboard_app(engine)
    app.config["TESTING"] = True
    return app.test_client()


def test_dashboard_page_and_health() -> None:
    client = dashboard_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Monitoring dashboard" in response.data
    assert client.get("/health").json == {"status": "ok"}


def test_dashboard_overview_filters_and_product_history() -> None:
    client = dashboard_client()
    overview = client.get("/api/overview?organization=org&source=api").json
    assert overview["organizations"] == 1
    assert overview["sources"] == 1
    assert overview["products"] == 1
    assert overview["price_drops"] == 1
    assert overview["out_of_stock"] == 1
    products = client.get("/api/products?search=Widget&category=Equipment").json
    assert len(products) == 1
    assert products[0]["price"] == 90.0
    history = client.get(f"/api/products/{products[0]['id']}/history").json
    assert len(history["prices"]) == 2
    assert len(history["availability"]) == 2
    assert client.get("/api/products/999/history").status_code == 404


def test_dashboard_runs_errors_export_and_manual_run_guard() -> None:
    client = dashboard_client()
    assert len(client.get("/api/runs").json) == 2
    assert client.get("/api/errors").json == []
    export = client.get("/api/export?organization=org")
    assert export.status_code == 200
    assert export.headers["Content-Disposition"].endswith("monitoring-report.json")
    csv_export = client.get("/api/export/csv?organization=org")
    assert csv_export.status_code == 200
    assert csv_export.headers["Content-Disposition"].endswith("products.csv")
    xlsx_export = client.get("/api/export/xlsx?organization=org")
    assert xlsx_export.status_code == 200
    assert xlsx_export.data.startswith(b"PK")
    assert client.get("/api/export/pdf").status_code == 400
    assert client.post("/api/sources/api/run").status_code == 503
    assert client.post("/api/sources", json={}).status_code == 503


def test_dashboard_updates_monitoring_settings() -> None:
    client = dashboard_client()
    response = client.put(
        "/api/settings/organization/org",
        json={"minimum_price_change_percent": 7},
    )
    assert response.status_code == 200
    assert client.get("/api/settings?organization=org").json["organization"] == {
        "minimum_price_change_percent": 7
    }
    assert client.put(
        "/api/settings/source/api", json={"minimum_price_change": -1}
    ).status_code == 400
    assert client.put("/api/settings/invalid/org", json={}).status_code == 400
    assert client.put("/api/settings/source/missing", json={}).status_code == 404


@responses.activate
def test_dashboard_tests_and_connects_configurable_source(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    catalog = SourceCatalog(
        organizations=(Organization("org", "Acme Company"),), sources=()
    )
    runner = PipelineRunner(SourceRegistry(), catalog, engine=engine)
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps({"organizations": [{"id": "org", "name": "Acme Company"}], "sources": []}),
        encoding="utf-8",
    )
    responses.get(
        "https://shop.test/catalog",
        body='<div class="product"><a href="/p/1"><b>Widget</b></a><i>$10</i></div>',
    )
    app = create_dashboard_app(engine, runner=runner, catalog_path=path)
    app.config["TESTING"] = True
    client = app.test_client()
    response = client.post(
        "/api/sources",
        json={
            "id": "client-shop",
            "organization_id": "org",
            "name": "Client Shop",
            "page_urls": ["https://shop.test/catalog"],
            "selectors": {"item": ".product", "name": "b", "price": "i", "url": "a"},
        },
    )
    assert response.status_code == 201
    assert response.json == {"source_id": "client-shop", "products_found": 1}
    assert "client-shop" in runner.registry.ids()
    assert json.loads(path.read_text(encoding="utf-8"))["sources"][0]["adapter"] == "configurable_html"


def test_dashboard_rejects_invalid_source_configuration(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    catalog = SourceCatalog(organizations=(Organization("org", "Acme"),), sources=())
    runner = PipelineRunner(SourceRegistry(), catalog, engine=engine)
    path = tmp_path / "sources.json"
    path.write_text('{"organizations":[{"id":"org","name":"Acme"}],"sources":[]}', encoding="utf-8")
    app = create_dashboard_app(engine, runner=runner, catalog_path=path)
    app.config["TESTING"] = True
    response = app.test_client().post("/api/sources", json={"id": "BAD ID"})
    assert response.status_code == 400
    assert "ID must" in response.json["error"]
