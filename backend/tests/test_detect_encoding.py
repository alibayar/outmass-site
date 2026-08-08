"""The CSV encoding second opinion.

The extension refuses any file it cannot place from the user's own language,
because the legacy single-byte tables cannot fail on wrong input — a wrong
guess is undetectable and becomes a mangled name in a sent email. Safe, but a
dead end for Turkish, Polish, Baltic, Vietnamese and Western European lists.

This endpoint is the second opinion for exactly that population. Measured on
a 51-file corpus: charset-normalizer got 8 of the 9 files the extension
refuses; a bundled jschardet got 3, at 334 KB and LGPL.

The invariants below are the ones that make it safe to consult at all.
"""
import io

import pytest

from tests.conftest import FAKE_STARTER_USER


def _csv(lang_rows, encoding):
    text = "name,company,email\n" + "".join(
        "%s,Acme Corporation Limited,user%d@example.com\n" % (n, i)
        for i, n in enumerate(lang_rows)
    )
    return text.encode(encoding)


POLISH = ["Łukasz Wójcik", "Małgorzata Nowak", "Grażyna Wiśniewska"] * 8
TURKISH = ["Ayşe Yılmaz", "Çağrı Öztürk", "Mehmet Şimşek"] * 8
RUSSIAN = ["Иван Петров", "Анна Смирнова", "Дмитрий Соколов"] * 8


def _post(client, body):
    import base64

    return client.post(
        "/campaigns/detect-encoding",
        json={"sample_b64": base64.b64encode(body).decode("ascii")},
        headers={"Authorization": "Bearer test"},
    )


def test_returns_a_label_the_browser_can_actually_use(client, auth_bypass):
    """The whole point of the mapping table.

    charset-normalizer answers in Python codec names, and TextDecoder rejects
    them: "utf_8" has an underscore, "cp932" is not a WHATWG label at all.
    Returning those would hand the client a string it cannot use, which is
    worse than returning nothing because the client would have to guess AGAIN
    to recover. Measured the hard way — the first three versions of the
    benchmark harness that produced these numbers each scored correct answers
    as failures for exactly this reason.
    """
    resp = _post(client, _csv(POLISH, "windows-1250"))
    assert resp.status_code == 200
    label = resp.json()["encoding"]
    assert label == "windows-1250", label
    # WHATWG labels are lowercase, hyphenated, and never contain underscores.
    assert "_" not in label and label == label.lower()


@pytest.mark.parametrize(
    "rows,encoding,expected",
    [
        (POLISH, "windows-1250", "windows-1250"),
        (TURKISH, "windows-1254", "windows-1254"),
    ],
)
def test_it_places_the_files_the_extension_refuses(
    client, auth_bypass, rows, encoding, expected
):
    """The Latin codepages, which is the entire population this exists for.

    They are refused locally because they cannot be told apart by inspection:
    every byte of a windows-1250 file is a defined character in windows-1252
    and vice versa, so no rule over the bytes can choose. A frequency model
    trained on real text can, and does.
    """
    resp = _post(client, _csv(rows, encoding))
    assert resp.status_code == 200
    assert resp.json()["encoding"] == expected


def test_the_detector_is_not_trustworthy_on_its_own(client, auth_bypass):
    """Asserted, because it is the reason the UI contract is what it is.

    A Russian windows-1251 list comes back as x-mac-cyrillic — confidently,
    and wrongly; MacCyrillic and windows-1251 disagree on most of the range,
    so acting on it silently would mangle every name. The same corpus showed
    charset-normalizer answering ISO-8859-7 for German and cp1250 for a
    diluted Chinese list, and its own chaos score does not separate its right
    answers from its wrong ones — the ranges overlap completely.

    Two consequences, both deliberate:
      * the result is a SUGGESTION shown against a decoded preview the user
        confirms, never a silent decision;
      * Cyrillic, Arabic, Hebrew, Greek and Thai files never reach here at
        all, because the extension's own rules place them from the user's
        language and only ASK when those rules refuse.

    If this ever starts returning windows-1251 for this input, that is good
    news about the library — but it must not become the reason anyone drops
    the confirmation step.
    """
    resp = _post(client, _csv(RUSSIAN, "windows-1251"))
    assert resp.status_code == 200
    label = resp.json()["encoding"]
    assert label != "windows-1251", (
        "the detector got Cyrillic right this time — update the comment "
        "above, but do NOT take it as licence to trust it unsupervised"
    )
    # Whatever it says, it must still be a label the browser can use.
    assert label is None or ("_" not in label and label == label.lower())


