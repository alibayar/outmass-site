# OutMass — Handoff Document (2026-04-17)

## Proje Nedir?
GMass'ın Outlook Web versiyonu. Chrome Extension (MV3) + FastAPI backend.
**Durum:** Launch'a hazır, sadece Chrome Web Store submission + quality checks kaldı.

---

## ✅ Tamamlanan Özellikler (özet)

### Core
- Microsoft OAuth 2.0 (Web Auth Flow — server-side refresh) → long-lived refresh tokens
- Campaign CRUD + kampanya adı (opsiyonel, fallback: subject + tarih)
- CSV upload + mail merge ({{firstName}}, {{company}}, vb.)
- Email sending via Microsoft Graph API (/me/sendMail)
- Open pixel + click redirect + unsubscribe flow
- A/B subject testing (4h sonra winner auto-send)
- Scheduled sending (Celery beat, 5 dk)
- Auto follow-up emails (not_opened / not_clicked)
- Email templates + Campaign Name two-way sync
- AI Email Writer (Claude Haiku, Pro plan, 50/ay limit)
- **CSV template download** (locale-specific örnekler, 10 dilde)

### i18n (10 dil)
- EN, TR, DE, FR, ES, RU, AR (RTL), HI, ZH_CN, JA
- Settings → Interface Language override
- AI writer target dili seçici (10 dil)
- Unsubscribe sayfası Accept-Language ile otomatik
- CSV template sample'ları locale-specific

### Monetization
- 3-tier pricing: **Free $0** (50/ay), **Starter $9** (2k/ay), **Pro $19** (10k/ay)
- Stripe Checkout + Customer Portal
- **Starter → Pro proration**: mevcut subscription modify + orantılı ücret
- Webhook handler (checkout.session.completed, customer.subscription.*)

### UX Detayları
- Sidebar: 4 tab (Campaign, Reports, Settings, Account)
- Connection status dot + offline banner
- Platform limit disclaimer (Outlook günlük limitleri)
- Settings: Sender profile, Interface language, Suppression list (search + count)
- Feedback form → Telegram + Email (MailerSend, Reply-To user)
- Daily report to Telegram (14:00 UTC, MRR + DAU)

### Observability
- PostHog error tracking (backend exceptions + extension errors)
- PostHog → Telegram alert (new issue)
- Daily metric report (Telegram, 14:00 UTC)

### Testing
- **118 test total** (70 unit + 48 E2E)
- Unit: mock DB, TDD for critical paths (billing, auth, ai limit, feedback, daily_report, unsub)
- E2E: Playwright sidebar UI (16) + Visual regression in 10 locales (32 screenshots)

---

## 🔴 Launch Öncesi Kritik İşler

### 1. Chrome Web Store Submission
- [x] manifest.json production-ready (Railway URL eklenmiş)
- [x] Icons (16, 48, 128)
- [x] Privacy Policy (docs/privacy.html) + Terms (docs/terms.html)
- [x] 10 dilde store listing (docs/store-listing/listings.json)
- [ ] **Screenshot 1-5** (1280x800) — kullanıcı çekiyor
- [ ] **Small promo tile** (440x280) — kullanıcı yapacak
- [ ] Developer Dashboard'a upload + 10 localized listing ekleme
- [ ] Review (3-7 gün)

### 2. Canlıya Geçiş (Review onaylandıktan sonra)
Railway env var'ları swap (sandbox → live):
- [ ] `STRIPE_SECRET_KEY` → `sk_live_...`
- [ ] `STRIPE_WEBHOOK_SECRET` → live webhook secret
- [ ] `STRIPE_STARTER_PRICE_ID` → live $9 price
- [ ] `STRIPE_PRO_PRICE_ID` → live $19 price
- [ ] `STRIPE_PORTAL_CONFIG_ID` → live `bpc_...`
- [ ] `CORS_ORIGINS` → yeni Chrome Web Store extension ID ekle
- [ ] `AZURE_EXTENSION_ID` → yeni extension ID

---

## 🟡 Launch Sonrası Yapılacaklar (kullanıcı talep etti — bir sonraki session)

### A. CSV Kontrolleri (öncelik yüksek)

**Kritik:**
- [ ] **Duplicate email dedup** — aynı CSV içinde tekrarlayan adres sadece 1 kez kaydedilsin (case-insensitive)
- [ ] **Case-insensitive normalization** — `Ali@Example.com` ve `ali@example.com` aynı → küçük harfe normalize et
- [ ] **Suppression list cross-check** — upload sırasında kullanıcının kendi suppression list'i ile kesişim varsa uyar ve skip et

**Önemli:**
- [ ] **"email" kolonu mandatory check** — yoksa açık hata mesajı ("Column 'email' is required")
- [ ] **Satır sayısı limiti** — max 5000 satır/upload (veya plan bazlı: Free 100, Starter 2k, Pro 5k)
- [ ] **File size limit** — max 5 MB
- [ ] **Encoding detection** — UTF-8 BOM handle et, latin-1 reddet (açık mesaj ver)

