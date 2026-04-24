\# GMass for Outlook — Chrome Extension



\## Proje Özeti

GMass'ın Outlook Web versiyonu. Chrome Extension (MV3).

Hedef: 2-3 haftada ilk gelir.



\## Stack

\- \*\*Extension\*\*: Vanilla JS, Chrome MV3

&nbsp; - content\_script.js → Outlook Web DOM injection

&nbsp; - background.js → Service Worker, API calls, Alarms

&nbsp; - popup.html/js → Auth + plan gösterimi

\- \*\*Backend\*\*: Python 3.11+, FastAPI

&nbsp; - /api → REST endpoints

&nbsp; - /track → Pixel + click tracking (ayrı lightweight router)

&nbsp; - Celery worker → async email queue

\- \*\*DB\*\*: Supabase (PostgreSQL)

\- \*\*Queue\*\*: Upstash Redis

\- \*\*Auth\*\*: JWT (backend) + Microsoft OAuth 2.0 (Graph API)

\- \*\*Billing\*\*: Stripe Checkout + Webhooks



\## Klasör Yapısı

```

/extension

&nbsp; manifest.json        # MV3

&nbsp; content\_script.js    # DOM injection

&nbsp; background.js        # Service Worker

&nbsp; popup.html / popup.js

&nbsp; sidebar.html         # iframe olarak inject edilir

&nbsp; styles.css



/backend

&nbsp; main.py              # FastAPI app

&nbsp; routers/

&nbsp;   auth.py

&nbsp;   campaigns.py

&nbsp;   tracking.py

&nbsp;   billing.py

&nbsp; workers/

&nbsp;   email\_worker.py    # Celery

&nbsp; models/

&nbsp;   db.py              # Supabase client

&nbsp; requirements.txt



/docs

&nbsp; ARCHITECTURE.md

```



\## 🔴 KULLANICI ETKİSİ KURALI (EN ÖNCELİKLİ — OVERRIDES EVERYTHING)

Proje artık \*\*canlı kullanıcılara hizmet veriyor\*\*. Bu nedenle her session'da aşağıdaki kuralları \*\*istisnasız\*\* uygula:

\### 1. Kullanıcıyı etkileyecek her değişikten ÖNCE onay al

"Kullanıcıyı etkiler" kapsamı:
- API contract (endpoint ekle/sil/param değiştir)
- DB schema migration (column ekle/sil/rename, index, RLS)
- Extension davranış değişikliği (UI flow, default ayar, shortcut)
- Email içerik/konu/rate/zamanlama değişikliği
- OAuth / auth flow / JWT TTL
- Pricing / plan limits / Stripe logic
- i18n metni silme/yeniden adlandırma
- Rate limit / quota / send delay
- Any breaking change whatsoever

\*\*Davranış:\*\* Planı yaz, trade-off'ları açıkla, \*\*"onaylar mısın?"\*\* diye sor. Onay almadan kod yazma. Commit atma. Push atma.

\### 2. Minimum impact prensibi

Onaylı değişiklik yaparken bile:
- \*\*Backward compat\*\* koru (legacy client'ler kırılmamalı)
- Default davranışı değiştirirken feature flag kullan
- Silmek yerine deprecate et (1-2 sürüm bekle, sonra sil)
- Migration yazarken \*\*reversible\*\* ol (down migration düşün)
- Worker/beat değişikliklerinde iş kaybı yok — idempotent + ack late
- Feature kapat / kısıtla ≠ feature sil

Amaç: kullanıcı \*\*ne yaptığını fark etmeyecek\*\* kadar sorunsuz deploy.

\### 3. Etkilenen kullanıcıya proaktif bildirim

Değişiklik gerçekten user-visible ise (UX değişir, ayar resetlenir, feature kaybolur, veri taşınır, fiyat değişir), \*\*kullanıcı bilmek zorunda\*\*:

| Değişiklik tipi | Bildirim yolu |
|---|---|
| Breaking / data migration | Email (MailerSend) + sidebar banner + release notes |
| Feature deprecation | Sidebar notice 2 sürüm önceden |
| Price change | Email 30 gün önceden + portal |
| Downtime / maintenance | Email + sidebar banner + status page |
| New feature (opt-in) | Release notes + optional onboarding tooltip |
| Bug fix (behavior değişir) | Release notes (user-friendly dil, bug itirafı değil) |

Default: \*\*sessizce değiştirme\*\*. "How would I feel if I were this user and this changed without warning?" testi yap.

\### 4. Deploy öncesi sanity check

Her kullanıcı-etkili commit push edilmeden önce kontrol et:
- [ ] User'a ne değişiyor? 1 cümle yaz.
- [ ] Migration reversible mi?
- [ ] Canlı user'lar mid-session ise ne olur? (race condition)
- [ ] Onay alındı mı? Bildirim planı hazır mı?
- [ ] Geri alma planı (rollback) var mı?

Herhangi biri \*\*hayır\*\* ise \*\*push atma\*\*, kullanıcıya geri dön.

\### 5. Backend-only değişiklikler için istisna (sınırlı)

\*\*Kullanıcıya görünmeyen\*\* iç iyileştirmeler (örn. Redis command optimizasyonu, logging, test) onay olmadan yapılabilir \*\*ancak\*\*:
- Etki tamamen invisible olmalı (davranış değişmiyor, performans aynı ya da daha iyi)
- Rollback trivial olmalı
- Push'tan önce hızlı verification

Şüphe varsa → onay al. \*\*Default: onay iste.\*\*

---

\## Kritik Kurallar (teknik)

1\. \*\*Outlook Web only\*\* — desktop Outlook veya Add-in değil

2\. \*\*Graph API ile gönder\*\* — DOM'dan send etme

3\. \*\*Rate limiting zorunlu\*\* — spam değil, batch gönderim

4\. \*\*Freemium gate\*\*: 50 email/ay ücreti Supabase'den kontrol et

5\. \*\*MV3 uyumu\*\* — XMLHttpRequest değil fetch, background script değil service worker



\## Microsoft Graph API

\- Scope: `Mail.Send`, `Mail.Read` (reply detection için)

\- Auth flow: OAuth 2.0 delegated

\- Endpoint: `https://graph.microsoft.com/v1.0/me/sendMail`



\## Öncelik Sırası (MVP)

1\. Content script → compose window detect + toolbar inject

2\. Sidebar UI → CSV upload + merge preview

3\. Background SW → Graph API send

4\. Tracking server → pixel + click

5\. Stripe webhook → plan aktivasyon

6\. Follow-up scheduler → Alarm API



\## Test

\- Extension: Chrome'da `chrome://extensions` → Load unpacked

\- Backend: `uvicorn main:app --reload`

\- Graph API: Microsoft Graph Explorer ile test et

