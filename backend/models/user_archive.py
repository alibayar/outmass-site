"""
OutMass — User Archive helpers

Wraps the `archive_and_delete_user` Postgres function (migration 012)
behind a Python surface. Keeping the transactional work server-side
means we don't have to worry about the Supabase REST client dropping
a connection halfway between archiving and deleting.
"""

import logging

from database import get_db

logger = logging.getLogger(__name__)

# Allowed deletion_reason values — enforced in code rather than a DB
# CHECK constraint so we can evolve the vocabulary without a migration.
REASON_USER_REQUESTED = "user_requested"
REASON_ADMIN = "admin"
REASON_INACTIVITY = "inactivity"
REASON_CHARGEBACK = "chargeback"

VALID_REASONS = {
    REASON_USER_REQUESTED,
    REASON_ADMIN,
    REASON_INACTIVITY,
    REASON_CHARGEBACK,
}


def archive_and_delete(user_id: str, reason: str) -> str:
    """Atomically archive + delete a user. Returns the new archive_id.

    Raises ValueError for unknown reasons so we never accidentally land
    a typo like "user_reqested" as a permanent audit value.
    Raises RuntimeError if the RPC call fails (e.g. user already gone).
    """
    if reason not in VALID_REASONS:
        raise ValueError(f"Invalid deletion reason: {reason!r}")

    result = (
        get_db()
        .rpc(
            "archive_and_delete_user",
            {"p_user_id": user_id, "p_deletion_reason": reason},
        )
        .execute()
    )

    # Supabase RPC returns the scalar as `data`. Shape varies by client
    # version — handle both scalar and [{"archive_and_delete_user": uuid}].
    data = result.data
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            # Named return or first key
            archive_id = first.get("archive_and_delete_user") or next(iter(first.values()), None)
        else:
            archive_id = first
    else:
        archive_id = data

    if not archive_id:
        raise RuntimeError(f"archive_and_delete_user returned no id for user {user_id}")

    logger.info(
        "Archived + deleted user %s (reason=%s, archive_id=%s)",
        user_id, reason, archive_id,
    )
    return str(archive_id)
