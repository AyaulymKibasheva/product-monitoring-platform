"""Shared resilient HTTP behavior for static websites."""

from __future__ import annotations

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_retrying_session(max_retries: int, backoff_factor: float) -> Session:
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = Session()
    session.headers.update(
        {"User-Agent": "product-monitoring-pipeline/1.0 (portfolio project)"}
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

