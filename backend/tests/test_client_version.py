"""Version comparison, because the obvious implementation is wrong.

`"0.2.10" >= "0.2.3"` is False as strings, and every one of these callers is
deciding whether a client is new enough for a behaviour. Getting it backwards
would silently withhold a feature from exactly the users who had updated —
and it becomes reachable the day a patch number passes nine, which is a
normal Tuesday rather than an edge case.
"""
import pytest

from utils.client_version import client_at_least, parse_version

# Deliberately NOT one of the live gates (config.UPLOAD_LIMIT_MIN_CLIENT,
# config.FIRST_SIGNIN_MIN_CLIENT). This file tests the comparison itself, and
# tying it to a real gate would mean editing it on every release for no gain
# — and would quietly turn a test of the helper into a test of the config.
V023 = (0, 2, 3)


# ── parsing ──


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.2.3", (0, 2, 3)),
        ("0.2.3.1", (0, 2, 3, 1)),   # Chrome allows a fourth part
        ("1.0", (1, 0)),
        ("12", (12,)),
        ("  0.2.3  ", (0, 2, 3)),    # header whitespace
    ],
)
def test_a_version_parses_to_integers(raw, expected):
    assert parse_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None, "", "   ",
        "0.2.3-beta",     # not a Chrome version
        "v0.2.3",         # the tag, not the manifest field
        "0.2.x",
        "0.2.3.4.5",      # more than four parts
        "abc",
        "0..3",
        "999999",         # part too long for the manifest format
        123,              # not even a string
    ],
)
def test_anything_else_is_not_a_version(raw):
    assert parse_version(raw) is None


# ── the comparison ──


def test_the_exact_version_qualifies():
    assert client_at_least("0.2.3", V023) is True


def test_a_newer_version_qualifies():
    assert client_at_least("0.2.4", V023) is True
    assert client_at_least("0.3.0", V023) is True
    assert client_at_least("1.0.0", V023) is True


def test_an_older_version_does_not():
    assert client_at_least("0.2.2", V023) is False
    assert client_at_least("0.1.27", V023) is False


def test_double_digit_patch_numbers_are_not_compared_as_text():
    """The whole reason this module exists rather than a `>=` on strings."""
    assert client_at_least("0.2.10", V023) is True
    assert client_at_least("0.2.9", V023) is True
    assert client_at_least("0.10.0", V023) is True
    assert client_at_least("0.2.30", (0, 2, 4)) is True


def test_a_hotfix_build_is_not_older_than_the_release_it_fixes():
    assert client_at_least("0.2.3.1", V023) is True


def test_a_shorter_version_pads_with_zeros():
    assert client_at_least("0.2", V023) is False
    assert client_at_least("0.3", V023) is True
    assert client_at_least("1", V023) is True


@pytest.mark.parametrize("raw", [None, "", "garbage", "v0.2.3", 0.23])
def test_an_unknown_version_is_treated_as_old(raw):
    """One-directional on purpose. Every caller asks this to decide whether a
    client is new enough for a NEW behaviour, so an unknown answer has to
    mean today's behaviour. There is no reading where guessing 'probably new'
    is the safe half."""
    assert client_at_least(raw, V023) is False


def test_a_zero_minimum_still_needs_a_readable_version():
    """`client_at_least(x, (0,))` is not a way to say 'anything' — an
    unparseable version is still unknown, and a caller writing (0,) is more
    likely to have made a mistake than to mean 'literally everyone'."""
    assert client_at_least("0.0.1", (0,)) is True
    assert client_at_least(None, (0,)) is False
    assert client_at_least("nonsense", (0,)) is False
