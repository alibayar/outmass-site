-- Migration 003: Add AI generation counter for Pro plan limit tracking
-- Safe to re-run (IF NOT EXISTS)

ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_generations_this_month INT DEFAULT 0;
