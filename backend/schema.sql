-- OutMass — Supabase SQL Schema
-- Bunu Supabase Dashboard → SQL Editor'da calistirin.

-- ── Users ──
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  microsoft_id TEXT UNIQUE NOT NULL,
  email TEXT NOT NULL,
  name TEXT,
  plan TEXT DEFAULT 'free',
  emails_sent_this_month INT DEFAULT 0,
  month_reset_date DATE DEFAULT CURRENT_DATE,
  last_login_at TIMESTAMPTZ,
  last_activity_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Campaigns ──
CREATE TABLE campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT DEFAULT 'draft',
  total_contacts INT DEFAULT 0,
  sent_count INT DEFAULT 0,
  open_count INT DEFAULT 0,
  click_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Contacts ──
CREATE TABLE contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  first_name TEXT,
  last_name TEXT,
  company TEXT,
  position TEXT,
  custom_fields JSONB DEFAULT '{}',
  status TEXT DEFAULT 'pending',
  sent_at TIMESTAMPTZ,
  opened_at TIMESTAMPTZ,
  clicked_at TIMESTAMPTZ,
  unsubscribed BOOL DEFAULT FALSE
);

-- ── Events (tracking log) ──
CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Suppression List ──
CREATE TABLE suppression_list (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  reason TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Follow-ups ──
CREATE TABLE follow_ups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  delay_days INT NOT NULL DEFAULT 3,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  condition TEXT DEFAULT 'not_opened',
  status TEXT DEFAULT 'scheduled',
  scheduled_for TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── User Tokens (for server-side token refresh) ──
CREATE TABLE IF NOT EXISTS user_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
  refresh_token TEXT,
  access_token TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Templates ──
CREATE TABLE IF NOT EXISTS templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── A/B Tests ──
CREATE TABLE IF NOT EXISTS ab_tests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  subject_a TEXT NOT NULL,
  subject_b TEXT NOT NULL,
  test_percentage INT DEFAULT 20,
  opens_a INT DEFAULT 0,
  opens_b INT DEFAULT 0,
  winner TEXT,
  status TEXT DEFAULT 'testing',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Settings columns on users ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS track_opens BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS track_clicks BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS unsubscribe_text TEXT DEFAULT 'Unsubscribe';
ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'UTC';

-- ── AI generation counter ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_generations_this_month INT DEFAULT 0;

-- ── Sender profile columns on users ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_name TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_position TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_company TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_phone TEXT DEFAULT '';

-- ── Billing columns on users ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_updated_at TIMESTAMPTZ;

-- ── Scheduling column on campaigns ──
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;

-- ── A/B variant on contacts ──
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ab_variant TEXT;

-- ── Indexes ──
CREATE INDEX idx_campaigns_user_id ON campaigns(user_id);
CREATE INDEX idx_contacts_campaign_id ON contacts(campaign_id);
CREATE INDEX idx_contacts_status ON contacts(status);
CREATE INDEX idx_events_contact_id ON events(contact_id);
CREATE INDEX idx_events_campaign_id ON events(campaign_id);
CREATE INDEX idx_suppression_user_email ON suppression_list(user_id, email);
CREATE INDEX idx_followups_campaign_id ON follow_ups(campaign_id);
CREATE INDEX idx_followups_status ON follow_ups(status);
CREATE INDEX idx_followups_scheduled_for ON follow_ups(scheduled_for);
CREATE INDEX idx_templates_user_id ON templates(user_id);
CREATE INDEX idx_ab_tests_campaign_id ON ab_tests(campaign_id);
CREATE INDEX idx_campaigns_scheduled_for ON campaigns(scheduled_for);
