"""Reply detection must read one user's contacts, not the first page of everyone's.

The contacts query used to carry no user filter and no limit. PostgREST capped
it at SUPABASE_MAX_ROWS and returned the first rows of the WHOLE table, and the
code then narrowed them to the user's own campaigns in memory. So every user
scanned the same global page, and anyone whose contacts fell outside it was
invisible to reply detection. Across 2,795 recipients emailed in a recent
30-day window, that was most of them.

Two consequences. The reply rate in Reports understated the truth for the whole
base — and, the one that reaches a person, followup_worker excludes contacts by
replied_at, so a missed reply means chasing somebody who already answered.

Same defect class as commit 01e18bb, which fixed the send close-out and did not
touch this file.

These tests pin the ordering rather than the numbers: campaigns first, contacts
scoped to them. That ordering is what makes the read small enough to fit in a
page at all, so it cannot be rearranged back without failing here.
"""
from unittest.mock import MagicMock, patch


class _Table:
    """Records the filters applied to it and returns what it was given."""

    def __init__(self, rows, log, name):
        self._rows, self._log, self._name = rows, log, name
        self.filters = {}

    def select(self, *a, **kw):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = list(vals)
        return self

    def gte(self, *a):
        return self

    def is_(self, *a):
        return self

    def limit(self, n):
        self.filters["__limit"] = n
        return self

    def update(self, vals):
        self.filters["__update"] = vals
        return self

    def execute(self):
        self._log.append((self._name, dict(self.filters)))
        return MagicMock(data=self._rows)


def _run(campaign_rows, contact_rows):
    """One reply scan for user 'u1', capturing every query it makes."""
    from workers import reply_detector

    log = []

    def _table(name):
        if name == "campaigns":
            return _Table(campaign_rows, log, "campaigns")
        if name == "contacts":
            return _Table(contact_rows, log, "contacts")
        return _Table([], log, name)

    db = MagicMock()
    db.table.side_effect = _table

    with patch("workers.reply_detector._list_recent_messages", return_value=[]):
        stamped = reply_detector._find_replies_for_user(
            db, "u1", "owner@example.com", "tok"
        )
    return stamped, log


def test_the_contact_read_is_scoped_to_this_user_s_campaigns():
    """The whole fix in one assertion.

    Without campaign_id on the contacts query, this scan reads the first page
    of the contacts table — every user's, in whatever order the server likes —
    and finds this user's recipients only if they happen to be in it.
    """
    _, log = _run(
        campaign_rows=[{"id": "camp-a"}, {"id": "camp-b"}],
        contact_rows=[],
    )

    names = [n for n, _ in log]
    assert names[0] == "campaigns", (
        f"campaigns must be read FIRST so the contact query can be scoped by "
        f"them; query order was {names}"
    )

    contact_queries = [f for n, f in log if n == "contacts"]
    assert contact_queries, "no contacts query was made at all"
    for f in contact_queries:
        assert "campaign_id" in f, (
            "the contacts read carries no campaign_id filter — it is reading "
            "the whole table and relying on a page boundary to stop"
        )
        assert set(f["campaign_id"]) <= {"camp-a", "camp-b"}, (
            f"the contacts read asked for campaigns this user does not own: "
            f"{f['campaign_id']}"
        )
        assert f.get("__limit"), (
            "the contacts read has no explicit limit — PostgREST applies one "
            "silently, and a silent ceiling is what this file is being fixed for"
        )


def test_a_user_with_no_campaigns_does_not_query_contacts_at_all():
    """Nothing to scope by means nothing to scan — and, crucially, it must not
    fall back to an unscoped read."""
    stamped, log = _run(campaign_rows=[], contact_rows=[{"id": "x"}])

    assert stamped == 0
    assert not [n for n, _ in log if n == "contacts"], (
        "a user with no campaigns still read the contacts table — that read "
        "can only be unscoped"
    )


