"""Tests for role-account + disposable-domain detection."""
from utils.email_classifier import is_role_account, is_disposable


def test_role_account_info():
    assert is_role_account("Info@Acme.com")


def test_role_account_admin():
    assert is_role_account("admin@example.com")


def test_not_role_account():
    assert not is_role_account("alice@example.com")


def test_role_account_without_at():
    assert not is_role_account("just-text")


def test_disposable_mailinator():
    assert is_disposable("x@mailinator.com")


def test_disposable_case_insensitive():
    assert is_disposable("x@MAILINATOR.COM")


def test_not_disposable_gmail():
    assert not is_disposable("x@gmail.com")


def test_disposable_without_at():
    assert not is_disposable("plain-text")
