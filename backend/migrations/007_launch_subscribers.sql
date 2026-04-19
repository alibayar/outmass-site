-- 007: Launch notify-me list
-- Stores email addresses that opted in to be notified on public launch,
-- so we can send the PH launch announcement + promo code to them on day 0.

CREATE TABLE IF NOT EXISTS launch_subscribers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    locale      TEXT,                    -- UI locale the form was submitted from
    source      TEXT,                    -- e.g. 'landing', 'twitter', 'linkedin'
    notified_at TIMESTAMPTZ,             -- set when we send the launch email
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Case-insensitive uniqueness (jane@Example.com and jane@example.com
-- should collide).
CREATE UNIQUE INDEX IF NOT EXISTS launch_subscribers_email_lower_idx
    ON launch_subscribers (LOWER(email));
