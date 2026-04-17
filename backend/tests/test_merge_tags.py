"""Tests for merge-tag validation helpers."""
from utils.merge_tags import (
    find_malformed_tags,
    find_unknown_tags,
    STANDARD_TAGS,
)


def test_find_malformed_tags_detects_missing_close_brace():
    # Missing closing brace — will land in recipient's inbox
    result = find_malformed_tags("Hello {{firstName}")
    assert len(result) == 1
    assert "firstName" in result[0]


def test_find_malformed_tags_detects_missing_open_brace():
    result = find_malformed_tags("Hello firstName}}")
    assert len(result) == 1
    assert "firstName" in result[0]


def test_find_malformed_tags_single_brace_ignored():
    # A lone { or } without a partner is not a "tag" — just text
    assert find_malformed_tags("Price: $5 { off }") == []


def test_find_malformed_tags_empty_tag():
    # {{}} is malformed
    result = find_malformed_tags("Hello {{}}")
    assert result == ["{{}}"]


def test_find_malformed_tags_clean_template():
    assert find_malformed_tags("Hi {{firstName}}, welcome {{lastName}}.") == []


def test_find_malformed_tags_empty_input():
    assert find_malformed_tags("") == []


def test_find_unknown_tags_flags_missing_context_key():
    ctx_keys = {"firstName", "email"}
    result = find_unknown_tags("Hi {{firstName}} at {{unknownField}}", ctx_keys)
    assert result == ["unknownField"]


def test_find_unknown_tags_standard_sender_tags_always_ok():
    # senderName etc. are always resolvable from user profile
    result = find_unknown_tags("From {{senderName}}", set())
    assert result == []


def test_find_unknown_tags_multiple_unknowns_deduplicated():
    result = find_unknown_tags("{{foo}} {{bar}} {{foo}}", set())
    assert sorted(result) == ["bar", "foo"]


def test_find_unknown_tags_handles_empty_template():
    assert find_unknown_tags("", {"firstName"}) == []


def test_find_unknown_tags_standard_contact_tags_ok_even_without_csv_key():
    # firstName / lastName etc. are standard (always present after bulk_insert)
    assert find_unknown_tags("Hi {{firstName}}", set()) == []


def test_standard_tags_includes_all_documented():
    for key in (
        "firstName", "lastName", "email", "company", "position",
        "senderName", "senderPosition", "senderCompany", "senderPhone",
    ):
        assert key in STANDARD_TAGS
