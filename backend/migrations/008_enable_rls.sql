-- 008: enable Row Level Security on every application table
--
-- Threat model: if the Supabase anon key ever leaks or is accidentally
-- shipped to a client, we don't want it to be able to read or write our
-- data. With RLS ON and no policies, only the service_role key can
-- access rows (service_role bypasses RLS by default).
--
-- The backend must connect with SUPABASE_SERVICE_ROLE_KEY, not the
-- anon key, after this migration runs. If the backend is still using
-- the anon key, it will get empty results / permission errors.
--
-- To run AFTER updating Railway env var SUPABASE_KEY to the service_role
-- value (or adding SUPABASE_SERVICE_ROLE_KEY, whichever the updated
-- backend config prefers).

ALTER TABLE users               ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns           ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts            ENABLE ROW LEVEL SECURITY;
ALTER TABLE events              ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppression_list    ENABLE ROW LEVEL SECURITY;
ALTER TABLE follow_ups          ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_tokens         ENABLE ROW LEVEL SECURITY;
ALTER TABLE templates           ENABLE ROW LEVEL SECURITY;
ALTER TABLE ab_tests            ENABLE ROW LEVEL SECURITY;
ALTER TABLE launch_subscribers  ENABLE ROW LEVEL SECURITY;

-- Verify: this should return 10 rows, all with rowsecurity = true
-- SELECT tablename, rowsecurity FROM pg_tables
-- WHERE schemaname = 'public' AND tablename IN (
--     'users', 'campaigns', 'contacts', 'events', 'suppression_list',
--     'follow_ups', 'user_tokens', 'templates', 'ab_tests',
--     'launch_subscribers'
-- );