**İleride:**
- [ ] Role account tespiti (`admin@`, `info@`, `noreply@`, `postmaster@`, `abuse@`) — uyar
- [ ] Disposable email domain tespiti (tempmail, guerrillamail, vb. 30+ domain liste)
- [ ] Duplicate detection across PREVIOUS campaigns (opsiyonel, Pro özellik)

**Dosyalar:**
- `backend/models/contact.py` — `bulk_insert()` fonksiyonu
- `backend/routers/campaigns.py` — `upload_contacts()` endpoint
- `extension/sidebar.js` — `handleCSV()` client-side pre-validation
- Testler: `backend/tests/test_campaigns.py`, yeni test_contact_validation.py

### B. Campaign Name Kontrolleri

**Kritik:**
- [ ] **Whitespace trim** — " " (sadece boşluk) adı reject et
- [x] Max 100 karakter (HTML maxlength zaten var)
- [x] Boş kalırsa fallback: subject + tarih ✅

**Önemli:**
- [ ] **Duplicate campaign name uyarısı** — aynı user'da aynı isim varsa confirm() "A campaign with this name exists. Continue?"

### C. Email Content Kontrolleri

**Kritik:**
- [ ] **Bozuk merge tag tespiti** — `{{firstName}` (eksik `}`) → gönderime izin verme
- [ ] **Bilinmeyen merge tag uyarısı** — `{{fname}}` yazılmış ama CSV'de sadece `firstName` var → "Unknown merge tag: fname"
- [ ] **Merge tag preview** — Preview butonu zaten var, ama bozuk tag'leri işaretle

**Önemli:**
- [ ] **"Test Send" butonu** — Preview yanına, kendi email'ine gerçek gönderim (en çok istenen özellik)
- [ ] **Subject uzunluk uyarısı** — 78+ karakter → "Subject may be truncated on mobile"
- [ ] **Spam kelime uyarısı** — "FREE!!!", "$$$", "100% guaranteed", "act now" → warning
- [ ] **ALL CAPS uyarısı** — subject veya body'de çok fazla büyük harf = spam sinyali
- [ ] **Link sayısı uyarısı** — 5+ link → "Too many links may trigger spam filters"

