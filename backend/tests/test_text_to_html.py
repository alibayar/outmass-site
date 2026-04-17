"""Tests for _text_to_html — plain-text to HTML conversion for outbound email."""
from routers.campaigns import _text_to_html


def test_preserves_existing_html():
    body = "<p>Hello <strong>{{firstName}}</strong></p><p>Regards</p>"
    assert _text_to_html(body) == body


def test_plain_text_single_line_wraps_in_p():
    assert _text_to_html("Hello there") == "<p>Hello there</p>"


def test_plain_text_paragraphs_split_on_blank_line():
    body = "Hi John\n\nWelcome to OutMass\n\nCheers"
    out = _text_to_html(body)
    assert out == "<p>Hi John</p><p>Welcome to OutMass</p><p>Cheers</p>"


def test_plain_text_single_newline_becomes_br():
    body = "Line 1\nLine 2"
    assert _text_to_html(body) == "<p>Line 1<br>Line 2</p>"


def test_mixed_single_and_double_newlines():
    body = "Hi John\n\nLine A\nLine B\n\nBye"
    out = _text_to_html(body)
    assert out == "<p>Hi John</p><p>Line A<br>Line B</p><p>Bye</p>"


def test_escapes_html_special_chars_in_plain_text():
    body = "Price < 10 & quantity > 5"
    assert _text_to_html(body) == "<p>Price &lt; 10 &amp; quantity &gt; 5</p>"


def test_crlf_normalized():
    body = "Line 1\r\n\r\nLine 2"
    assert _text_to_html(body) == "<p>Line 1</p><p>Line 2</p>"


def test_empty_body_returns_empty():
    assert _text_to_html("") == ""


def test_html_detection_is_tag_not_literal_lt():
    # "3 < 5" is plain text — no actual tag — should be escaped.
    body = "3 < 5 is true"
    assert _text_to_html(body) == "<p>3 &lt; 5 is true</p>"


def test_html_passthrough_preserves_merge_tags():
    # {{firstName}} resolves before this function; but if author wrote HTML,
    # we must not mangle it.
    body = '<a href="https://example.com">Click</a>'
    assert _text_to_html(body) == body
