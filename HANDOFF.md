# OutMass — Handoff Document (2026-04-29)

## Proje Nedir?
GMass'ın Outlook Web versiyonu. Chrome Extension (MV3) + FastAPI backend.
**Durum:** PRODUCTION CANLIDA. Chrome Web Store'da **v0.1.8** yayında. SEO infrastructure aktif.

## 🎯 Bu Handoff Neye Yarıyor
Context dolduğundan yeni session'a geçiyoruz. Bu doküman bu session'daki tüm
ilerlemeyi, mevcut state'i ve kalan işleri kapsıyor. Yeni session sadece bunu
+ `Claude.md`'yi okuyarak devam edebilmeli.

---

## 🔴 ÖNCELİKLE OKUNMASI GEREKEN: `Claude.md`

`Claude.md`'nin başında **"🔴 KULLANICI ETKİSİ KURALI"** var. Özet:
1. Kullanıcı-etkili her değişiklik için ÖNCE onay al, sonra kodla.
2. Backward compat koru, feature flag kullan, reversible migration yaz.
3. User-visible değişiklik varsa proaktif bildirim yap (email/banner/release notes).
4. Push öncesi sanity check listesi yap.
5. Backend-only invisible değişiklikler için sınırlı istisna.

Live kullanıcı var — kural ihlal edilmesin.

---

## 🚦 Canlı Durum (2026-04-29 itibariyle)

### Chrome Web Store
- **v0.1.8 ONAYLANDI ve canlıda** (`adcfddainnkjomddlappnnbeomhlcbmm`)
- Atlanmış sürümler: v0.1.2 (paketlendi, ship olmadı), v0.1.5/v0.1.6/v0.1.7 (review'larından geçti veya v0.1.8'e dahil oldu)

