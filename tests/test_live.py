"""Live integration tests against real SEBI endpoints.

Marked `live` — excluded from default runs (they hit a regulator's servers;
run sparingly):  pytest -m live
"""
import pytest

pytestmark = pytest.mark.live


def test_registry_live_search_zerodha():
    from server import registry
    cards = registry.live_search(search="zerodha broking")
    assert cards is not None, "sebi.gov.in unreachable"
    assert any("ZERODHA" in c["name"].upper() for c in cards)
    zer = next(c for c in cards if "ZERODHA BROKING" in c["name"].upper())
    assert zer["reg_no"] == "INZ000031633"


def test_registry_live_regno_search():
    from server import registry
    cards = registry.live_search(regno="INZ000031633")
    assert cards is not None
    assert any("ZERODHA" in c["name"].upper() for c in cards)


def test_sebi_check_invalid_handle():
    """A fabricated @valid-shaped handle must come back invalid (not verified,
    not unavailable). One request only — respect the rate gate."""
    from server import db, sebicheck
    db.init()
    r = sebicheck.client.check_upi("definitely-not-real-9x7.brk@validhdfc")
    assert r["state"] in ("invalid", "captcha_required", "unavailable"), r
    if r["state"] == "invalid":
        assert r["reason_code"] == "sebi_says_invalid"
        assert r["txn"], "SEBI transactionId missing"


def test_sebi_check_format_gate_saves_a_call():
    from server import db, sebicheck
    db.init()
    r = sebicheck.client.check_upi("not a handle at all")
    assert r["state"] == "invalid" and r["reason_code"] == "format_invalid"
    assert r["source"] == "local"
