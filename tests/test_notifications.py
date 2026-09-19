from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.database import ProductRepository, create_schema
from src.database.models import NotificationDeliveryRow
from src.models import Availability, Organization, Product, SourceDefinition, SourceType
from src.notifications import EmailChannel, NotificationDispatcher, NotificationMessage, SlackChannel
from src.sources import SourceCatalog, SourceRunResult, SourceRunStats
from src.validation import ProductValidator


class Recorder:
    def __init__(self, messages: list[NotificationMessage], *, fail: bool = False) -> None:
        self.messages = messages
        self.fail = fail

    def send(self, message: NotificationMessage) -> None:
        if self.fail:
            raise RuntimeError("temporary delivery error")
        self.messages.append(message)


def catalog(*, minimum: int = 0, frequency: str = "immediate", events=None) -> SourceCatalog:
    channels = ({"id": "mail", "name": "Mail", "type": "email", "recipient": "a@example.test"},)
    rules = ({
        "id": "important",
        "name": "Important events",
        "events": events or ["price_drop", "source_failed", "data_quality_problem"],
        "channel_ids": ["mail"],
        "minimum_price_change_percent": minimum,
        "frequency": frequency,
    },)
    return SourceCatalog(
        organizations=(Organization("org", "Company", notification_rules=rules, notification_channels=channels),),
        sources=(SourceDefinition("source", "org", "Supplier", SourceType.API, "fake"),),
    )


def item(price: str, *, name: str = "Item") -> Product:
    return Product(
        organization_id="org", source_id="source", external_id="sku-1", name=name,
        category="Hardware", brand="Acme", price=Decimal(price), currency="USD",
        availability=Availability.IN_STOCK, url="https://example.test/item",
        collected_at=datetime.now(timezone.utc),
    )


def save(repository: ProductRepository, product: Product) -> int:
    result = SourceRunResult("org", "source", [product], SourceRunStats(records_found=1, records_processed=1))
    return repository.save_run(result, ProductValidator().validate_batch([product]), started_at=datetime.now(timezone.utc))


def setup_repository(config: SourceCatalog):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    repository = ProductRepository(engine)
    repository.sync_catalog(config)
    return engine, repository


def test_price_rule_sends_once_and_deduplicates() -> None:
    engine, repository = setup_repository(catalog(minimum=5))
    messages: list[NotificationMessage] = []
    dispatcher = NotificationDispatcher(engine, channel_factory=lambda *_: Recorder(messages))
    save(repository, item("100"))
    run_id = save(repository, item("90"))

    assert dispatcher.process_run(run_id) == 1
    assert dispatcher.process_run(run_id) == 0
    assert len(messages) == 1
    assert "PRICE DROP" in messages[0].subject
    assert "100.0000 -> 90" in messages[0].body
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(NotificationDeliveryRow)) == 1


def test_threshold_and_hourly_frequency_delay_delivery() -> None:
    engine, repository = setup_repository(catalog(minimum=5, frequency="hourly"))
    messages: list[NotificationMessage] = []
    dispatcher = NotificationDispatcher(engine, channel_factory=lambda *_: Recorder(messages))
    save(repository, item("100"))
    run_id = save(repository, item("90"))

    assert dispatcher.process_run(run_id) == 0
    assert messages == []
    assert dispatcher.dispatch_pending(now=datetime.now(timezone.utc) + timedelta(hours=2)) == 1


def test_below_threshold_creates_no_delivery() -> None:
    engine, repository = setup_repository(catalog(minimum=20))
    dispatcher = NotificationDispatcher(engine, channel_factory=lambda *_: Recorder([]))
    save(repository, item("100"))
    run_id = save(repository, item("90"))
    assert dispatcher.process_run(run_id) == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(NotificationDeliveryRow)) == 0


def test_failed_source_is_retried_then_marked_failed() -> None:
    engine, repository = setup_repository(catalog(events=["source_failed"]))
    dispatcher = NotificationDispatcher(
        engine, channel_factory=lambda *_: Recorder([], fail=True), max_attempts=2
    )
    run_id = repository.save_failed_run(
        "source", started_at=datetime.now(timezone.utc), error=RuntimeError("offline")
    )
    assert dispatcher.process_run(run_id) == 0
    with Session(engine) as session:
        delivery = session.scalar(select(NotificationDeliveryRow))
        assert delivery.status == "retry"
        assert delivery.attempts == 1
    dispatcher.dispatch_pending(now=datetime.now(timezone.utc) + timedelta(minutes=2))
    with Session(engine) as session:
        delivery = session.scalar(select(NotificationDeliveryRow))
        assert delivery.status == "failed"
        assert delivery.attempts == 2
        assert "temporary delivery error" in delivery.last_error


def test_validation_errors_create_data_quality_event() -> None:
    engine, repository = setup_repository(catalog(events=["data_quality_problem"]))
    messages: list[NotificationMessage] = []
    dispatcher = NotificationDispatcher(engine, channel_factory=lambda *_: Recorder(messages))
    invalid = item("-1")
    result = SourceRunResult(
        "org", "source", [invalid], SourceRunStats(records_found=1, records_processed=1)
    )
    run_id = repository.save_run(
        result,
        ProductValidator().validate_batch([invalid]),
        started_at=datetime.now(timezone.utc),
    )
    assert dispatcher.process_run(run_id) == 1
    assert "DATA QUALITY PROBLEM" in messages[0].subject


def test_email_channel_uses_environment_and_smtp(monkeypatch) -> None:
    calls = []

    class SMTP:
        def __init__(self, host, port, timeout): calls.append((host, port, timeout))
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def starttls(self): calls.append("tls")
        def login(self, username, password): calls.append((username, password))
        def send_message(self, message): calls.append(message)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "monitor@example.test")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("src.notifications.channels.smtplib.SMTP", SMTP)
    EmailChannel("team@example.test", {}).send(NotificationMessage("Alert", "Body"))
    assert calls[0] == ("smtp.example.test", 587, 20)
    assert calls[-1]["To"] == "team@example.test"


def test_slack_channel_posts_webhook(monkeypatch) -> None:
    posted = {}

    class Response:
        def raise_for_status(self): posted["checked"] = True

    def post(url, **kwargs):
        posted.update(url=url, **kwargs)
        return Response()

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setattr("src.notifications.channels.requests.post", post)
    SlackChannel({}).send(NotificationMessage("Alert", "Body"))
    assert posted["url"] == "https://hooks.slack.test/abc"
    assert posted["json"] == {"text": "*Alert*\nBody"}
    assert posted["checked"] is True