### Backend (Railway)
- **outmass-production** (FastAPI/uvicorn)
- **outmass-worker** (Celery worker, concurrency=2)
- **outmass-beat** (Celery beat scheduler)
- Tüm migration'lar uygulandı (010-017)
- Env vars (önemli ekler bu session'da):
  - `ALLOWED_EXTENSION_IDS=adcfddainnkjomddlappnnbeomhlcbmm,acdafphnihddolfhabbndfofheokckhl`
  - `INACTIVITY_NUDGE_ENABLED=false` (default OFF, user istediğinde açacak)
  - `INACTIVITY_AUTOCANCEL_ENABLED=false` (Phase 6 için reserve, kullanılmıyor)

### Database (Supabase)
- 17 migration (010-017) uygulandı, tüm RLS policy'leri aktif
- Yeni tablolar bu session'da: `audit_log`, `users_archive`
- Yeni kolonlar: `users.last_login_at, last_activity_at, requires_reauth`,
  `users.inactivity_nudge_sent_at, inactivity_warning_60d_sent_at, inactivity_warning_90d_sent_at`,
  `user_tokens.has_onedrive_scope`, `campaigns.attachments`,
  `contacts.replied_at` (+ partial index)

### Stripe
- Live mode aktif, $9 Starter + $19 Pro
- Webhook handler: checkout, subscription.deleted/updated, invoice.payment_failed
- **YENİ:** `charge.dispute.created` + `charge.dispute.closed` handlers (chargeback otomatik subscription cancel + audit + Telegram alert)

### SEO / getoutmass.com
- 3 blog makalesi yayında
- robots.txt + sitemap.xml mevcut
- Tüm ana sayfalarda canonical + meta description
- Google Search Console: site verified, sitemap submit edildi (kullanıcı yapacak), 3 sayfa indexed

---

## ✅ Bu Session'da Yapılanlar (Özet)

### v0.1.4 — Lifecycle, audit, multi-extension OAuth (Phases 1-7)
- **Phase 1:** Uninstall landing page (`docs/uninstall.html`) + `/api/uninstall-feedback` endpoint + extension `setUninstallURL`
- **Phase 2:** Migration 010 — `users.last_login_at, last_activity_at` + tüm FK'lere `ON DELETE CASCADE`
- **Phase 2.5:** Migration 011 — `audit_log` tablosu + IP anonymize fonksiyonu (1 yıl sonra /24-/48). `models/audit.py` emit helper. Hooks: oauth_granted, login, campaign_created, contacts_uploaded, send_triggered, email_sent (per recipient). Privacy policy Section 7 güncel.
- **Phase 3:** Migration 012 — `users_archive` tablo + `archive_and_delete_user` RPC. Self-service "Delete my account" — Account tab → Danger Zone. Aktif Stripe sub varsa 409. MailerSend confirmation email. Privacy + Terms güncellemeleri.
- **Phase 4:** `last_login_at` ve `last_activity_at` (15-dk rate-limited write) hook'lar `auth.py` ve `get_current_user`'a eklendi.
- **Phase 5:** Migration 013 — `users.inactivity_nudge_sent_at`. 30-day inactivity nudge beat task (`workers/inactivity_nudge.py`). Default OFF.
- **Phase 6 (minimal):** Migration 014 — 60d/90d warning kolonları. 3-tier email cadence (30/60/90 gün). Auto-cancel YAPILMADI (sadece email warnings).
- **Phase 7:** Stripe `charge.dispute.created/closed` webhook handlers — auto subscription cancel + audit + Telegram alert.
- **Multi-extension OAuth:** `/auth/login?ext={chrome.runtime.id}` + state-based ext_id passthrough + ALLOWED_EXTENSION_IDS allowlist. Hem store hem dev unpacked aynı backend'le sign in olabilir.

### v0.1.5 — OneDrive attachments (ilk girişim, ship olmadı)
- Migration 015 — `campaigns.attachments JSONB`
- `/api/onedrive/share-link` endpoint
- Microsoft Graph File Picker SDK v8 (iframe)
- `/auth/login?include_onedrive=true` incremental consent
- **Sorun:** Microsoft `onedrive.live.com` X-Frame-Options: DENY → personal account'larda iframe açılmıyor. Bu sürüm ship edilmedi.

### v0.1.6 — Engagement metrics + resilience
- **Engaged metric** (open OR click OR reply) — Reports'ta dürüst tek-rakam
- **Reply detection** — daily Inbox scan beat (`workers/reply_detector.py`), Mail.Read scope kullanıyor (zaten vardı). Migration 017 — `contacts.replied_at`.
- **Resume button** — partial campaigns için `POST /campaigns/{id}/resume`. Reports'ta yalnızca `partial` status'undaki kampanyalarda görünür.
- **`utils/graph_retry.py`** — 5xx/network/429 için 3-attempt exponential backoff
- **`config.OUTBOUND_HTTP_TIMEOUT`** — connect 10s / read 30s / write 10s, send path'lerde explicit
- **Stuck `sending` resetter beat** — saatlik, 30+ dk takılı kampanyaları `partial` veya `scheduled`'a döndürür

### v0.1.7 — Custom OneDrive picker (iframe yerine native)
- `GET /api/onedrive/browse?folder_id=root` endpoint — folder navigation
- Sidebar'da custom HTML list browser (breadcrumbs + click-to-navigate)
- iframe + Microsoft SDK kodu kaldırıldı

### v0.1.8 — Friendly no-OneDrive error
- Microsoft "no OneDrive" senaryosu (eski Outlook.com, SPO license'sız work account) için spesifik error code `no_onedrive`
- 10 dilde lokalize mesaj — "Bu hesapta OneDrive yok, başka hesapla giriş yap"

### Critical bug fixes (commit-level)
- `1007d72` — Microsoft Graph 401'i de `needs_files_scope` olarak handle (önceden sadece 403)
- `1159f16` — **URGENT:** v0.1.5'teki refresh token regression'u (token exchange + refresh path'lerine OneDrive scope koşulsuz eklendi → AADSTS65001 → tüm Mail-only user sign-in kırıldı). State-based scope tracking + `user_tokens.has_onedrive_scope` flag ile çözüldü (Migration 016).
- `36672d1` — Stripe portal errors lokalize edildi (`no_stripe_customer`, `stripe_not_configured`)
- `0d6947b` — `user.unsubscribe_text` artık tüm async send path'lerde (3 worker) honor ediliyor (önceden hardcoded "Abonelikten cik" Türkçe)
- `37ad2ee` — Manage Subscription error UX (sessiz failure → backend error mesajı surface)
- `859f642` — Locale-aware datetimes (`_i18nOverride` confusion) + 401 session-expired banner
- `ac1f0ac` — Multi-extension OAuth state-based routing
- `c651cb1` — `Claude.md` user-impact kural eklendi (1. öncelik, OVERRIDES EVERYTHING)

### SEO infrastructure (yeni bölüm)
- 3 blog makalesi `docs/blog/` altında:
  - `how-to-send-mass-emails-from-outlook.html` (~2,200 kelime, "outlook mail merge" hedefli)
  - `gmass-for-outlook.html` (~1,800 kelime, "gmass alternative" hedefli, comparison)
  - `outlook-mail-merge-limit.html` (~2,000 kelime, "outlook send limit" hedefli)
- Her makale `Article` + `FAQPage` JSON-LD schema, OG meta, canonical, internal+external link
- `docs/blog/index.html` — blog listing
- `docs/sitemap.xml` — 9 URL
- `docs/robots.txt` — sitemap point + plans/store-listing exclude
- `docs/_config.yml` — site title/description/url
- Tüm ana sayfalara (index, pricing, privacy, terms, refund, launch) canonical tag eklendi (`e80848c`)
- `docs/store-listing/listings.json` — OneDrive + Reply detection feature bullets 10 dilde eklendi (`abf9300`)

---

## ⏳ Yarım Kalan İşler ve Sıradaki Adımlar

### A) HEMEN (kullanıcı yapacak)
1. **Microsoft Edge Add-ons store yüklemesi**
   - `partner.microsoft.com/dashboard/microsoftedge` → ücretsiz dev hesabı
   - Aynı `outmass-v0.1.8.zip` yüklenir, manifest değişmez
   - Listing copy'sini Chrome'dakinden paste et
   - Review 1-3 gün
   - Detaylı adım: bu HANDOFF altında "Edge Add-ons Detayları"
2. **Google Search Console — sitemap submit + URL inspector**
   - Sol menü → Site Haritaları → `sitemap.xml` ekle
   - URL inspector → 4 yeni blog URL'i için "Dizine ekleme iste"
   - **Not:** AppSource için OutMass uygun değil (Office Add-in framework gerek). Edge Add-ons yeterli.

### B) Yakın gelecek (post-launch quality, launch-blocker DEĞİL)
- [ ] Non-root Celery worker (Dockerfile + `useradd --uid 1000`) — güvenlik sıkılaştırma, paid user 500+ olunca yap
- [ ] **Phase 6 full** — auto-pause @ 60 gün + auto-cancel @ 90 gün (şu an SADECE warning email var, gerçek Stripe modifikasyon yok). Yapmak istersen kullanıcı ile detaylı tartış, feature flag default OFF + 5-10 user manuel test sonrası açılır.
- [ ] Çoklu-stage follow-up (şu an 1 stage). GMass 8 stage destekliyor, comparison'da eksik.
- [ ] **Behavior triggers** ("recipient X linkine tıklarsa Y mail gönder")
- [ ] **Team plan** (paylaşılan template'ler, role-based access)
- [ ] Bounced email handling — şu an bounce'ları izlemiyoruz
- [ ] Sender reputation score (SpamAssassin benzeri)

### C) Marketing / büyüme
- [ ] **SEO daha fazla makale** — sıradaki önerilen başlıklar:
  - "Best Mail Merge Tools for Outlook in 2026" (comparison hub)
  - "Cold Email from Outlook: Complete Guide for SaaS Founders" (founder persona)
  - "How to Schedule Email in Outlook (3 Methods + Limits)"
  - "Outlook Add-in vs Browser Extension for Mass Email"
  - "Track Email Opens in Outlook (Without Macros)"
- [ ] **Backlinks** — guest post outreach, HARO, podcast appearance (sosyal — kullanıcı asosyal, yapmıyor)
- [ ] **Niche newsletter sponsorship** ($200-500 bütçe gerek)
- [ ] **Reddit single-post** — r/Outlook, r/sales, r/EntrepreneurRideAlong (kullanıcı engagement düşük tercih ediyor)
- [ ] **Indie Hackers launch** — daha sosyal-low Product Hunt alternatifi
- [ ] **Product Hunt — KULLANICI İSTEMİYOR** (sosyal anksiyete + asosyal profil). Listede tutmuyoruz.

### D) Müşteri ilk gelirken yapılacaklar
- [ ] `INACTIVITY_NUDGE_ENABLED=true` aç — ama önce kendi inbox'una test et (HANDOFF içinde test SQL var)
- [ ] Stripe Dashboard'da `charge.dispute.created` + `charge.dispute.closed` event'lerinin webhook'a abone olduğunu kontrol et
- [ ] Manuel: ilk paid user'a "thanks" emaili at, ne kullandığını sor

### E) Doc/UX iyileştirmeler
- [ ] Backend error code'larını lokalize etmek için general framework (örn. `error: "no_stripe_customer"` → her dilde i18n key). Şu an portal endpoint'inde manuel yapıldı, generalize edilmedi.
- [ ] Error tracking dashboard (PostHog'da var ama görünür değil)

---

## 🔧 Backend Mimari (Quick Reference)

### Beat schedule (`backend/workers/celery_app.py`)
```
process-followups-hourly     | 60 min       | followup_worker.process_followups
process-scheduled-campaigns  | 5 min        | scheduled_worker.process_scheduled_campaigns
evaluate-ab-tests            | 10 min       | scheduled_worker.evaluate_ab_tests
daily-report                 | 14:00 UTC    | daily_report.send_daily_report
check-user-tokens            | 03:00 UTC    | scheduled_worker.check_user_tokens
reset-stuck-sending-campaigns | 60 min      | scheduled_worker.reset_stuck_sending_campaigns
anonymize-audit-log-ips      | 03:30 UTC    | scheduled_worker.anonymize_audit_log_ips
send-inactivity-nudges       | 04:00 UTC    | inactivity_nudge.send_inactivity_nudges (gated)
send-inactivity-warnings-60d | 04:15 UTC    | inactivity_nudge.send_inactivity_warnings_60d (gated)
send-inactivity-warnings-90d | 04:30 UTC    | inactivity_nudge.send_inactivity_warnings_90d (gated)
detect-replies               | 05:00 UTC    | reply_detector.detect_replies
```

### Tablolar (Supabase)
```
users                  — accounts (now with last_login_at, last_activity_at, requires_reauth, plan, ...)
campaigns              — campaign metadata (now with attachments JSONB, scheduled_for)
contacts               — recipients per campaign (now with replied_at)
events                 — open/click tracking log
follow_ups             — scheduled follow-up emails
suppression_list       — user-level email opt-outs
templates              — saved email templates
ab_tests               — A/B subject test data
user_tokens            — MS OAuth tokens (now with has_onedrive_scope)
audit_log              — immutable action log (5-year retention, IP anon @ 1y)
users_archive          — anonymized post-deletion records
launch_subscribers     — pre-launch waitlist (legacy)
```

### Routes
```
/auth                    — OAuth flow, state-based ext routing, incremental consent
/campaigns               — CRUD, send, test-send, archive, resume, stats, export, ab-test, followups
/billing                 — Stripe checkout, portal, webhook (incl. chargebacks)
/templates               — CRUD
/ai                      — Claude email writer (Pro, 50/mo limit)
/settings                — Sender profile, suppression, dedup config, requires_reauth flag
/account                 — DELETE /account (self-service GDPR delete)
/api/onedrive            — share-link, browse
/api/uninstall-feedback  — anonymous feedback from uninstall landing
/api/feedback            — extension feedback form
/api/error-report        — extension client errors → PostHog
/track                   — pixel + click + unsubscribe (lightweight, separate router)
/launch                  — pre-launch waitlist signup
```

### Send pipeline (3 path)
1. **Immediate** — `routers/campaigns.py:send_campaign` (sync, async httpx with retry)
2. **Scheduled** — `workers/scheduled_worker.py:process_scheduled_campaigns` (5-min beat)
3. **Follow-up** — `workers/followup_worker.py:process_followups` (1-hr beat)
4. (Dead) `workers/email_worker.py` — async queue, prepared but unused

Tüm 3 path:
- `models.ms_token.get_fresh_access_token` (auto-flags `requires_reauth` on permanent failure)
- `utils.graph_retry.post_with_retry` (5xx/429/network 3-attempt expo backoff)
- `utils.email_attachments.render_attachments_footer` (OneDrive chips)
- Per-email audit emit (`audit.emit_email_sent`)
- `OUTBOUND_HTTP_TIMEOUT` ile bounded request

---

## 📂 Dosya Yapısı (Quick Reference)

```
backend/
  config.py              | env vars + OUTBOUND_HTTP_TIMEOUT + ALLOWED_EXTENSION_IDS + INACTIVITY_*
  main.py                | FastAPI app, error report, feedback endpoints
  database.py            | Supabase singleton
  schema.sql             | Full schema (all migrations applied)
  migrations/            | 001-017 (010-017 added this session)
  routers/
    auth.py              | OAuth flow, multi-ext state, incremental consent (od flag)
    campaigns.py         | Campaign + send + resume
    billing.py           | Stripe + chargeback webhooks
    templates.py
    ai.py                | Claude API
    settings.py
    tracking.py          | /t/ pixel, /c/ click, /unsubscribe/
    launch.py
    account.py           | DELETE /account (NEW this session)
    onedrive.py          | /api/onedrive/share-link, /api/onedrive/browse (NEW)
  models/
    user.py              | + touch_login, maybe_touch_activity
    campaign.py          | + attachments param
    contact.py
    template.py
    ab_test.py
    followup.py
    ms_token.py          | + has_onedrive_scope-aware refresh
    audit.py             | Audit log emitter (NEW)
    user_archive.py      | RPC wrapper for archive_and_delete (NEW)
  utils/
    merge_tags.py
    email_classifier.py
    email_attachments.py | OneDrive chip rendering (NEW)
    graph_retry.py       | Bounded retry for Graph API calls (NEW)
  workers/
    celery_app.py        | Beat schedule (10+ tasks)
    email_worker.py      | (dead) async per-email queue
    scheduled_worker.py  | + reset_stuck_sending + anonymize_audit_log_ips + check_user_tokens
    followup_worker.py
    daily_report.py
    inactivity_nudge.py  | 3-tier 30/60/90d nudges (NEW, gated)
    reply_detector.py    | Daily Inbox scan (NEW)
  tests/
    119+ unit tests (was ~118 at session start)
    test_audit_log.py, test_account_delete.py, test_resilience.py,
    test_onedrive.py, test_inactivity_nudge.py, test_chargeback_webhook.py,
    test_token_lifecycle.py, test_auth_multi_ext.py,
    test_uninstall_feedback.py, test_unsubscribe_label.py,
    test_activity_tracking.py (NEW this session)

extension/   (v0.1.8)
  manifest.json          | 0.1.8
  background.js          | Multi-ext OAuth, structured 402/409 errors, ONEDRIVE_BROWSE/SHARE_LINK,
                         | RESUME_CAMPAIGN, DELETE_ACCOUNT, MS_LOGIN_ONEDRIVE, sessionExpired flag
  sidebar.html           | + Attachments section, OneDrive picker modal (custom),
                         | + Engaged + Replied metric boxes, + Resume section, + Delete account modal
  sidebar.js             | + OneDrive custom picker logic, + handleSessionExpired,
                         | + getActiveLocale, + delete account flow
  popup.js               | + Manage Sub error detail surface
  i18n.js                | + getActiveLocale() shared helper
  CHANGELOG.md           | v0.1.0 → v0.1.8
  _locales/              | 10 dil, ~70 yeni key bu session'da
  styles/sidebar.css     | + OneDrive picker, + danger-zone, + Engaged/Replied callouts, + Resume

docs/                    | GitHub Pages (getoutmass.com)
  index.html, pricing.html, privacy.html, terms.html, refund.html, launch.html, uninstall.html
  blog/                  | NEW
    index.html
    how-to-send-mass-emails-from-outlook.html
    gmass-for-outlook.html
    outlook-mail-merge-limit.html
  store-listing/listings.json   | 10 dil, +OneDrive +Reply bullets
  sitemap.xml            | NEW
  robots.txt             | NEW
  _config.yml            | + url/title/description
```

---

## 🔑 Kritik Env Var'lar (Railway)

```
SUPABASE_URL=https://qhfefazyfhyqnjcmfmdd.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role>
JWT_SECRET=<32-byte hex>

AZURE_CLIENT_ID=3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5
AZURE_CLIENT_SECRET=<from Azure>
AZURE_REDIRECT_URI=https://outmass-production.up.railway.app/auth/callback
AZURE_EXTENSION_ID=adcfddainnkjomddlappnnbeomhlcbmm
ALLOWED_EXTENSION_IDS=adcfddainnkjomddlappnnbeomhlcbmm,acdafphnihddolfhabbndfofheokckhl

BACKEND_URL=https://outmass-production.up.railway.app
CORS_ORIGINS=chrome-extension://adcfddainnkjomddlappnnbeomhlcbmm,...

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STARTER_PRICE_ID=price_1TNBQNJ2B12lELVmRjjuFmth
STRIPE_PRO_PRICE_ID=price_1TNBQlJ2B12lELVmS0rxYD4F
STRIPE_PORTAL_CONFIG_ID=bpc_1TNvl3QsbO4Gj1Xr3VaOSWcU

REDIS_URL=rediss://default:...@upstash.io:6379  (pay-as-you-go from this session)

ANTHROPIC_API_KEY=sk-ant-...
POSTHOG_API_KEY=phc_...  (EU)
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=8445487787

MAILERSEND_API_KEY=mlsn_...
MAILERSEND_FROM_EMAIL=support@getoutmass.com
MAILERSEND_FROM_NAME=OutMass

INACTIVITY_NUDGE_ENABLED=false   ← still OFF, user will flip when ready
INACTIVITY_NUDGE_DAYS=30
INACTIVITY_AUTOCANCEL_ENABLED=false   ← Phase 6 reserved
```

---

## 🧪 Test Komutları

```bash
npm run test:unit           # backend pytest (~250 unit)
npm run test:e2e            # Playwright (48 i18n visual + UI)
npm run test:all
```

Bu session sonunda: **261 unit + 48 E2E = 309 test geçiyor**.

---

## 📦 Paketleme

`outmass-v*.zip` gitignore'da. Her release için yeniden paketlenir:

```bash
# Linux / macOS
cd extension && zip -r ../outmass-v0.1.X.zip . -x "*.DS_Store" && cd ..
```
```powershell
# Windows
cd extension; Compress-Archive -Path * -DestinationPath ../outmass-v0.1.X.zip -Force
```

---

## 🌐 Edge Add-ons Detayları (sıradaki adım için)

[Microsoft Partner Center](https://partner.microsoft.com/en-us/dashboard/microsoftedge/):
1. Microsoft hesabı ile sign in (ücretsiz, Chrome'un $5'ından farklı)
2. **Create new extension** → **Upload package** → `outmass-v0.1.8.zip`
3. **Listing details:**
   - Title: `OutMass — Mass Email for Outlook` (Chrome ile aynı)
   - Summary: `Send personalized mail merge campaigns from Outlook. Tracking, follow-ups, AI writer, OneDrive attachments.`
   - Description: `docs/store-listing/listings.json` → `en.description` paste
   - Screenshots: 1280×800 veya 640×400 (Chrome'daki dosyalar uyar)
   - Privacy URL: `https://getoutmass.com/privacy.html`
   - Support URL: `mailto:support@getoutmass.com`
   - Categories: Productivity / Communication
4. **Submit for certification** → 1-3 gün

Onaylanınca: Edge Add-ons store'da `Edge://extensions/` üzerinden bulunabilir.

---

## 🔍 Kritik Bilgiler / Edge Cases

### Owner test hesabı
- `outmassapp@outlook.com`, plan='pro' (manuel set, gerçek Stripe sub yok — dogfooding)
- user_id: `7ebce016-e2af-4f88-9e00-90bdfdb18cba`
- "Manage Subscription" butonu bu hesapta `no_stripe_customer` döner — beklenen davranış

### Dev unpacked extension ID
- `acdafphnihddolfhabbndfofheokckhl` — Azure redirect list'inde + ALLOWED_EXTENSION_IDS'te
- Local geliştirmede unpacked yüklenirse aynı backend ile sign in olabilir

### Subscription test akışı
- Free hesap → Stripe live ile kart ekle → $9 öder → Pro'ya geçer
- LAUNCH50 promo kodu (50% off, 100 redemption, May 31 2026 expiry)

### OneDrive feature canlıda
- Yeni user'lar default sign-in'de OneDrive scope istemiyor (incremental consent)
- "+ Add OneDrive link" tıklayınca:
  1. İlk kullanım: consent modal (OneDrive scope'u açıkla)
  2. Picker açılır → backend `/api/onedrive/browse` → user'ın OneDrive root'u listelenir
  3. Eğer Files scope yok: backend 401/403 → `needs_files_scope` → frontend MS_LOGIN_ONEDRIVE tetikler → user MS consent ekranında approve eder → picker yeniden açılır
- "No OneDrive" hesaplarında: `no_onedrive` error code → friendly message gösterir

### Reply detection
- Default ON, daily 05:00 UTC çalışır
- Mail.Read scope kullanır (zaten default scope'ta vardı)
- Inbox'tan recent messages tarar, sender email + sent_at karşılaştırması ile match eder
- `contacts.replied_at` set eder, audit_log'a `replies_detected` event'i yazar
- Reports'ta "Replied" + "Reply rate" gösterir

### Inactivity nudge — DEFAULT OFF
- 3 beat task gün boyunca tarar (04:00, 04:15, 04:30 UTC) ama `INACTIVITY_NUDGE_ENABLED=false` olduğu için early-return ediyor
- Açmadan önce kendi hesabınla test:
  ```sql
  -- 30d test
  UPDATE users SET last_activity_at = NOW() - INTERVAL '31 days',
                   inactivity_nudge_sent_at = NULL
  WHERE email='outmassapp@outlook.com';
  ```
  Sonra Railway worker shell'inden:
  ```bash
  celery -A workers.celery_app call workers.inactivity_nudge.send_inactivity_nudges
  ```
- Mail içeriği `workers/inactivity_nudge.py` `_html_tier1/2/3` fonksiyonlarında, value-positive ton

### Account delete (self-service GDPR)
- Sidebar Account → Danger Zone → Delete my account
- 2-step confirmation (typed "DELETE" + irreversibility checkbox)
- Aktif Stripe sub varsa 409 + "Cancel subscription first" mesajı
- DB: `archive_and_delete_user` RPC → `users_archive`'e anonymized kopya + `DELETE FROM users` (CASCADE all dependents)
- Email: MailerSend confirmation gönderilir

### Audit log retention
- 5 yıl saklanır (Türk VUK ve UK/EU tax compliance)
- IP adresleri 1 yıl sonra `/24` (IPv4) veya `/48` (IPv6) anonymize edilir
- Privacy policy Section 7'de açıkça belirtildi

### Stripe chargeback handling
- `charge.dispute.created` → subscription auto-cancel + plan='free' + audit + Telegram alert
- `charge.dispute.closed` → audit + alert (kazanılan dispute'lar otomatik geri yüklenmez)
- Stripe Dashboard'da event'lerin webhook'a abone olduğunu KONTROL ET

---

## 🐛 Bilinen Sınırlamalar / Bug'lar

1. **AppSource uyumsuz** — Office Add-in framework gerekiyor, mevcut Chrome extension uygun değil. Edge Add-ons doğru kanal.
2. **Çoklu-stage follow-up yok** — Şu an 1 stage. GMass 8 stage destekliyor.
3. **Behavior triggers yok** — "if clicked X then send Y" akışı yok.
4. **Team plan yok** — paylaşılan template/role yok.
5. **Bounce handling primitive** — Microsoft NDR'lerini takip etmiyoruz, contact `failed` status'a geçmiyor.
6. **Phase 6 partial** — 60d/90d email warnings var, gerçek auto-pause/cancel YAPILMADI.
7. **Sender reputation score yok** — SpamAssassin benzeri heuristic check yapılabilir.
8. **Backend error mesajları kısmen lokalize** — portal endpoint'inde structured code var, diğer 4xx errors raw English string.

---

## 🎯 Önerilen Bir Sonraki Adımlar

Yeni session'a başlarken kullanıcıya şunu sor:

1. **v0.1.8 ne kadar süredir live?** Performans nasıl? Yeni user / paid user aldı mı?
2. **Edge Add-ons yüklendi mi?** Yoksa o Phase'i hızlandır.
3. **Google Search Console'da indexed sayfa sayısı arttı mı?** (3 → 8-9 olmalı)
4. **`INACTIVITY_NUDGE_ENABLED` aç ihtiyacı var mı?** İlk paid user gelince anlamlı.
5. **Bir bug raporu / customer feedback mailini almış mı?** O öncelikli.

Yoksa mantıklı sonraki yatırımlar (kullanıcı önceliği ne ise):

- **SEO content** — 3-5 makale daha (HANDOFF "Marketing" bölümünde liste var)
- **Multi-stage follow-up** — kullanıcı en çok eksik dediği şey burası, GMass parity
- **Bounce handling** — Microsoft NDR webhook / Inbox scan ile contact `failed` işaretle
- **Phase 6 full** — auto-pause/cancel logic (HIGH RISK, kullanıcı onayı şart)

---

## 📝 Stack
- **Extension:** Vanilla JS, Chrome MV3
- **Backend:** Python 3.11+, FastAPI
- **DB:** Supabase (PostgreSQL, RLS aktif)
- **Queue:** Celery + Upstash Redis (SSL, pay-as-you-go from this session)
- **AI:** Claude (Anthropic API)
- **Error Tracking:** PostHog (EU)
- **Billing:** Stripe live
- **Email (outbound):** MailerSend
- **Email (inbound):** Cloudflare Email Routing → Outlook
- **Notifications:** Telegram Bot API
- **Hosting:** Railway (3 services: web + worker + beat)
- **Frontend tools:** GitHub Pages (getoutmass.com)
- **Test:** Pytest (~261 unit) + Playwright (48 E2E) = 309 total

---

## 🔗 Hızlı Linkler

- Repo: github.com/alibayar/outmass-site
- Web: https://getoutmass.com
- Chrome Web Store: https://chromewebstore.google.com/detail/outmass/adcfddainnkjomddlappnnbeomhlcbmm
- Backend: https://outmass-production.up.railway.app
- Supabase: https://qhfefazyfhyqnjcmfmdd.supabase.co
- Google Search Console: https://search.google.com/search-console
- Stripe Dashboard: https://dashboard.stripe.com/

---

**Bu handoff'u yeni session'a verin. `Claude.md` ile birlikte yeterli olacaktır.**
