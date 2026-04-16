-- Migration 004: Change default timezone from 'Europe/Istanbul' to 'UTC' for global users
-- Existing users keep their current timezone. Only affects new users.

ALTER TABLE users ALTER COLUMN timezone SET DEFAULT 'UTC';

-- Also change default unsubscribe_text to English 'Unsubscribe' for global users
-- (existing users keep their current value)
ALTER TABLE users ALTER COLUMN unsubscribe_text SET DEFAULT 'Unsubscribe';