def test_an_encoding_the_browser_cannot_use_becomes_null(client, auth_bypass, monkeypatch):
    """A detection with no WHATWG equivalent must degrade to a refusal.

    This is not hypothetical: on the benchmark corpus charset-normalizer
    answered cp775 (a Baltic DOS codepage) for a French list. cp775 has no
    TextDecoder label, so the only safe answer is null — which puts the user
    back on today's behaviour rather than on an error the client cannot act
    on. It is also the reason that one miss cost nothing.
    """
    from routers import campaigns as campaigns_router

    class _Best:
        encoding = "cp775"

    class _Results:
        def best(self):
            return _Best()

    monkeypatch.setattr(
        "charset_normalizer.from_bytes", lambda _b: _Results(), raising=True
    )
    resp = _post(client, _csv(POLISH, "windows-1250"))
    assert resp.status_code == 200
    assert resp.json()["encoding"] is None
    assert "cp775" not in resp.text


def test_a_sample_is_enough_to_place_the_file(client, auth_bypass):
    """64 KB decides it, which is why the client only sends that much.

    Measured on a 5 MB list: 2521 ms for the whole file, 19 ms for 64 KB,
    same answer. The slow version would also be a denial-of-service
    invitation on an authenticated endpoint taking arbitrary bytes.
    """
    from routers.campaigns import _DETECT_SAMPLE_BYTES

    sample = (_csv(POLISH, "windows-1250") * 2000)[:_DETECT_SAMPLE_BYTES]
    resp = _post(client, sample)
    assert resp.status_code == 200
    body = resp.json()
    assert body["encoding"] == "windows-1250"
    assert body["sampled_bytes"] <= _DETECT_SAMPLE_BYTES


def test_oversize_sample_is_rejected_before_detection(client, auth_bypass):
    """The client slices to 64 KB before sending; anything larger is either a
    bug or someone probing. Either way it does not get decoded."""
    from routers.campaigns import _DETECT_SAMPLE_BYTES

    resp = _post(client, b"x" * (_DETECT_SAMPLE_BYTES + 1))
    assert resp.status_code == 413


def test_a_body_that_is_not_base64_is_a_400(client, auth_bypass):
    resp = client.post(
        "/campaigns/detect-encoding",
        json={"sample_b64": "not base64 at all !!!"},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 400


def test_empty_sample_is_a_400(client, auth_bypass):
    assert _post(client, b"").status_code == 400


def test_a_detector_fault_never_breaks_the_upload(client, auth_bypass, monkeypatch):
    """This endpoint is the extra mile, not the road.

    The client's own chain already handled every common case before it asks;
    a library fault here must degrade to "no opinion", never to a 500 that
    the sidebar has to interpret.
    """
    def _boom(_b):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("charset_normalizer.from_bytes", _boom, raising=True)
    resp = _post(client, _csv(POLISH, "windows-1250"))
    assert resp.status_code == 200
    assert resp.json()["encoding"] is None


def test_the_response_carries_no_file_content(client, auth_bypass):
    """The bytes are a customer's contact list — real names, real addresses.

    The response may say what the file IS, never what it CONTAINS. Anything
    added to this endpoint later has to keep that true, so it is asserted
    rather than left to good intentions.
    """
    resp = _post(client, _csv(POLISH, "windows-1250"))
    text = resp.text
    for leak in ("Łukasz", "Wójcik", "user0@example.com", "Acme"):
        assert leak not in text
    assert set(resp.json()) == {"encoding", "sampled_bytes"}


def test_it_requires_authentication(client):
    """An unauthenticated decode oracle that accepts arbitrary bytes is not
    something to leave open."""
    import base64

    resp = client.post(
        "/campaigns/detect-encoding",
        json={"sample_b64": base64.b64encode(_csv(POLISH, "windows-1250")).decode("ascii")},
    )
    assert resp.status_code in (401, 403, 422)
