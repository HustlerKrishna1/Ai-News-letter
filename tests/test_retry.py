"""Tests for the retry decorator."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from modules.retry import with_retry


def test_retry_succeeds_after_transient_failure():
    mock = MagicMock(side_effect=[
        requests.ConnectionError("boom"),
        requests.Timeout("slow"),
        "ok",
    ])

    @with_retry(attempts=3, base_delay=0.0)
    def call() -> str:
        return mock()

    assert call() == "ok"
    assert mock.call_count == 3


def test_retry_exhausted_raises_last_error():
    @with_retry(attempts=2, base_delay=0.0)
    def call() -> None:
        raise requests.ConnectionError("always fails")

    with pytest.raises(requests.ConnectionError):
        call()


def test_retry_does_not_swallow_client_error():
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 404
    err = requests.HTTPError("not found", response=resp)

    calls = {"n": 0}

    @with_retry(attempts=5, base_delay=0.0)
    def call() -> None:
        calls["n"] += 1
        raise err

    with pytest.raises(requests.HTTPError):
        call()
    assert calls["n"] == 1  # 4xx is not retried


def test_retry_retries_5xx():
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 503
    err = requests.HTTPError("svc unavailable", response=resp)

    calls = {"n": 0}

    @with_retry(attempts=3, base_delay=0.0)
    def call() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise err
        return "recovered"

    assert call() == "recovered"
    assert calls["n"] == 3
