/**
 * OutMass — Extension Configuration
 */

// Backend URL — production default, can be overridden via chrome.storage for dev
// For local dev: chrome.storage.local.set({ backendUrl: "http://localhost:8000" })
var OUTMASS_BACKEND_URL = "https://outmass-production.up.railway.app";

// PostHog project public key (safe to ship in extension — public by design,
// same value the backend uses in POSTHOG_API_KEY env var on Railway).
var OUTMASS_POSTHOG_KEY = "phc_kSzEWG2WxxMYzokbnxUWuohvAeXvH3ovdKioxXoez27r";
var OUTMASS_POSTHOG_HOST = "https://us.i.posthog.com";
