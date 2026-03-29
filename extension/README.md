# OutMass — Chrome Extension + Backend

Outlook Web uzerinden toplu email kampanyalari gondermek icin Chrome Extension (MV3) + FastAPI backend.

## Azure App Registration (Zorunlu)

Microsoft OAuth 2.0 icin Azure'da uygulama kaydi gerekli:

### Adimlar

1. [portal.azure.com](https://portal.azure.com) adresine git
2. **Azure Active Directory** → **App registrations** → **New registration**
3. Ayarlar:
   - **Name**: `OutMass`
   - **Supported account types**: "Accounts in any organizational directory and personal Microsoft accounts"
   - **Redirect URI**: Platform = **Web**, URI asagidaki degeri gir

### Redirect URI'yi Bulmak

1. Extension'i Chrome'a yukle (asagidaki "Kurulum" bolumune bak)
2. Extension'in Service Worker console'unu ac:
   `chrome://extensions` → OutMass → "Service worker" linkine tikla
3. Console'da su logu bul:
   ```
   [OutMass-BG] Redirect URI: https://EXTENSION_ID.chromiumapp.org/auth
   ```
4. Bu URI'yi Azure portal'da Redirect URI olarak ekle

### API Permissions

Azure portal'da uygulama sayfasinda:

1. **API permissions** → **Add a permission**
2. **Microsoft Graph** → **Delegated permissions** sec
3. Su izinleri ekle:
   - `Mail.Send`
   - `Mail.Read`
   - `User.Read`
4. (Admin consent gerektirmez — delegated permissions)

### Client ID'yi Koda Eklemek

1. Azure portal'da **Overview** sayfasindan **Application (client) ID** degerini kopyala
2. `extension/background.js` dosyasini ac
3. Su satiri bul ve degistir:
   ```js
   const AZURE_CLIENT_ID = "YOUR_CLIENT_ID_HERE";
   ```
   Yerine:
   ```js
   const AZURE_CLIENT_ID = "buraya-gercek-client-id";
   ```

## Supabase Kurulumu

1. [supabase.com](https://supabase.com) adresinden proje olustur
2. **SQL Editor** ac
3. `backend/schema.sql` dosyasinin icerigini yapistir ve calistir
4. **Settings** → **API** → URL ve anon key'i kopyala

## Backend Kurulumu

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# .env dosyasini doldur (Supabase URL/Key, JWT secret)
uvicorn main:app --reload --port 8000
```

Health check: http://localhost:8000 → `{"status":"ok","version":"0.1.0"}`

## Extension Kurulumu

1. Chrome'da `chrome://extensions` adresine git
2. Sag ustten **Developer mode** aktif et
3. **Load unpacked** tikla → `extension/` klasorunu sec
4. Extension yuklendi, toolbar'da mavi ikon gorunecek

## Test Adimlari

### 1. Backend Testi

```bash
# Backend calisiyor mu?
curl http://localhost:8000
# → {"status":"ok","version":"0.1.0","service":"outmass-api"}
```

### 2. Auth Testi

1. Azure portal'dan Client ID al, `background.js`'e yapistir
2. `chrome://extensions` → OutMass → **Reload**
3. Extension popup'ini tikla
4. **"Microsoft ile Baglan"** butonuna tikla
5. MS login sayfasi acilmali → giris yap
6. Popup'ta adiniz ve email adresiniz gorunmeli
7. Console'da `[OutMass-BG] Backend sync OK, JWT saved` logu gorunmeli

### 3. Email Gonderim Testi

1. Outlook'ta compose ac → sidebar ac
2. Ornek CSV hazirla:
   ```csv
   email,firstName,company
   test@example.com,Ali,Acme
   ```
3. CSV'yi sidebar'a yukle
4. Subject: `Merhaba {{firstName}}`
5. Body: `{{company}} icin teklifimiz var`
6. "Onizleme" → merge sonucunu kontrol et
7. "Gonder" tikla → progress gosterilmeli
8. Backend logs'ta gonderim gorulmeli
9. Gercek email geldi mi kontrol et

### 4. Tracking Testi

1. Email gonderildikten sonra, email'deki gorunmez pixel'i kontrol et
2. Email acildiginda: backend `events` tablosunda `open` event gorunmeli
3. Email'deki link tiklandiginda: `click` event gorunmeli

### Console Kontrolleri

Service Worker console'unu ac (`chrome://extensions` → "Service worker"):

- `[OutMass-BG] Starting MS OAuth flow...` → flow basladi
- `[OutMass-BG] LOGIN_SUCCESS: user@outlook.com` → basarili giris
- `[OutMass-BG] Backend sync OK, JWT saved` → backend baglantisi basarili
- `[OutMass-BG] Campaign created` → kampanya olusturuldu

### Storage Kontrolu

DevTools → Application → chrome.storage.local:

- `accessToken` → MS Graph token
- `backendJwt` → OutMass backend JWT
- `user` → `{ email: "...", name: "..." }`
- `plan` → "free" veya "pro"

## Dosya Yapisi

```
extension/
  manifest.json         # MV3 manifest
  config.js             # Backend URL config
  background.js         # Service Worker + OAuth + backend sync
  graph_api.js          # Graph API wrapper (importScripts)
  content_script.js     # DOM injection + compose detection
  popup.html / popup.js # Extension popup (auth UI)
  sidebar.html / sidebar.js  # Campaign panel (iframe)
  styles/
    content.css          # Injected button + sidebar wrapper
    sidebar.css          # Sidebar internal styles
  icons/
    icon16.png           # Placeholder (solid blue)
    icon48.png
    icon128.png

backend/
  main.py               # FastAPI app + CORS
  config.py             # Environment variables
  database.py           # Supabase client
  schema.sql            # Database schema
  routers/
    auth.py             # Microsoft OAuth → JWT
    campaigns.py        # Campaign CRUD + send
    tracking.py         # Open/click pixel tracking
    billing.py          # Stripe placeholder
  workers/
    email_worker.py     # Celery worker (optional, MVP sync)
  models/
    user.py             # User model helpers
    campaign.py         # Campaign model helpers
    contact.py          # Contact model helpers
  requirements.txt
  .env.example
  Procfile              # Railway deployment
```

## Teknik Notlar

- Extension: Vanilla JS, sifir dependency, MV3 uyumlu
- Backend: Python 3.11+, FastAPI, Supabase
- OAuth 2.0 + PKCE (client secret gerekli degil)
- Token otomatik yenilenir (refresh token ile)
- Email gonderim: MS Graph API (kullanicinin kendi hesabindan)
- Tracking: 1x1 pixel (open) + link redirect (click)
- Rate limiting: her email arasi 1sn, 429 → 60sn retry
- Freemium: 50 email/ay (free), sinirsiz (pro)
- MVP: sync send (Celery opsiyonel)
- Console log prefix'leri: `[OutMass-CS]`, `[OutMass-BG]`, `[OutMass-Sidebar]`
