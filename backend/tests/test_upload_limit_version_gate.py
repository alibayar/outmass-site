"""The CSV ceiling is decided by the client, not by a switch we must remember.

A list larger than the monthly quota is accepted in full and sent over
several months. Only 0.2.3 says how many months; an older panel implies the
remainder clears at the next reset, which would be a promise we do not keep —
so an older panel keeps the per-plan limits it knows how to describe.

This replaced a condition nothing could evaluate. UPLOAD_LIMIT_FOLLOWS_QUOTA
was owed a flip "once 0.2.3 is published on both stores and most people have
updated", which is not a thing a program can check and is exactly the kind of
debt that gets paid late or not at all. The version is in the request already
(X-Extension-Version, sent by backendFetch on every authenticated call), so
the question is asked per call instead.

The flag survives as a one-directional override: true means the new ceiling
for everyone. It can widen and never narrow, so leaving it alone is always
safe.
"""
from unittest.mock import patch

import pytest

import config
from config import (
    CSV_UPLOAD_ROW_LIMIT,
    FREE_UPLOAD_ROW_LIMIT,
    PRO_UPLOAD_ROW_LIMIT,
    STARTER_UPLOAD_ROW_LIMIT,
    upload_limit_for_plan,
)

NEW = "0.2.3"
OLD = "0.2.2"


@pytest.fixture(autouse=True)
def _flag_off():
    """Every test here is about the version, so the override stays down."""
    with patch.object(config, "UPLOAD_LIMIT_FOLLOWS_QUOTA", False):
        yield


# ── an older panel keeps what it can explain ──


@pytest.mark.parametrize(
    "plan,expected",
    [
        ("free", FREE_UPLOAD_ROW_LIMIT),
        ("starter", STARTER_UPLOAD_ROW_LIMIT),
        ("pro", PRO_UPLOAD_ROW_LIMIT),
        (None, FREE_UPLOAD_ROW_LIMIT),
        ("nonsense", FREE_UPLOAD_ROW_LIMIT),
    ],
)
def test_an_older_client_gets_the_per_plan_limits(plan, expected):
    assert upload_limit_for_plan(plan, OLD) == expected


def test_no_version_at_all_is_an_older_client():
    """A build we cannot identify is one we cannot vouch for."""
    assert upload_limit_for_plan("free") == FREE_UPLOAD_ROW_LIMIT
    assert upload_limit_for_plan("free", None) == FREE_UPLOAD_ROW_LIMIT
    assert upload_limit_for_plan("free", "") == FREE_UPLOAD_ROW_LIMIT
    assert upload_limit_for_plan("free", "garbage") == FREE_UPLOAD_ROW_LIMIT


# ── a panel that can explain it gets the ceiling ──


@pytest.mark.parametrize("plan", ["free", "starter", "pro", None])
def test_a_new_client_gets_the_single_ceiling_whatever_the_plan(plan):
    """The point of the change: the quota does the gating, not the upload."""
    assert upload_limit_for_plan(plan, NEW) == CSV_UPLOAD_ROW_LIMIT


def test_a_double_digit_patch_is_not_read_as_older():
    """String comparison would put "0.2.10" below "0.2.3" and withhold the
    ceiling from precisely the people who had updated furthest."""
    assert upload_limit_for_plan("free", "0.2.10") == CSV_UPLOAD_ROW_LIMIT
    assert upload_limit_for_plan("free", "0.3.0") == CSV_UPLOAD_ROW_LIMIT
    assert upload_limit_for_plan("free", "1.0.0") == CSV_UPLOAD_ROW_LIMIT


# ── the override only ever widens ──


def test_the_flag_lifts_the_ceiling_for_an_older_client_too():
    with patch.object(config, "UPLOAD_LIMIT_FOLLOWS_QUOTA", True):
        assert upload_limit_for_plan("free", OLD) == CSV_UPLOAD_ROW_LIMIT
        assert upload_limit_for_plan("free", None) == CSV_UPLOAD_ROW_LIMIT


def test_the_flag_cannot_take_the_ceiling_away_from_a_new_client():
    """One-directional. There is no combination of flag and version that
    gives a 0.2.3 client less than the ceiling, so nothing about leaving the
    flag alone can hurt anyone."""
    for flag in (True, False):
        with patch.object(config, "UPLOAD_LIMIT_FOLLOWS_QUOTA", flag):
            assert upload_limit_for_plan("free", NEW) == CSV_UPLOAD_ROW_LIMIT


# ── and the panel is told the number it will be held to ──


def test_settings_quotes_the_limit_that_will_be_enforced(client, fake_db, auth_bypass):
    """The panel draws its upload limit from /settings and then enforces it
    client-side before the file is read. If /settings answered with a number
    the upload endpoint would not honour, the panel would refuse a file the
    server would have taken — or take one it would refuse."""
    old = client.get("/settings", headers={"X-Extension-Version": OLD})
    new = client.get("/settings", headers={"X-Extension-Version": NEW})

    assert old.status_code == 200 and new.status_code == 200
    assert new.json()["upload_limit"] == CSV_UPLOAD_ROW_LIMIT
    assert old.json()["upload_limit"] != CSV_UPLOAD_ROW_LIMIT or (
        CSV_UPLOAD_ROW_LIMIT == FREE_UPLOAD_ROW_LIMIT
    ), "the two builds were told the same number; the header is not reaching /settings"


def test_settings_without_the_header_answers_conservatively(
    client, fake_db, auth_bypass
):
    resp = client.get("/settings")
    assert resp.status_code == 200
    plan_limit = {
        "pro": PRO_UPLOAD_ROW_LIMIT,
        "starter": STARTER_UPLOAD_ROW_LIMIT,
    }.get(resp.json()["plan"], FREE_UPLOAD_ROW_LIMIT)
    assert resp.json()["upload_limit"] == plan_limit
