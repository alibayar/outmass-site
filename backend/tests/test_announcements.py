from models import announcement as ann
from tests.conftest import FakeQueryBuilder


def test_fake_upsert_sets_data():
    qb = FakeQueryBuilder()
    qb.upsert({"announcement_id": "a", "user_id": "u", "read_at": "now"})
    assert qb.execute().data == [{"announcement_id": "a", "user_id": "u", "read_at": "now"}]


def _row(**kw):
    base = {
        "id": "ann-1", "audience": "broadcast", "user_id": None,
        "priority": "normal", "title": "Hi", "body": "Body",
        "cta_label": None, "cta_url": None, "version": None,
        "starts_at": "2020-01-01T00:00:00Z", "expires_at": None,
        "active": True, "created_at": "2026-06-02T00:00:00Z",
    }
    base.update(kw)
    return base


def test_visible_includes_broadcast(fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    out = ann.get_user_announcements("user-X")
    assert len(out) == 1
    assert out[0]["read"] is False and out[0]["dismissed"] is False


def test_targeted_only_visible_to_owner(fake_db):
    rows = [_row(id="t1", audience="targeted", user_id="owner")]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    assert ann.get_user_announcements("owner")
    assert ann.get_user_announcements("someone-else") == []


def test_dismissed_excluded(fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder(
        [{"announcement_id": "ann-1", "user_id": "u", "read_at": None,
          "dismissed_at": "2026-06-02T01:00:00Z"}]))
    assert ann.get_user_announcements("u") == []


def test_inactive_and_expired_excluded(fake_db):
    rows = [
        _row(id="inactive", active=False),
        _row(id="expired", expires_at="2020-02-01T00:00:00Z"),
        _row(id="future", starts_at="2999-01-01T00:00:00Z"),
    ]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    assert ann.get_user_announcements("u") == []


def test_summary_counts_unread_and_picks_banner(fake_db):
    rows = [
        _row(id="n", priority="normal"),
        _row(id="h", priority="high", title="Gift"),
    ]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    summary = ann.get_summary_for_user("u")
    assert summary["unread"] == 2
    assert summary["banner"]["id"] == "h"


def test_version_tagged_not_server_filtered(fake_db):
    """The `version` field is gated by the client (it has the manifest),
    NOT the server. A version-tagged row must still be returned regardless
    of value — this pins the contract so nobody adds server-side filtering."""
    fake_db.set_table("announcements", FakeQueryBuilder([_row(version="9.9.9")]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    out = ann.get_user_announcements("u")
    assert len(out) == 1 and out[0]["version"] == "9.9.9"


def test_mixed_audience_feed(fake_db):
    """A realistic feed: broadcast + targeted-to-me + targeted-to-other.
    'me' sees exactly the broadcast and my own targeted item."""
    rows = [
        _row(id="b", audience="broadcast", user_id=None),
        _row(id="mine", audience="targeted", user_id="me"),
        _row(id="theirs", audience="targeted", user_id="other"),
    ]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    ids = {a["id"] for a in ann.get_user_announcements("me")}
    assert ids == {"b", "mine"}


def test_get_announcements_endpoint(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.get("/announcements")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["announcements"][0]["title"] == "Hi"


def test_get_announcements_unauthorized(client):
    assert client.get("/announcements").status_code in (401, 422)


def test_mark_read_endpoint(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.post("/announcements/ann-1/read")
    assert resp.status_code == 200
    assert resp.json()["status"] == "read"


def test_mark_read_unknown_returns_404(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.post("/announcements/nope/read")
    assert resp.status_code == 404


def test_dismiss_endpoint(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.post("/announcements/ann-1/dismiss")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"
