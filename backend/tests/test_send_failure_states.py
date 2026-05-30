"""Tests for failure classification in the send pipeline.

`_classify_failure` maps a Graph send failure (HTTP status code or None for
a network/timeout exception) to a contact status: permanent `failed` vs
transient `deferred`. It lives in utils/send_classify.py and is re-exported
from routers.campaigns for the send loop.
"""
from routers.campaigns import _classify_failure


def test_classify_4xx_is_permanent():
    assert _classify_failure(400) == "failed"
    assert _classify_failure(403) == "failed"
    assert _classify_failure(413) == "failed"


def test_classify_429_is_transient():
    assert _classify_failure(429) == "deferred"


def test_classify_5xx_is_transient():
    assert _classify_failure(500) == "deferred"
    assert _classify_failure(503) == "deferred"


def test_classify_none_is_transient():
    # network/timeout exception → no status_code → transient
    assert _classify_failure(None) == "deferred"
