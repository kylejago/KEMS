"""Alpha9.190: bounded retries preserve asset safety and maintenance gates."""

import asyncio
import hashlib

import pytest
from kems_core.github_release_assets import download_release_asset


class ClientConnectionError(Exception):
    """Test aiohttp's optional transport exception without importing it."""


ClientConnectionError.__module__ = "aiohttp.client_exceptions"


class Response:
    def __init__(self, status=200, body=b"good", retry=None, failure=None):
        self.status = status
        self.body = body
        self.headers = {"Content-Type": "application/octet-stream"}
        if retry is not None:
            self.headers["Retry-After"] = str(retry)
        self.failure = failure

    async def __aenter__(self):
        if self.failure:
            raise self.failure
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append((url, timeout))
        return next(self.responses)


def request(responses, digest=None):
    session = Session(responses)
    asset = {
        "id": 123,
        "size": 4,
        "digest": digest or "sha256:" + hashlib.sha256(b"good").hexdigest(),
    }

    async def run():
        return await download_release_asset(
            session, asset, repository="kylejago/KEMS", user_agent="KEMS-test"
        )

    return session, run


def test_http_429_short_retry_after_recovers(monkeypatch):
    async def no_delay(seconds):
        assert 0.6 <= seconds <= 3

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", no_delay)
    session, run = request([Response(429, retry=1), Response()])
    assert asyncio.run(run()) == b"good"
    assert len(session.calls) == 2


def test_http_429_long_retry_after_defers_without_second_request(monkeypatch):
    session, run = request([Response(429, retry=120), Response()])
    with pytest.raises(ValueError, match="defer"):
        asyncio.run(run())
    assert len(session.calls) == 1


def test_connection_reset_retries_but_sha_error_never_retries(monkeypatch):
    async def no_delay(seconds):
        assert seconds == 0.6

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", no_delay)
    session, run = request(
        [Response(failure=ClientConnectionError("reset")), Response()]
    )
    assert asyncio.run(run()) == b"good"
    assert len(session.calls) == 2

    session, run = request([Response(), Response()], "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="digest disagrees"):
        asyncio.run(run())
    assert len(session.calls) == 1


def test_403_never_retried_and_repeated_503_is_bounded(monkeypatch):
    async def no_delay(seconds):
        pass

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", no_delay)
    session, run = request([Response(403), Response()])
    with pytest.raises(ValueError, match="403"):
        asyncio.run(run())
    assert len(session.calls) == 1
    session, run = request([Response(503), Response(503)])
    with pytest.raises(ValueError, match="503"):
        asyncio.run(run())
    assert len(session.calls) == 2


def test_http_429_future_http_date_defers_without_repeat_request(monkeypatch):
    """GitHub's RFC HTTP-date must never become an eager 0.6s retry."""

    async def unexpected_sleep(_seconds):
        raise AssertionError("A future Retry-After must defer, not sleep")

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", unexpected_sleep)
    session, run = request(
        [Response(429, retry="Fri, 01 Jan 2099 00:00:00 GMT"), Response()]
    )
    with pytest.raises(ValueError, match="defer to next update check"):
        asyncio.run(run())
    assert len(session.calls) == 1


@pytest.mark.parametrize("retry_after", ["not-an-http-date", "-1", "nan", "inf"])
def test_http_429_invalid_retry_after_never_spins(monkeypatch, retry_after):
    async def unexpected_sleep(_seconds):
        raise AssertionError("Invalid Retry-After must defer immediately")

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", unexpected_sleep)
    session, run = request([Response(429, retry=retry_after), Response()])
    with pytest.raises(ValueError, match="defer to next update check"):
        asyncio.run(run())
    assert len(session.calls) == 1


def test_http_429_past_http_date_can_recover_in_one_bounded_attempt(monkeypatch):
    delays = []

    async def no_delay(seconds):
        delays.append(seconds)

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", no_delay)
    session, run = request(
        [Response(429, retry="Wed, 01 Jan 2020 00:00:00 GMT"), Response()]
    )
    assert asyncio.run(run()) == b"good"
    assert len(session.calls) == 2
    assert delays == [0.6]


def test_http_429_missing_retry_after_keeps_one_bounded_retry(monkeypatch):
    delays = []

    async def no_delay(seconds):
        delays.append(seconds)

    monkeypatch.setattr("kems_core.github_release_assets.asyncio.sleep", no_delay)
    session, run = request([Response(429), Response()])
    assert asyncio.run(run()) == b"good"
    assert len(session.calls) == 2
    assert delays == [0.6]
