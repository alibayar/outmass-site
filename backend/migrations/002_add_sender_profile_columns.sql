-- Migration 002: Add sender profile columns to users
-- Run this in Supabase SQL Editor
-- Safe to re-run (IF NOT EXISTS)

ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_name TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_position TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_company TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_phone TEXT DEFAULT '';