**İleride:**
- [ ] HTML validation (eksik tag, geçersiz yapı)
- [ ] Image count limit (5+ → spam)
- [ ] Link shortener tespiti (bit.ly, tinyurl → deliverability'yi düşürür)
- [ ] Sender reputation score (SpamAssassin benzeri)

### D. Diğer UX İyileştirmeleri

- [ ] **Onboarding wizard** — ilk kullanıcıya 3-step tanıtım (upload CSV → write content → send)
- [ ] **Campaign archive** — eski kampanyaları arşivle, Reports tab'ında "Active" tab'ıyla ayrı göster
- [ ] **Email preview HTML render** — şu an plain text, HTML'i modal'da render et
- [ ] **Export campaign list as CSV** — tüm kampanyaları + istatistikleri bir CSV olarak indir

---

## 🔧 Stack

- **Extension**: Vanilla JS, Chrome MV3
- **Backend**: Python 3.11+, FastAPI, Supabase (PostgreSQL)
- **Queue**: Celery + Upstash Redis (SSL)
- **AI**: Claude Haiku (Anthropic API)
- **Error Tracking**: PostHog (EU)
- **Billing**: Stripe (sandbox → live)
- **Email (outbound)**: MailerSend (feedback forwarding)
- **Email (inbound)**: Cloudflare Email Routing (support@getoutmass.com → Outlook)
- **Notifications**: Telegram Bot API (hata alert + feedback + daily report)
- **Hosting**: Railway (backend + worker + beat services)
- **Test**: Pytest (70 unit) + Playwright (48 E2E)

## 📁 Dosya Yapısı

```
backend/
  config.py                 # Tüm env var'lar
  main.py                   # FastAPI app, /api/error-report, /api/feedback
  database.py               # Supabase singleton
  schema.sql                # DB schema
  migrations/
    001_add_settings_billing_columns.sql
    002_add_sender_profile_columns.sql
    003_add_ai_generation_counter.sql
    004_default_timezone_utc.sql
  routers/
    auth.py                 # MS OAuth callback + token exchange
    campaigns.py            # Campaign CRUD, upload, send, export
    tracking.py             # Open/click/unsubscribe (i18n, RTL)
    billing.py              # Stripe: checkout + modify sub + portal + webhook
    templates.py            # Template CRUD
    ai.py                   # Claude Haiku (Pro only, 50/ay limit)
    settings.py             # User settings + suppression list
  models/
    user.py, campaign.py, contact.py, template.py, ab_test.py, followup.py
    ms_token.py             # Shared token refresh logic
  workers/
    celery_app.py           # Beat schedule (followup, scheduled, ab_test, daily_report)
    email_worker.py         # Single send task
    scheduled_worker.py     # Scheduled campaigns + AB winner
    followup_worker.py      # Follow-up sender
    daily_report.py         # Telegram daily metric report
  tests/
    conftest.py             # Mock fixtures (FakeSupabase, auth bypass)
    test_*.py               # 70 unit tests (auth/billing/campaigns/ai/feedback/tracking/...)
    integration/
      conftest.py           # Real DB fixtures
      test_*.py             # Integration tests (uses real Supabase)

extension/
  manifest.json             # MV3, production URLs, default_locale en
  background.js             # Service worker, API handlers, health check
  content_script.js         # Sidebar iframe injection
  sidebar.html/js/css       # 4-tab UI
  popup.html/js             # Auth + quick actions
  i18n.js                   # t() + applyI18n() + language override
  _locales/                 # 10 dil (en, tr, de, fr, es, ru, ar, hi, zh_CN, ja)
  icons/                    # 16, 48, 128 PNG

docs/                       # GitHub Pages (getoutmass.com)
  index.html, pricing.html, privacy.html, terms.html, refund.html
  store-listing/
    listings.json           # 10 dilde Chrome Web Store listing
    README.md

e2e/
  extension.spec.ts         # 16 UI tests
  i18n-visual.spec.ts       # 32 visual regression (10 dil × 3 tab + 2 dir check)

.github/workflows/
  ci.yml                    # Unit + E2E tests on push
```

## 🔑 Önemli Env Var'lar

### Railway (production)
```
# Supabase
SUPABASE_URL=https://qhfefazyfhyqnjcmfmdd.supabase.co
SUPABASE_KEY=<anon key>

# Auth
JWT_SECRET=<32-byte hex>
AZURE_CLIENT_ID=3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5
AZURE_CLIENT_SECRET=<from Azure app>
AZURE_REDIRECT_URI=https://outmass-production.up.railway.app/auth/callback
AZURE_EXTENSION_ID=<extension ID, değişecek store'dan sonra>

# App
BACKEND_URL=https://outmass-production.up.railway.app
CORS_ORIGINS=chrome-extension://<ext_id>,<other origins>

# Stripe (sandbox şu an)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STARTER_PRICE_ID=price_1TNBQNJ2B12lELVmRjjuFmth
STRIPE_PRO_PRICE_ID=price_1TNBQlJ2B12lELVmS0rxYD4F
STRIPE_PORTAL_CONFIG_ID=bpc_1TJYHWJ2B12lELVmfOpxm6VW

# Queue
REDIS_URL=rediss://default:...@upstash.io:6379

# AI
ANTHROPIC_API_KEY=sk-ant-...

# Observability
POSTHOG_API_KEY=phc_...
POSTHOG_HOST=https://eu.i.posthog.com

# Notifications
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=8445487787

# Email forwarding
MAILERSEND_API_KEY=mlsn_...
MAILERSEND_FROM_EMAIL=support@getoutmass.com
MAILERSEND_FROM_NAME=OutMass Feedback
MAILERSEND_TO_EMAIL=support@getoutmass.com
```

## 🧪 Test Komutları
```bash
npm run test:unit           # 70 backend unit tests (mock DB) — 3 sn
npm run test:integration    # Integration tests (real Supabase) — 30 sn
npm run test:e2e            # 48 Playwright tests — 15 sn
npm run test:all            # Hepsi
```

## 👤 Test DB User
- Email: `outmassapp@outlook.com`
- ID: `7ebce016-e2af-4f88-9e00-90bdfdb18cba`
- Test için plan manipulasyonu script:
  ```python
  from database import get_db
  get_db().table('users').update({
      'plan': 'free',
      'stripe_customer_id': None,
      'stripe_subscription_id': None
  }).eq('id', '7ebce016-e2af-4f88-9e00-90bdfdb18cba').execute()
  ```

## 📦 Son Commit (bu session sonunda)
Kontrol için: `git log --oneline -10`

## 📝 Bir Sonraki Session İçin Talimatlar

Kullanıcı bu session'da şunu istedi:
> "Bir handoff dokümanı yaz, yeni bir session'da ben bunların hepsinin (ileride dahil) yapılmasını istiyorum."

Yani **yukarıdaki "Launch Sonrası Yapılacaklar" bölümündeki A/B/C/D başlıklarının HEPSİNİ** (kritik, önemli, ileride dahil) yap.

**Sıralama önerisi:**
1. **C grubu (Email Content)** önce — Test Send butonu en çok istenen özellik, merge tag validation kullanıcıyı yanlış gönderimden korur
2. **A grubu (CSV Kontrolleri)** — duplicate dedup kritik bug
3. **B grubu (Campaign Name)** — küçük polish
4. **D grubu (UX İyileştirmeleri)** — onboarding, archive, HTML preview

**Çalışma metodolojisi:**
- TDD: Kritik alanlar (billing, auth, send, tracking) için önce test, sonra kod
- Test-after: UI değişiklikleri için
- Her commit küçük ve atomik, descriptive message
- 10 dilde i18n her yeni UI string için

**Yeni session'a bu doküman + kod ile başlayacak. Branch: master.**
