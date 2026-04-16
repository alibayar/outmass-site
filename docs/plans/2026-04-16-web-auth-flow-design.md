# Web Auth Flow Migration — Design Doc

**Date:** 2026-04-16
**Status:** Approved

## Problem
SPA (Single Page App) OAuth flow produces short-lived, rotating refresh tokens (24h, bound to browser session). This blocks server-side features: scheduled sending, follow-up emails, A/B test winner auto-send — all of which run in Celery workers that need fresh access tokens hours/days later.

## Solution: Backend-Centric Web Auth Flow with JWT-in-URL pickup

Azure AD already has both SPA and Web platforms registered for the same app. The Web platform supports long-lived refresh tokens (90 days) when using `client_secret` in token exchange.

### Flow
```
1. Extension → chrome.identity.launchWebAuthFlow with backend redirect URI
   auth URL uses: redirect_uri=https://outmass-production.up.railway.app/auth/callback
2. User authenticates with Microsoft
3. MS redirects to backend: /auth/callback?code=XXX
4. Backend:
   a. Exchanges code + AZURE_CLIENT_SECRET for tokens (Web platform)
   b. Stores long-lived refresh_token in user_tokens table
   c. Creates OutMass JWT
   d. Redirects to extension: https://<ext-id>.chromiumapp.org/auth#jwt=TOKEN&email=X&name=Y&plan=Z
5. Extension extracts JWT from URL hash fragment
6. Extension stores JWT in chrome.storage, login complete
```

### Why hash fragment instead of query string?
- Never sent to server (browser-only parse)
- Not in server access logs
- Not in browser history for extension-scoped URLs
- Standard OAuth implicit flow pattern

### Celery workers
After migration, workers can refresh access tokens indefinitely using stored refresh_token + client_secret. No user interaction needed.

## Changes

### Backend
- `config.py`: add `AZURE_CLIENT_SECRET`, `AZURE_REDIRECT_URI`
- `routers/auth.py`: add `GET /auth/callback` endpoint that does code exchange, creates JWT, redirects to extension
- `workers/followup_worker.py`: already uses client_secret from config (we just need env var set)
- `workers/scheduled_worker.py`: same

### Extension
- `background.js`:
  - `startMSLogin`: change redirect_uri to backend callback URL
  - Remove PKCE (not needed with Web flow — client_secret is server-side)
  - Remove `exchangeCodeForTokens` (backend does it now)
  - Add URL hash parser to extract JWT from launchWebAuthFlow result
  - `syncAuthWithBackend` becomes unnecessary (backend returns JWT directly)

### Migration for existing users
- Old SPA flow state in chrome.storage will be ignored
- First time user opens extension after update, they click login again
- New Web flow completes, refresh_token stored server-side
- All subsequent actions use new JWT

## Security considerations
- `AZURE_CLIENT_SECRET` only in Railway env vars, never in extension code
- JWT in URL hash only visible to extension (launchWebAuthFlow scope)
- State parameter for CSRF protection

## Dependencies
- Azure AD Web platform already configured with redirect URI
- Client secret already added to Railway Variables
