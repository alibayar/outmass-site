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
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Campaigns ──
CREATE TABLE campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
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
  campaign_id UUID REFERENCES campaigns(id),
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
  contact_id UUID REFERENCES contacts(id),
  campaign_id UUID REFERENCES campaigns(id),
  event_type TEXT NOT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Suppression List ──
CREATE TABLE suppression_list (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  email TEXT NOT NULL,
  reason TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Follow-ups ──
CREATE TABLE follow_ups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID REFERENCES campaigns(id),
  user_id UUID REFERENCES users(id),
  delay_days INT NOT NULL DEFAULT 3,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  condition TEXT DEFAULT 'not_opened',
  status TEXT DEFAULT 'scheduled',
  scheduled_for TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

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
