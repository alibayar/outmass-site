# inbox

Drop files here for Claude to read — invoices, exports, screenshots, logs,
anything pulled out of a dashboard or an email.

Contents are gitignored. This README is the only tracked file, so the folder
exists on a fresh clone.

## Why not just read them where they are

The Downloads folder is denied by a rule in `.claude/settings.local.json`,
added deliberately on 2026-08-14. It holds unrelated personal files, and
pointing an agent at it to answer one question means handing it the rest.
Working from a directory inside the project keeps that boundary clear and
makes it obvious what has been shared and what has not.

Delete things when you are done with them. Nothing here is a record; the
record goes in `docs/plans/`.
