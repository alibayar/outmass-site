# OutMass — Handoff Document (2026-04-21)

## Proje Nedir?
GMass'ın Outlook Web versiyonu. Chrome Extension (MV3) + FastAPI backend.
**Durum:** PRODUCTION CANLIDA. Chrome Web Store'da v0.1.1 yayında, v0.1.3 local'de hazır paketli (review'a yüklenmek üzere).

## 🎯 Bu Handoff Neye Yarıyor
Context dolduğundan yeni session'a geçiyoruz. Bu doküman son sessiondaki tüm ilerlemeyi, yarım kalan işleri ve kritik state'i içeriyor. Yeni session bunu okuyarak devam edebilmeli.

---

## ⏳ Yarım Kalan İşler (Öncelik Sırasına Göre)

### 1. v0.1.3 Chrome Web Store submission (user action bekliyor)
- **Action:** Dashboard → Paket → `outmass-v0.1.3.zip` upload → "İnceleme için gönder"
- **Zip konumu:** `D:\dev\git\outmass\outmass-v0.1.3.zip` (128 KB, manifest v0.1.3 ✓)
- **Not:** Paket artifact'i gitignore'da — her session'da yeniden paketlenir:
  ```powershell
  # Windows (PowerShell)
  cd extension; Compress-Archive -Path * -DestinationPath ../outmass-v0.1.3.zip -Force
  ```
  ```bash
  # Linux / macOS
  cd extension && zip -r ../outmass-v0.1.3.zip . -x "*.DS_Store" && cd ..
  ```
- **Release notes draft:**
  ```
  v0.1.3 — bug fixes + UX improvements
  • Reconnect-to-Outlook banner when MS authorization expires (from v0.1.2)
  • "Session expired" banner when your sign-in has timed out, with one-click re-login
  • Scheduled-send time, reports dates, and alerts now use your selected interface language (was OS default)
  • Manage Subscription button now shows a clear error message when billing isn't set up
  • Unsubscribe footer label now respects your Settings → Unsubscribe text override (was always Turkish)
  • Multi-extension OAuth support lets dev builds and the store build sign in against the same backend
  • Test Send no longer creates placeholder campaigns in Reports (from v0.1.2)
  • Scheduled sending error shows proper upgrade prompt (from v0.1.2)
  • Fixed i18n named-placeholder substitution in non-English locales (from v0.1.2)
  • Cleaned up developer personal data from Settings placeholders (from v0.1.2)
  ```

### 2. Post-launch iyileştirmeler (backlog, launch-blocker DEĞİL)
- [ ] `ON DELETE CASCADE` FK zinciri events → contacts → campaigns → user (temizlik SQL'i sadeleşir)
- [x] ~~Scheduled send token failure → campaign'i `failed_auth` status'a çek~~ (done in v0.1.3 backend, commit `170edd9`)
- [x] ~~MailerSend notification when user gets flagged `requires_reauth`~~ (done in v0.1.3 backend, commit `170edd9`)
- [x] ~~Proactive token health check job~~ (done in v0.1.3 backend, beat 03:00 UTC, commit `170edd9`)
- [ ] Non-root Celery worker (Dockerfile + `useradd` + `--uid 1000`) — güvenlik sıkılaştırma, paid user 500+ olunca yap
- [ ] Gmail desteği (Phase 2, $5-10k MRR sonrası — CASA audit gerektirir)
- [ ] Sender reputation score (SpamAssassin-benzeri)
- [ ] Error codes yerine plain-text backend error mesajları lokalize etmek (örn. "No Stripe customer found" → structured code + i18n key)

### 3. Launch marketing (v0.1.3 onay sonrası)
- Launch kit zaten hazır: `docs/launch/producthunt.md`
- Launch günü öncesi: demo video (30-60 sn Loom), "notify me" email list'i büyüt (`getoutmass.com/launch`)
- PH launch önerisi: Thursday, 00:01 PST (Istanbul 10:01)
- LAUNCH50 Stripe promo hazır

---

## 🚦 Canlı Launch Durumu (2026-04-21)

### Mağazada
- **Chrome Web Store v0.1.1** yayında (`adcfddainnkjomddlappnnbeomhlcbmm`) — onaylandı 2026-04-21
- **v0.1.3** `outmass-v0.1.3.zip` olarak local'de hazır, review'a yüklenecek. v0.1.2 hiç ship olmadı (önceki session'da hazırlanmış zip, bu session'ın içerikleriyle süper-set olduğu için v0.1.3'e atlandı).
- İçerik: requires_reauth banner, session-expired banner, locale-aware datetimes, manage-subscription error surfacing, unsubscribe label fix, multi-extension OAuth flow.

### Backend (Railway — 3 servis)
- **outmass-production** (web): FastAPI, uvicorn, healthcheck `/`
- **outmass-worker** (Celery): `celery -A workers.celery_app worker --loglevel=info --concurrency=2`
- **outmass-beat** (Celery): `celery -A workers.celery_app beat --loglevel=info`
- Son "start command" debug edildi — `railway.json`'da global `startCommand` ve `healthcheckPath` YOK, her servis kendi Custom Start Command'ını UI'da tanımlıyor. Aksi halde 3 servis de uvicorn çalışır (düzeltildi, commit `f68dbcc` + `ec7dbe8`).

### Database (Supabase)
- RLS tüm 10 tabloda AÇIK (migration 008)
- Backend `SUPABASE_SERVICE_ROLE_KEY` kullanıyor (3 servis de — user bugün manuel ekledi)
- Migrations 001-009 tamamen uygulandı

### Ödeme (Stripe)
- Live mode aktif, UK Ltd hesabıyla
- 2 Product: Starter $9/ay, Pro $19/ay (recurring USD)
- Webhook endpoint + Customer Portal (bpc_1TNvl3QsbO4Gj1Xr3VaOSWcU) config'li
- `LAUNCH50` promo kodu (50% off first month, 100 redemption limit, May 31 expiry)
- Gerçek kart test edildi → $19 ödendi → refund yapıldı + subscription canceled

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

## 📜 2026-04-20 Session'ında Yapılanlar (Özet)

### Security + Reliability
- **RLS açıldı** 10 tablo için (migration 008) + backend `SUPABASE_SERVICE_ROLE_KEY`'e geçti (`d962bdf`)
- **Celery start commands** düzeltildi — railway.json global startCommand silindi, her servis Custom Start Command'ını UI'dan alır (`ec7dbe8`, `f68dbcc`)
- **sys.path fix** celery_app.py — ForkPoolWorker'lar `models` import edebilsin (`3201d5e`)
- **Scheduled send pipeline** end-to-end validated — beat/worker/Graph API/Supabase tüm zincir çalıştığı canlıda kanıtlandı
- **requires_reauth feature** (migration 009 + backend + frontend + tests) — Microsoft token expire'da silent failure yerine sidebar banner gösterir. Backend live, frontend v0.1.2'de.

### UX
- Test Send stateless yapıldı — artık `__test_send__` campaign row yaratmıyor (`004e2bd`)
- i18n named placeholder substitution fix (`$N$`, `$EMAIL$` gibi) — `5e4d55c`
- Scheduled sending 402 → proper "feature_locked" upgrade prompt (`c699411`)
- 0-recipient scheduled campaign guard — dedup tüm rows filtrelerse abort (`5e4d55c`)
- Scheduled-success alert tarihi override locale ile formatlanıyor
- Sender Information placeholders generic (`Ayşe Yılmaz` gibi) — `ae8874d`

### Launch Assets
- Notify-me landing page: `getoutmass.com/launch.html` + backend endpoint (`9fc8b31`)
- Product Hunt launch kit: `docs/launch/producthunt.md` (`cdcd1a8`)
- Legal entity migration: Metis Bilisim (TR) → Metis Information Technologies Ltd (UK, 71-75 Shelton Street) — privacy + terms + all footers (`542691e`)
- Landing pricing fixed: actual $0/$9/$19 tiers, not fictional team plan (`bb086ba`)
- Jekyll build fix: `docs/plans/` exclude ile Liquid parse error kurtarıldı (`71bed58`)
- Chrome Web Store store listing assets shipped (promo tiles 440×280 + 920×680, branded icons 16/48/128, 5 screenshot)
- 10-language store listing descriptions (TR/DE/FR/ES/RU/AR/HI/ZH_CN/JA) eklendi v0.1.1 submission'ında

### Infra debugging lessons learned
1. **Upstash free Redis** 14 gün inactivity → siliniyor. Yeniden oluşturuldu (`loving-weasel-102416.upstash.io`).
2. **Chrome Web Store pending review sırasında yeni package upload** → engelli. v0.1.1 onayı beklenmesi lazım.
3. **Microsoft refresh token** yaklaşık 14-90 gün geçerli (tenant policy). Token expire'da sessizce çalışmıyor → yeni requires_reauth UX.

### Test coverage
- **144 unit test** + **48 E2E test** yeşil (baseline 118, bu session +26)
- Yeni test dosyaları: `test_reauth_flagging.py`, `test_launch.py`, `test_cross_campaign_dedup.py`, `test_campaigns_validation.py`, `test_merge_tags.py`, `test_contact_validation.py`, `test_email_classifier.py`, `test_text_to_html.py`

### Stripe live mode setup
- 2 product (Starter $9, Pro $19) recurring USD
- Webhook endpoint live
- Customer Portal: `bpc_1TNvl3QsbO4Gj1Xr3VaOSWcU`
- `LAUNCH50` promo code (50% off, 100 limit, May 31 expiry)

---

## 🔑 Kritik State ve Erişim Bilgisi

### Owner Account (`outmassapp@outlook.com`)
- Plan: **Pro** (manuel Supabase update, Stripe'ta subscription yok — dogfooding)
- Manuel Pro için: `UPDATE users SET plan='pro' WHERE email='outmassapp@outlook.com'`
- user_id: `7ebce016-e2af-4f88-9e00-90bdfdb18cba`

### Extension IDs
- **Yayınlanan** (Chrome Web Store): `adcfddainnkjomddlappnnbeomhlcbmm`
- **Eski dev unpacked** (hâlâ Azure redirect list'inde, local test için): `acdafphnihddolfhabbndfofheokckhl`

### Azure AD app
- Client ID: `3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5`
- Redirect URIs (Web): `https://outmass-production.up.railway.app/auth/callback`
- Redirect URIs (SPA): both chromiumapp.org URLs (yeni + eski)

### Analytics queries — owner'ı exclude et
```sql
-- Revenue / active users queries'te kendi hesabını çıkar
WHERE stripe_subscription_id IS NOT NULL
  AND email != 'outmassapp@outlook.com'
```

### Supabase temizlik (FK-safe sıra)
```sql
-- events → contacts → ab_tests → follow_ups → campaigns
DELETE FROM events WHERE contact_id IN (
  SELECT c.id FROM contacts c JOIN campaigns ca ON c.campaign_id=ca.id
  WHERE ca.user_id='7ebce016-e2af-4f88-9e00-90bdfdb18cba');
DELETE FROM contacts WHERE campaign_id IN (
  SELECT id FROM campaigns WHERE user_id='7ebce016-e2af-4f88-9e00-90bdfdb18cba');
DELETE FROM ab_tests WHERE user_id='7ebce016-e2af-4f88-9e00-90bdfdb18cba';
DELETE FROM follow_ups WHERE user_id='7ebce016-e2af-4f88-9e00-90bdfdb18cba';
DELETE FROM campaigns WHERE user_id='7ebce016-e2af-4f88-9e00-90bdfdb18cba';
```

---

## 🟢 Launch Sonrası — 2026-04-17 session'ında tamamlandı

> Bu session'da A/B/C/D başlıklarının tümü (kritik + önemli + ileride) uygulandı.
> Plan: `docs/plans/2026-04-17-post-launch-quality.md`. Test sayısı 118 → 158
> (110 unit + 48 E2E, hepsi yeşil).

### A. CSV Kontrolleri

**Kritik:**
- [x] **Duplicate email dedup** — `bulk_insert()` aynı upload içinde tekrarı skip eder (case-insensitive, `skipped_duplicate` sayacı döner)
- [x] **Case-insensitive normalization** — email `.strip().lower()` ile normalize edilip DB'ye yazılır
- [x] **Suppression list cross-check** — `upload_contacts` suppression_list'i çekip `bulk_insert`'e geçirir, kesişim skip edilir (`skipped_suppressed` sayacı)

**Önemli:**
- [x] **"email" kolonu mandatory check** — header case-insensitive taranır, yoksa 400 + "Column 'email' is required in the CSV header"
- [x] **Satır sayısı limiti** — plan bazlı: Free 100, Starter 2k, Pro 5k (413)
- [x] **File size limit** — 5 MB (413)
- [x] **Encoding detection** — UTF-8 BOM strip, `\uFFFD` (replacement char) reddi (400 + "Please save as UTF-8")

**İleride:**
- [x] **Role account tespiti** — `utils/email_classifier.py` (~15 prefix, warn-only sayaç)
- [x] **Disposable email domain tespiti** — ~25 domain (mailinator, yopmail, guerrillamail, vb.), warn-only
- [x] **Cross-campaign dedup (Pro feature)** — `upload_contacts` önceki kampanyalardaki `sent`+`pending` adresleri lookback penceresi içinde skip eder. Settings'te toggle + gün sayısı (default 60, 7-730 clamp). Non-Pro'da UI gizli, backend plan gating'i var. Response'da `skipped_previous` sayacı + upload alert'i. Migration 006 (`005_campaign_archived.sql`'dan sonra) çalıştırılmalı.

**Dosyalar:**
- `backend/models/contact.py` — `bulk_insert()` → dict döner (inserted + 4 sayaç)
- `backend/routers/campaigns.py:upload_contacts` — size/row/encoding/header validation + suppression cross-check
- `backend/utils/email_classifier.py` — role + disposable classifiers
- `extension/sidebar.js:handleCSV` — client-side mirror validation
- `backend/tests/test_contact_validation.py` + `test_email_classifier.py` + ilgili `test_campaigns_validation.py`

### B. Campaign Name Kontrolleri

- [x] **Whitespace trim** — `create_campaign` 400 döner, HTML maxlength=100 zaten var
- [x] Max 100 karakter (HTML maxlength zaten var)
- [x] Boş kalırsa fallback: subject + tarih
- [x] **Duplicate campaign name uyarısı** — `startSendFlow` önce GET /campaigns çeker, isim varsa `confirm("A campaign named ... already exists")` gösterir

### C. Email Content Kontrolleri

**Kritik:**
- [x] **Bozuk merge tag tespiti** — `utils/merge_tags.find_malformed_tags` (`{{firstName}`, `firstName}}`, `{{}}` hepsi yakalanır), send + test-send 400 döner
- [x] **Bilinmeyen merge tag uyarısı** — `find_unknown_tags` CSV'de olmayan key'leri tespit eder, send 400 "Unknown merge tags: fname"
- [x] **Merge tag preview** — D.1'deki yeni HTML preview modal bozuk tag'leri olduğu gibi gösterir; send öncesi validator zaten blocke eder

**Önemli:**
- [x] **"Test Send" butonu** — `POST /campaigns/{id}/test-send` + sidebar butonu (Preview ile Send arasında); quota yemez, tracking olmaz
- [x] **Subject uzunluk uyarısı** — 78+ karakter → `warnSubjectLong`
- [x] **Spam kelime uyarısı** — 11 kelimelik liste (`FREE!!!`, `act now`, `$$$`, vb.) → `warnSpamWords`
- [x] **ALL CAPS uyarısı** — >50% uppercase ve 8+ harf → `warnAllCaps`
- [x] **Link sayısı uyarısı** — 5+ link → `warnTooManyLinks`

> Kullanıcı uyarıları override edebilir (`warnContinueAnyway` confirm).

**İleride:**
- [x] **HTML validation** — block-level tag'ler için açık/kapalı sayım (`div, p, span, a, table, tr, td, ul, li, h1-6, ...`), dengesizse `warnHtmlInvalid` uyarısı (void tag'ler ve self-closing `<br/>` hariç tutulur)
- [x] **Image count limit** — `<img`  sayısı 5+ ise `warnTooManyImages`
- [x] **Link shortener tespiti** — 15 domain (bit.ly, tinyurl.com, t.co, goo.gl, ow.ly, buff.ly, is.gd, cutt.ly, rebrand.ly, t.ly, shorturl.at, rb.gy, bl.ink, tiny.cc, lnkd.in), varsa `warnShortenedLinks`
- [ ] Sender reputation score (SpamAssassin benzeri — karmaşık, üçüncü-parti servis gerektirir)

### D. Diğer UX İyileştirmeleri

- [x] **Onboarding wizard** — 3-step, `chrome.storage.local.onboardingDone` ile tek seferlik
- [x] **Campaign archive** — `migration 005` + `/archive` + `/unarchive` endpoints + Reports tab'ında Active/Archived sub-tabs + per-row Archive/Unarchive butonu
- [x] **Email preview HTML render** — sandboxed `<iframe srcdoc>` modal (shared `.om-modal-*` stilleri)
- [x] **Export campaign list as CSV** — `GET /campaigns/export-list` + Reports header'da "Export All" butonu

### 🚨 Deploy öncesi çalıştırılacak adımlar

- [x] **Migration 005 çalıştır** — `backend/migrations/005_campaign_archived.sql` ✅ çalıştırıldı
- [x] **Migration 006 çalıştır** — `backend/migrations/006_cross_campaign_dedup.sql` ✅ 2026-04-17 çalıştırıldı

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
- **Test**: Pytest (119 unit) + Playwright (48 E2E) = 167 total

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
    005_campaign_archived.sql        # D.2 — archive flag + partial index
    006_cross_campaign_dedup.sql     # A.5 — dedup settings + contacts idx
  routers/
    auth.py                 # MS OAuth callback + token exchange
    campaigns.py            # Campaign CRUD, upload, send, export, test-send, archive
    tracking.py             # Open/click/unsubscribe (i18n, RTL)
    billing.py              # Stripe: checkout + modify sub + portal + webhook
    templates.py            # Template CRUD
    ai.py                   # Claude Haiku (Pro only, 50/ay limit)
    settings.py             # User settings + suppression list
  utils/
    merge_tags.py           # Malformed + unknown merge-tag detection
    email_classifier.py     # Role account + disposable domain detection
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
SUPABASE_SERVICE_ROLE_KEY=<service_role key>  # backend-only, bypasses RLS
# (SUPABASE_KEY with anon key still works as fallback, but RLS blocks it after migration 008)

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
