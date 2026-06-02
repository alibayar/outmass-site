-- 020: in-app announcements (one-way owner -> user channel).
--
-- announcements      = the messages we author (broadcast or targeted).
-- announcement_reads = per-user read/dismiss state (delivery visibility).
--
-- Additive + reversible (down = DROP both tables). No existing data touched.

BEGIN;

CREATE TABLE IF NOT EXISTS announcements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audience    TEXT NOT NULL CHECK (audience IN ('broadcast', 'targeted')),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,  -- set iff targeted
    priority    TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high')),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    cta_label   TEXT,
    cta_url     TEXT,
    version     TEXT,                       -- release notes: client shows only when running version >= this
    starts_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- targeted rows MUST name a user; broadcast rows MUST NOT
    CONSTRAINT announcements_target_chk CHECK (
        (audience = 'targeted' AND user_id IS NOT NULL)
        OR (audience = 'broadcast' AND user_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements (active, starts_at);
CREATE INDEX IF NOT EXISTS idx_announcements_user ON announcements (user_id);

CREATE TABLE IF NOT EXISTS announcement_reads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    announcement_id UUID NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at         TIMESTAMPTZ,
    dismissed_at    TIMESTAMPTZ,
    UNIQUE (announcement_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_announcement_reads_user ON announcement_reads (user_id);

COMMIT;

-- Down (manual):
--   DROP TABLE IF EXISTS announcement_reads;
--   DROP TABLE IF EXISTS announcements;

-- Verification:
--   SELECT * FROM announcements ORDER BY created_at DESC LIMIT 5;
