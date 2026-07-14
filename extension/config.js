/**
 * OutMass — Extension Configuration
 */

// Backend URL — production default, can be overridden via chrome.storage for dev
// For local dev: chrome.storage.local.set({ backendUrl: "http://localhost:8000" })
//
// Primary is our own domain: shared-platform hosts like *.railway.app are
// blocked wholesale by some corporate filters and national firewalls, and
// users on those networks could never even sign in (2026-07-14 incident).
// The railway URL stays as an automatic fallback — if the primary is
// unreachable at the network level, backendFetch retries there.
var OUTMASS_BACKEND_URL = "https://api.getoutmass.com";
var OUTMASS_BACKEND_FALLBACK_URL = "https://outmass-production.up.railway.app";

// PostHog project public key (safe to ship in extension — public by design,
// same value the backend uses in POSTHOG_API_KEY env var on Railway).
var OUTMASS_POSTHOG_KEY = "phc_kSzEWG2WxxMYzokbnxUWuohvAeXvH3ovdKioxXoez27r";
// EU region — the project (key phc_kSzE…) lives on PostHog EU. Sending to the
// US host silently drops events (US doesn't recognize an EU key), which broke
// all extension funnel telemetry until v0.1.14. The /batch/ endpoint is
// CORS-enabled, so the service-worker fetch works WITHOUT a host_permission
// (verified: it reflects access-control-allow-origin for chrome-extension://).
var OUTMASS_POSTHOG_HOST = "https://eu.i.posthog.com";
