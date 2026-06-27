"""Unit tests for the OAuth install-source tag (chrome vs edge store).

The OAuth callback tags each person's install source in PostHog from the
?ext=<id> the extension already sends — so we can break users down by store
without an extension update. This locks the store-ID → source mapping.
"""
from routers.auth import _install_source, _CHROME_EXT_ID, _EDGE_EXT_ID


def test_chrome_store_id_maps_to_chrome():
    assert _install_source(_CHROME_EXT_ID) == "chrome"


def test_edge_store_id_maps_to_edge():
    assert _install_source(_EDGE_EXT_ID) == "edge"


def test_unknown_or_missing_maps_to_other():
    assert _install_source("some-other-id") == "other"
    assert _install_source("") == "other"
    assert _install_source(None) == "other"


def test_store_ids_are_distinct():
    assert _CHROME_EXT_ID != _EDGE_EXT_ID
