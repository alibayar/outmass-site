# OutMass — Handoff Document (2026-06-01)

## Proje Nedir?
GMass'ın Outlook Web versiyonu. Chrome Extension (MV3) + FastAPI/Supabase backend.
**Durum:** PRODUCTION CANLIDA. İlk gerçek aktif kullanıcılar var.

Yeni session bu doküman + `Claude.md`'yi okuyarak devam edebilmeli.

---

## 🔴 ÖNCE OKU: `Claude.md` — KULLANICI ETKİSİ KURALI
1. Kullanıcı-etkili her değişiklik için ÖNCE onay al, sonra kodla/commit/push.
2. Backward compat koru, reversible migration, feature flag.
3. User-visible değişiklik → proaktif bildirim (email/banner/release notes).
4. Push öncesi sanity check listesi.
5. Backend-only invisible değişiklikler için sınırlı istisna.
Live kullanıcı var — kural ihlal edilmesin.

---

## 🚦 Canlı Durum (2026-06-01)

### Chrome Web Store
- **v0.1.10 ONAYLANDI + canlı** (`adcfddainnkjomddlappnnbeomhlcbmm`)
- **v0.1.11 kullanıcı tarafından YÜKLENDİ** (free tier raise) — review'da veya yeni onaylandı
- `outmass-v0.1.11.zip` repo kökünde (gitignore'da, her release yeniden paketlenir)

### Edge Add-ons — DEVAM EDİYOR
- Kullanıcı `outmass-v0.1.11.zip`'i Edge'e yüklüyor (Partner Center, ücretsiz).
- **🔴 Onay gelince KRİTİK:** Edge yeni bir extension ID atar. OAuth callback yalnızca allowlist'teki ID'lere redirect eder. **Edge ID'sini Railway `ALLOWED_EXTENSION_IDS` env'ine virgülle EKLE** (mevcutları silme — Chrome'u bozmaz) → otomatik deploy → Edge sign-in test. Azure'a dokunma (callback sabit).

### Backend (Railway) — 3 service: web + worker + beat
- **outmass-production** (FastAPI/uvicorn), **outmass-worker** (Celery), **outmass-beat**
- Migration'lar 001-019 uygulandı (019 = manual_promo_until)
- Health: `https://outmass-production.up.railway.app/` → `{"status":"ok"}`

### DB (Supabase) `qhfefazyfhyqnjcmfmdd`
- 19 migration, RLS aktif. Tablolar: users, campaigns, contacts, events, follow_ups, suppression_list, templates, ab_tests, user_tokens, audit_log, users_archive, launch_subscribers
- Önemli kolonlar: `users.last_seen_extension_version`, `users.manual_promo_until`, `users.month_reset_date` (aylık quota reset), `contacts.status` (pending/sent/deferred/failed), `contacts.replied_at`

### Stripe (live): $9 Starter + $19 Pro. Chargeback webhook'ları aktif.
### MailerSend: **Free plan** (100 mail/ay). Domain getoutmass.com DKIM+SPF verified.
### SEO: getoutmass.com (GitHub Pages), 3 blog makalesi, sitemap, robots.

---

## 📦 SÜRÜM GEÇMİŞİ (bu makinede yapılanlar)

| Sürüm | İçerik |
|---|---|
| v0.1.8 | (önceki) OneDrive, reply detection, account delete, audit log |
| **v0.1.9** | **Funnel telemetry** — 46 PostHog event (install→signup→send), `analytics.js` MV3 client, `X-Extension-Version` header, migration 018 (`last_seen_extension_version`). account_deleted anonim gönderilir. |
| **v0.1.10** | **UX fixes**: (1) 4-state contacts (deferred/failed) + Resume; (2) manual promo expiry (migration 019 + beat); (3) merge-tag UX — Send/Test-Send/Preview üçü de structured error + localized + CSV-derived `available_tags`, DRY helper `_raise_if_bad_merge_tags`, yeni `POST /campaigns/validate-tags`; (4) popup dinamik version + plan-aware Manage Subscription. |
| **v0.1.11** | **Free tier raise** (PARAMETRIK) — Free 50→250, Starter 2000→2500, upload hizalandı. Bkz. parametrik altyapı ↓ |

---

## ⚙️ PARAMETRİK LİMİT ALTYAPISI (v0.1.11 — kritik bilgi)

Plan limitleri artık **env-driven + API-exposed**. İleride limit değiştirmek = **Railway env değişkeni + otomatik deploy. KOD DEĞİŞMEZ, EXTENSION GÜNCELLENMEZ, WEB STORE REVIEW YOK.**

- `config.py`: `FREE_PLAN_MONTHLY_LIMIT = int(os.getenv("FREE_PLAN_MONTHLY_LIMIT", "250"))` (+ STARTER 2500, PRO 10000, FREE/STARTER/PRO_UPLOAD_ROW_LIMIT 250/2500/10000). Hepsi env-overridable.
- `config.monthly_limit_for_plan(plan)` / `upload_limit_for_plan(plan)` — tek kaynak helper.
- `GET /settings` → `monthly_limit` + `upload_limit` döndürür (plan-derived).
- Extension: background.js bunu storage'a yazar (`monthlyLimit`), sidebar.js oradan okur (hardcode YOK, fallback 250/2500 sadece offline).
- **Limit değiştirmek için:** Railway → `outmass-production` → Variables → örn. `FREE_PLAN_MONTHLY_LIMIT=300` → deploy. Enforcement + display birlikte güncellenir.
- **ASİMETRİ KURALI:** Limit artırmak hep pozitif, düşürmek hep negatif (churn). **Sadece ARTIR, düşürme.**

---

## 👥 GERÇEK KULLANICILAR (owner test hesapları hariç: outmassapp@outlook.com [pro, manuel], bayar_ali@hotmail.com, outmass.review@outlook.com)

| User | Durum | Outreach |
|---|---|---|
| **Abdul Khaliq** (khaliqabdul@hotmail.com) | 🟢 İlk gerçek aktif. 49 mail tek kampanyada, **%84 open rate**, v0.1.10 kullanıyor. free→250 oldu. | ✅ "early user + büyük free + feedback" maili (2026-06-01). **Privacy: performans verisi (%84) SÖYLENMEDİ** — kullanıcı haklı olarak "izleniyor" hissini istemedi. |
| **Jack Eason** (Jack@gaadvisorygroup.com) | Business lead (advisory). Sign-in yapmış, hiç kampanya atmamış (audit: sadece oauth+login). | ✅ onboarding nudge + 250 free + 5-dk rehber (2026-06-01) |
| **Abid** (abidalibalospura@outlook.com) | merge-tag'e takılmıştı (v0.1.10 ile çözüldü). Starter promo verildi, `manual_promo_until=2026-06-12` → beat otomatik free'ye düşürecek. | ✅ apology + gift maili |
| **Dan Han** (katherineh8702@outlook.com) | Nisan'da yüklemiş, hiç atmamış. | ✅ nudge maili (cevap yok) |

**Outreach kuralı:** Tüm direct support mailleri **BCC outmassapp@outlook.com** (memory: `support_email_bcc.md`). MailerSend ile gönderilir (key Railway env'de, local `.env`'de YOK — gönderirken elden verilir veya `MAILERSEND_API_KEY=... python script`).

---

## 📊 ANALYTICS / FUNNEL

- **PostHog** (key: `phc_kSzEWG2WxxMYzokbnxUWuohvAeXvH3ovdKioxXoez27r`, host us.i.posthog.com). **MCP genelde session'da BAĞLI DEĞİL** → PostHog web UI'dan bak, VEYA asıl behavioral veri Supabase `audit_log`'da.
- **Funnel SQL pattern** (audit_log event_type'lar): `oauth_granted → login → campaign_created → contacts_uploaded → send_triggered → email_sent`. Engagement: `contacts` tablosu `opened_at`/`clicked_at`/`replied_at`.
- **Sıradaki:** v0.1.9+ telemetry 7 gün veri biriktirince PostHog funnel insight → en büyük dropoff → sonraki fix.

---

## 🔑 KRİTİK ENV VAR'LAR (Railway)
```
SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / JWT_SECRET
AZURE_CLIENT_ID=3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5 / AZURE_CLIENT_SECRET / AZURE_REDIRECT_URI=.../auth/callback
ALLOWED_EXTENSION_IDS=adcfddainnkjomddlappnnbeomhlcbmm,acdafphnihddolfhabbndfofheokckhl  ← Edge onayında Edge ID EKLE
BACKEND_URL / CORS_ORIGINS
STRIPE_SECRET_KEY=sk_live_... / STRIPE_WEBHOOK_SECRET / STRIPE_STARTER_PRICE_ID / STRIPE_PRO_PRICE_ID / STRIPE_PORTAL_CONFIG_ID
REDIS_URL (Upstash) / ANTHROPIC_API_KEY / POSTHOG_API_KEY (phc_kSz...) / TELEGRAM_BOT_TOKEN+CHAT_ID
MAILERSEND_API_KEY=mlsn_... / MAILERSEND_FROM_EMAIL=support@getoutmass.com
INACTIVITY_NUDGE_ENABLED=false (default OFF)
# PARAMETRIK (opsiyonel, default'lar kodda): FREE_PLAN_MONTHLY_LIMIT, STARTER_PLAN_MONTHLY_LIMIT, FREE_UPLOAD_ROW_LIMIT, ...
```
⚠️ MailerSend key bu session'da chat'te paylaşıldı — endişe varsa revoke + yenile.

---

## 🧪 TEST & PAKETLEME
```bash
npm run test:unit    # backend pytest (299 geçiyor) — integration HARİÇ (env gerektirir)
npm run test:e2e     # Playwright 48 (i18n visual regression)
npm run test:all     # ikisi + integration (integration LOCAL'DE ÇALIŞMAZ — JWT_SECRET strong + gerçek DB gerekir, pre-existing)
```
NOT: `test:unit` (299) + `test:e2e` (48) = kod güvencesi. Integration testleri CI/prod env gerektirir, local fail NORMAL.

Paketleme (Windows): `cd extension; Compress-Archive -Path * -DestinationPath ../outmass-vX.Y.Z.zip -Force; cd ..`

**Worktree workflow:** Feature işi `.worktrees/<branch>` içinde (gitignored). `.env`'i worktree'ye kopyala (`cp backend/.env .worktrees/<b>/backend/.env`). Subagent'lara MUTLAK worktree path ver (yoksa main checkout'ta çalışıp master'ı kirletebilirler — bu session'da 2 kez oldu, recover edildi). Bitince merge + `git worktree remove --force` + `git branch -d`.

---

## 🏗️ BACKEND MİMARİ (quick ref)

### Beat schedule (`workers/celery_app.py`)
```
process-followups (60m), process-scheduled-campaigns (5m), evaluate-ab-tests (10m),
daily-report (14:00 UTC), check-user-tokens (03:00), reset-stuck-sending (60m),
anonymize-audit-log-ips (03:30), inactivity nudges 30/60/90d (04:00/15/30, GATED OFF),
detect-replies (05:00), expire-manual-promos (04:45)  ← v0.1.10
```

### Send pipeline (3 path, hepsi 4-state + classify)
1. Immediate: `campaigns.py:send_campaign`
2. Scheduled: `scheduled_worker.process_scheduled_campaigns`
3. Follow-up: `followup_worker.process_followups` (⚠️ original sent contact'lara bump atar — mark_failed EKLENMEDİ, duplicate-send riski)

Send hatası sınıflandırma: `utils/send_classify._classify_failure(status_code)` → 408/409/429/5xx/None=deferred (retry), diğer 4xx=failed (kalıcı). `contact.mark_failed(id, status)`. Resume `get_resumable_contacts` (pending+deferred).

### Merge-tag validation: `_raise_if_bad_merge_tags(subject, body, allowed_keys, available_tags)` — send + test-send + `/campaigns/validate-tags` (Preview) üçü de kullanır. `utils/merge_tags`: STANDARD_TAGS camelCase (firstName, lastName, email, company, position + sender*), regex `{{\w+}}` (boşluk yok).

---

## 🐛 BİLİNEN SINIRLAMALAR / BACKLOG (öncelik sırası)

### Yakın (v0.1.12 adayları)
- [ ] **I-1: A/B deferred recovery** — `evaluate_ab_tests` deferred A/B contact'larını winner-send'de almıyor (`get_pending_contacts` kullanıyor). Narrow (A/B Pro feature, az kullanım). `get_resumable_contacts`'e çevir + sign-off.
- [ ] **Multi-stage follow-up** — şu an 1 stage. GMass 8 destekliyor. Kullanıcının en çok eksik dediği.
- [ ] **Bounce handling** — Microsoft NDR'leri izlenmiyor, contact `failed` olmuyor.

### Orta
- [ ] **Viral footer DENEYİ** — "Sent with OutMass" REDDEDİLDİ (B2B'de profesyonelliksiz). Ama 50+ aktif user olunca opt-out + tracking ile ROI ölçülebilir deney olarak tekrar değerlendir.
- [ ] **Weak test** — `test_contact_states.py` get_resumable filter coverage zayıf (conftest fake filtrelemiyor).
- [ ] **Live merge-tag validation** (compose sırasında {{tag}} canlı uyarı) — şu an sadece send/test/preview anında.
- [ ] **send_failed failure_type aggregate** (Phase 4 skip edildi — per-contact status Supabase'de yeterli).

### Düşük
- [ ] Non-root Celery worker (güvenlik, 500+ paid user'da)
- [ ] Phase 6 full (auto-pause/cancel @ 60/90d — şu an sadece email warning)
- [ ] Team plan, sender reputation score
- [ ] Backend error mesajları kısmen lokalize (merge-tag/portal structured, diğer 4xx raw)

### Marketing
- [ ] SEO 3-5 makale daha (founder persona, comparison hub)
- [ ] Paid ad ARAŞTIRILDI, kullanıcı ÜCRETSIZ kanalları seçti (Bing $250 promo notu var ama ertelendi)
- [ ] Product Hunt — kullanıcı İSTEMİYOR (sosyal anksiyete). Reddit/PH listede tutulmuyor.

---

## 🎯 ÖNERİLEN SONRAKİ ADIMLAR (yeni session)
1. **Edge onayı geldi mi?** → Edge ID'yi `ALLOWED_EXTENSION_IDS`'e ekle + test.
2. **Outreach reply'ları?** Abdul/Jack/Abid/Dan'den dönüş = en yüksek conversion sinyali. Geldiyse öncelikli.
3. **v0.1.9+ funnel verisi** (7 gün biriktiyse) → PostHog insight → en büyük dropoff → fix.
4. **Yeni paid user / first revenue** geldi mi? Geldiyse "thanks" + ne kullandığını sor.
5. Yoksa backlog'dan: multi-stage follow-up (en çok istenen) veya bounce handling.

---

## 🔗 Hızlı Linkler
- Repo: github.com/alibayar/outmass-site · Web: getoutmass.com
- Chrome Store: chromewebstore.google.com/detail/outmass/adcfddainnkjomddlappnnbeomhlcbmm
- Backend: outmass-production.up.railway.app · Supabase: qhfefazyfhyqnjcmfmdd.supabase.co
- Design/plan docs: `docs/plans/` (2026-05-05 funnel, 2026-05-30 v0.1.10, 2026-06-01 free-tier)
- Memory: `support_email_bcc.md`, `project_v019_funnel.md`

**Bu handoff + `Claude.md` yeterli. Stack: Vanilla JS MV3 + FastAPI + Supabase + Celery/Upstash + Stripe + MailerSend + PostHog + Railway.**
