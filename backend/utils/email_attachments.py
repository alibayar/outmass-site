"""
OutMass — Email attachment footer rendering.

Single source of truth for how a campaign's OneDrive attachments
appear inside outbound emails. Used by every send path:
  - routers/campaigns.py (immediate send)
  - workers/scheduled_worker.py (scheduled + AB winner)
  - workers/followup_worker.py (auto follow-ups)
  - workers/email_worker.py (legacy async queue, dead code today)

Centralizing prevents drift — if we change the visual style or add
a click-tracking wrapper later, only one function changes.

Output is appended to the email body BEFORE the unsubscribe footer
and the tracking pixel, so attachments render visually above the
unsubscribe line but the pixel still fires regardless of whether
the recipient scrolls down.
"""

import html as _html_lib


def render_attachments_footer(attachments) -> str:
    """Return an HTML block listing attachments. Empty string when none.

    `attachments` is the JSONB column from campaigns — a list of
    {name, url} dicts. We coerce defensively because Python clients
    sometimes give us None or string-encoded JSON instead.
    """
    if not attachments:
        return ""
    if not isinstance(attachments, list):
        return ""

    rows = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        url = att.get("url") or ""
        name = att.get("name") or "file"
        if not url:
            continue
        # Escape both — a malicious filename like "<script>" must not
        # execute in the recipient's mail client, and the URL must not
        # break out of the href context.
        safe_name = _html_lib.escape(name, quote=True)
        safe_url = _html_lib.escape(url, quote=True)
        rows.append(
            f'<a href="{safe_url}" '
            f'style="display:inline-block;text-decoration:none;color:#0078d4;'
            f'background:#f3f2f1;border-radius:6px;padding:8px 12px;'
            f'margin:4px 6px 4px 0;font-size:13px;font-family:'
            f'-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">'
            f'\U0001F4CE {safe_name}</a>'
        )

    if not rows:
        return ""

    # Plain wrapper, no extra heading text — recipients understand
    # paperclip + filename pills without an "Attachments:" label, and
    # any extra prose risks looking like a marketing footer.
    return (
        '<div style="margin:18px 0 12px 0;line-height:1.6;">'
        + "".join(rows)
        + "</div>"
    )
