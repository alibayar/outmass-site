# Chrome Web Store Localized Listings

This directory contains the store listing content for all 10 supported languages.

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
  "ja": { ... }
}
```

## Character limits (Chrome Web Store)

- **title**: max 45 characters
- **summary**: max 132 characters (hard limit)
- **description**: max 16,000 characters (we aim for ~2,000)

All content verified under limits.

## How to use

When submitting to Chrome Web Store Developer Dashboard:

1. Go to Developer Dashboard → your extension → **Store listing**
2. For each language:
   - Click **Add localized listing**
   - Select the language code
   - Copy `title`, `summary`, `description` from listings.json
   - Add the SAME screenshots to each language (or localized screenshots if you want to translate the UI captures)
3. Save each localized listing
4. Submit for review

## Language codes (Chrome Web Store mapping)

| Our key | Chrome Web Store |
|---------|------------------|
| en | English (US) / en_US |
| tr | Turkish / tr |
| de | German / de |
| fr | French / fr |
| es | Spanish / es |
| ru | Russian / ru |
| ar | Arabic / ar |
| hi | Hindi / hi |
| zh_CN | Chinese (Simplified) / zh_CN |
| ja | Japanese / ja |

## Updates

If pricing or features change, update **all 10 entries** in `listings.json` and re-submit localized listings in the Developer Dashboard.
