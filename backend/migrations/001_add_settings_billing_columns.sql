-- Migration 001: Add settings, billing, scheduling, and A/B test columns
-- Run this in Supabase SQL Editor before deploying to production
-- Safe to re-run (IF NOT EXISTS)

-- ── Settings columns on users ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS track_opens BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS track_clicks BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS unsubscribe_text TEXT DEFAULT 'Abonelikten cik';
ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'Europe/Istanbul';

-- ── Billing columns on users ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_updated_at TIMESTAMPTZ;

-- ── Scheduling column on campaigns ──
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;

-- ── A/B variant on contacts ──
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ab_variant TEXT;