def test_many_campaigns_are_chunked_rather_than_sent_as_one_url():
    """PostgREST puts the id list in the query string.

    A user with hundreds of campaigns would otherwise build a URL long enough
    for something in the middle to refuse it, and the scan would fail for
    exactly the heaviest users.
    """
    from workers.reply_detector import CAMPAIGN_ID_CHUNK

    # The bound itself, not just the arithmetic around it. This test builds its
    # own input from the constant, so without this line any value passes —
    # including one large enough to put every id back in a single URL, which is
    # the thing chunking exists to prevent.
    assert 1 < CAMPAIGN_ID_CHUNK <= 200, (
        f"CAMPAIGN_ID_CHUNK is {CAMPAIGN_ID_CHUNK}; PostgREST puts the id list "
        f"in the query string, so a chunk this size defeats the point"
    )

    many = [{"id": f"camp-{i}"} for i in range(CAMPAIGN_ID_CHUNK + 5)]
    _, log = _run(campaign_rows=many, contact_rows=[])

    contact_queries = [f for n, f in log if n == "contacts"]
    assert len(contact_queries) == 2, (
        f"{CAMPAIGN_ID_CHUNK + 5} campaigns should be read in 2 chunks, got "
        f"{len(contact_queries)} query/queries"
    )
    seen = [cid for f in contact_queries for cid in f["campaign_id"]]
    assert len(seen) == CAMPAIGN_ID_CHUNK + 5, "chunking dropped campaigns"
    assert len(set(seen)) == len(seen), "chunking repeated a campaign"


def test_the_campaign_read_is_itself_bounded():
    """The same ceiling applies one level up."""
    _, log = _run(campaign_rows=[{"id": "camp-a"}], contact_rows=[])

    camp_queries = [f for n, f in log if n == "campaigns"]
    assert camp_queries and camp_queries[0].get("__limit"), (
        "the campaigns read has no explicit limit — a user past the ceiling "
        "would silently lose the campaigns beyond it, and every contact in them"
    )
    assert camp_queries[0].get("user_id") == "u1", (
        "the campaigns read is not filtered to this user"
    )


# ── who gets their inbox read, and how often ──


def test_a_user_who_never_sent_anything_is_not_scanned():
    """Reading the inbox of somebody who has never sent an email, looking for
    replies to messages that do not exist, is a Graph call for an answer that
    cannot change. Harmless once a day; multiplied by four on 2026-09-01 when
    the cadence went up, which is why the narrowing came first."""
    from unittest.mock import MagicMock, patch

    from workers import reply_detector

    db = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value = t
        t.gt.return_value = t
        t.eq.return_value = t
        t.limit.return_value = t
        if name == "user_tokens":
            t.execute.return_value = MagicMock(
                data=[{"user_id": "sender"}, {"user_id": "never-sent"}]
            )
        elif name == "campaigns":
            t.execute.return_value = MagicMock(data=[{"user_id": "sender"}])
        else:
            t.execute.return_value = MagicMock(data=[])
        return t

    db.table.side_effect = table
    scanned = []

    with patch("database.get_db", return_value=db), \
         patch("workers.reply_detector.get_fresh_access_token",
               side_effect=lambda uid: scanned.append(uid) or None):
        reply_detector.detect_replies()

    assert scanned == ["sender"], (
        f"scanned {scanned} — a user who has never sent anything had their "
        f"inbox read"
    )


def test_a_failed_narrowing_scans_everyone_rather_than_nobody():
    """Reading one inbox too many is waste. Reading one too few is a follow-up
    chasing somebody who already wrote back."""
    from unittest.mock import MagicMock, patch

    from workers import reply_detector

    db = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value = t
        t.gt.return_value = t
        t.eq.return_value = t
        t.limit.return_value = t
        if name == "user_tokens":
            t.execute.return_value = MagicMock(
                data=[{"user_id": "a"}, {"user_id": "b"}]
            )
        elif name == "campaigns":
            t.execute.side_effect = RuntimeError("postgrest down")
        else:
            t.execute.return_value = MagicMock(data=[])
        return t

    db.table.side_effect = table
    scanned = []

    with patch("database.get_db", return_value=db), \
         patch("workers.reply_detector.get_fresh_access_token",
               side_effect=lambda uid: scanned.append(uid) or None):
        reply_detector.detect_replies()

    assert scanned == ["a", "b"], (
        f"narrowing failed and the scan narrowed anyway: {scanned}"
    )


def test_reply_detection_runs_four_times_a_day():
    """The gap between runs is the window in which a follow-up can reach
    somebody who already replied. Daily made it 24 hours wide."""
    from workers.celery_app import celery

    entry = celery.conf.beat_schedule["detect-replies"]
    hours = entry["schedule"].hour
    assert len(hours) == 4, (
        f"reply detection runs {len(hours)} time(s) a day, not four: {hours}"
    )
    assert 5 in hours, "05:00 UTC must stay — it follows the send-window close"
