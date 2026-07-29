# Chrome / Edge Store Localized Listings

This directory contains the store listing content for all 11 listing languages
(10 UI languages + pt-BR, which is listing-only until the pt locales ship in
0.1.27).

## File: `listings.json`

Structure:
```json
{
  "en": { "title": "...", "summary": "...", "description": "..." },
  "tr": { ... },
  "de": { ... },
  "fr": { ... },
  "es": { ... },
  "ru": { ... },
  "ar": { ... },
  "hi": { ... },
  "zh_CN": { ... },
  "ja": { ... },
  "pt_BR": { ... }
}
```

## Character limits (Chrome Web Store)

- **title**: max 45 characters
- **summary**: max 132 characters (hard limit)
- **description**: max 16,000 characters (we aim for ~2,000)

All content verified under limits (`node docs/store-listing/check-limits.js`).

## Language-count policy (claims discipline)

The description claims "10 UI languages". Count = distinct languages, not
locale folders: the extension ships 11 folders but `zh` is only a fallback for
zh-TW/HK browsers carrying the same Simplified content as `zh_CN`, so it does
NOT add a language. After 0.1.27 (pt_BR + pt_PT) the honest count becomes 11
(Portuguese counted once). Update the number in ALL entries at that cut.

## How to use

When submitting to the Chrome Web Store Developer Dashboard:

1. Go to Developer Dashboard → your extension → **Store listing**
2. For each language:
   - Click **Add localized listing**
   - Select the language code
   - Copy `title`, `summary`, `description` from listings.json
   - Add the SAME screenshots to each language (or localized screenshots if you
     want to translate the UI captures)
3. Save each localized listing
4. Submit for review

For **Edge (Partner Center)**: Edit → Store listings → one page per language;
paste the same content. NOTE: saving Edge listing changes creates a new
submission that goes through certification again (metadata-only reviews are
usually fast and do not touch the live package) — batch listing edits, don't
trickle them.

## Language codes (store mapping)

| Our key | Chrome Web Store | Edge Partner Center |
|---------|------------------|---------------------|
| en | English (US) / en_US | English (United States) |
| tr | Turkish / tr | Turkish |
| de | German / de | German |
| fr | French / fr | French |
| es | Spanish / es | Spanish |
| ru | Russian / ru | Russian |
| ar | Arabic / ar | Arabic |
| hi | Hindi / hi | Hindi |
| zh_CN | Chinese (Simplified) / zh_CN | Chinese (Simplified) |
| ja | Japanese / ja | Japanese |
| pt_BR | Portuguese (Brazil) / pt_BR | Portuguese (Brazil) |

## Updates

If pricing or features change, update **all entries** in `listings.json`, run
the limits check, and re-paste the affected localized listings in BOTH
dashboards. Store copy only claims what is LIVE (claims-follow-product rule).
