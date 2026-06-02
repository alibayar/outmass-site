from tests.conftest import FakeQueryBuilder


def test_fake_upsert_sets_data():
    qb = FakeQueryBuilder()
    qb.upsert({"announcement_id": "a", "user_id": "u", "read_at": "now"})
    assert qb.execute().data == [{"announcement_id": "a", "user_id": "u", "read_at": "now"}]
