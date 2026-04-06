# OutMass — Handoff Document (2026-04-07)

## Proje Nedir?
GMass'ın Outlook Web versiyonu. Chrome Extension (MV3) + FastAPI backend.
Hedef: Mass email campaign gönderimi Outlook Web üzerinden.

## Tamamlanan Özellikler
1. **Auth**: Microsoft OAuth 2.0 → Graph API → JWT
2. **Campaign CRUD**: Oluştur, listele, istatistik
3. **Contact Upload**: CSV + JSON, email validation
4. **Email Sending**: Graph API `/me/sendMail` ile
5. **Tracking**: Open pixel (1x1 GIF), click redirect, unsubscribe
6. **3-Tier Pricing**: Free (50/ay), Standard ($15, 5000/ay), Pro ($25, 10000/ay)
7. **Stripe Billing**: Checkout + Webhooks, plan upgrade/downgrade
8. **CSV Export**: Standard+ plan gating
9. **Scheduled Sending**: Celery beat, 5dk aralıkla kontrol
10. **Email Templates**: CRUD, Standard+ plan
11. **A/B Testing**: Subject A/B, test %, 4 saat sonra winner değerlendirme, Pro plan
12. **AI Email Writer**: Claude 3 Haiku API, Pro plan only
13. **Follow-ups**: Delay days, condition (not_opened/not_clicked), soft-delete
14. **Settings Tab**: Track opens/clicks toggle, unsubscribe text, timezone, suppression list
15. **PostHog Error Tracking**: Backend exception handler + extension error reporting
16. **Test Automation**: 62 backend test (unit + integration) + 16 Playwright E2E = 78 test

## Bilinen Sorunlar / Yapılacaklar
- **Web Auth Flow migration**: SPA token 1 saatte expire oluyor, server-side refresh yapılamıyor. Azure AD'de Web platform + client_secret gerekli. Async özellikler (scheduled sending, follow-up) için şart.
- **Settings tab SQL**: `ALTER TABLE users ADD COLUMN IF NOT EXISTS track_opens BOOLEAN DEFAULT TRUE, track_clicks BOOLEAN DEFAULT TRUE, unsubscribe_text TEXT DEFAULT 'Abonelikten cik', timezone TEXT DEFAULT 'Europe/Istanbul';` — çalıştırıldı mı belirsiz.
- **Stripe Standard price**: `STRIPE_STANDARD_PRICE_ID` henüz `.env`'de yok.
- **Railway deployment**: Henüz yapılmadı.
- **Manuel test gerekli**: Email gönderimi (Graph API token gerekli), Stripe ödeme akışı, Outlook Web content script injection.

## Stack
- **Extension**: Vanilla JS, Chrome MV3
- **Backend**: Python 3.11+, FastAPI, Supabase (PostgreSQL)
- **Queue**: Celery + Upstash Redis
- **AI**: Claude 3 Haiku (Anthropic API)
- **Error Tracking**: PostHog (EU, free tier)
- **Billing**: Stripe
- **Test**: Pytest (unit + integration), Playwright (E2E)

## Önemli Dosyalar
```
backend/
  .env                    # Tüm env variables (Supabase, Stripe, Redis, PostHog, Anthropic)
  .env.test               # Test user email (outmassapp@outlook.com)
  main.py                 # FastAPI app, PostHog init, error handler
  config.py               # Tüm env okumaları
  database.py             # Supabase singleton client
  schema.sql              # Tüm DB şeması
  routers/
    auth.py               # Microsoft OAuth, JWT
    campaigns.py          # Campaign CRUD, contact upload, send, CSV export, A/B test
    tracking.py           # Open pixel, click redirect, unsubscribe
    billing.py            # Stripe checkout, webhooks
    templates.py          # Template CRUD
    ai.py                 # Claude Haiku email generation
    settings.py           # User settings, suppression list
  models/                 # Supabase query helpers (user, campaign, contact, template, ab_test, followup)
  workers/
    celery_app.py         # Celery config + beat schedule
    email_worker.py       # Email sending task
    scheduled_worker.py   # Scheduled campaigns + A/B evaluation
  tests/
    conftest.py           # Mock DB fixtures (FakeSupabase, auth bypass)
    test_*.py             # 31 unit tests
    integration/
      conftest.py         # Real DB fixtures (cleanup tracker, JWT auth)
      test_campaigns.py   # 8 tests: CRUD, CSV/JSON upload, invalid email skip
      test_settings.py    # 7 tests: get/update settings, suppression CRUD
      test_tracking.py    # 5 tests: open pixel dedup, click redirect, unsubscribe flow
      test_templates.py   # 6 tests: plan gating, CRUD, CSV export, scheduled sending
      test_followups.py   # 5 tests: followup CRUD, A/B test, plan gating

extension/
  manifest.json           # MV3, permissions, content scripts
  background.js           # Service worker, tüm API message handlers
  content_script.js       # Outlook DOM injection, sidebar toggle
  sidebar.html/js/css     # Ana UI (campaign, reports, settings tabs)
  popup.html/js           # Auth popup

e2e/
  extension.spec.ts       # 16 Playwright UI tests

playwright.config.ts      # Playwright config
package.json              # npm scripts (test:unit, test:integration, test:e2e, test:all)
```

## Test Komutları
```bash
npm run test:unit         # Mock unit tests (3sn)
npm run test:integration  # Real Supabase DB tests (30sn)
npm run test:e2e          # Playwright sidebar UI tests (7sn)
npm run test:all          # Hepsi birden
```

## DB User
- Email: outmassapp@outlook.com
- Plan: pro (test için değiştirilip restore ediliyor)
- ID: 7ebce016-e2af-4f88-9e00-90bdfdb18cba

## Son Yapılan Değişiklikler (bu session)
1. Test otomasyonu kuruldu (pytest + Playwright)
2. 31 unit test yazıldı (mock DB)
3. 31 integration test yazıldı (gerçek Supabase)
4. 16 Playwright E2E test yazıldı
5. AI writer OpenAI → Gemini → Claude Haiku'ya geçirildi
6. Settings tab backend + frontend tamamlandı

## Commit Durumu
Son commit: `4a5f333 feat: Add PostHog error tracking + fix CSV export bug`
Uncommitted: Settings tab, test files, AI writer Claude migration, package.json, playwright config
