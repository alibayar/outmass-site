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



\## Kritik Kurallar

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

