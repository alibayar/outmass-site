"""Light-touch email classifiers — role accounts and disposable domains.

Currently used only for upload counters (warn, don't skip). The lists are
deliberately small; expand on demand. Case-insensitive everywhere.
"""

# Local-part prefixes that indicate a shared / role mailbox.
ROLE_PREFIXES = frozenset({
    "admin", "info", "noreply", "no-reply", "postmaster", "abuse",
    "support", "billing", "sales", "contact", "hello", "hr",
    "webmaster", "root", "security", "privacy", "help",
})

# Domains known for throwaway / single-use addresses.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamailblock.com",
    "tempmail.com", "temp-mail.org", "10minutemail.com", "10minutemail.net",
    "throwaway.email", "yopmail.com", "yopmail.net", "trashmail.com",
    "trashmail.io", "getnada.com", "nada.email", "dispostable.com",
    "maildrop.cc", "sharklasers.com", "fakeinbox.com", "jetable.org",
    "spambog.com", "spamgourmet.com", "mytemp.email", "anonaddy.me",
    "tutanota.com",  # not strictly disposable but commonly used for throwaways
    "fakemail.fr", "tempail.com", "tempinbox.com",
})


def is_role_account(email: str) -> bool:
    """True if the local part looks like a shared mailbox (info@, admin@, ...)."""
    if "@" not in email:
        return False
    local = email.split("@", 1)[0].strip().lower()
    return local in ROLE_PREFIXES


def is_disposable(email: str) -> bool:
    """True if the domain is a known throwaway / disposable mail provider."""
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1].strip().lower()
    return domain in DISPOSABLE_DOMAINS
