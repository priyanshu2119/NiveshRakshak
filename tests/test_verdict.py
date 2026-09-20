"""Verdict precedence — the money paths (ADVERSARIAL-REVIEW scenarios 1–8)."""
from server import policy, verdict
from server.verdict import (CAPTCHA_PENDING, CAUTION, RED_FLAG, UNVERIFIABLE,
                            VERIFIED, build, classify_upi_local, cross_checks)


def P(state, **kw):
    base = {"kind": "upi", "value": "x@y", "state": state}
    base.update(kw)
    return base


INVALID = P("invalid", value="scam@ybl", reason_code="personal_handle", psp="ybl")
VERIFIED_P = P("verified", value="taurus.cf.brk@validaxis",
               entity={"name": "TAURUS CORPORATE ADVISORY SERVICES LIMITED",
                       "role": "Broker", "regNo": "INZ000099999"}, txn="TXN-1")
UNAVAIL = P("unavailable", value="a@validhdfc", reason="timeout")
REG_EXACT = {"state": "exact", "matches": [{"name": "ZERODHA BROKING LIMITED",
                                            "reg_no": "INZ000031633"}]}


def test_scenario1_real_name_fake_channel():
    """IIFL pattern: exact registry match can NEVER override a failed primary."""
    v = build([INVALID], REG_EXACT, [], [], {}, {})
    assert v["headline"]["state"] == RED_FLAG
    assert v["registry"]["state"] == "exact"  # still shown, as context


def test_scenario2_fake_valid_looking_handle_needs_live_check():
    """@valid-shaped handles are never judged locally — they go to SEBI Check."""
    assert classify_upi_local("zerodha.brk@validhdfc") is None
    assert classify_upi_local("anything@validicici") is None


def test_local_classification():
    assert classify_upi_local("scam99@ybl")["reason_code"] == "personal_handle"
    assert classify_upi_local("9877006482@kotak811")["reason_code"] == "personal_handle"
    assert classify_upi_local("oldbroker@hdfcbank")["reason_code"] == "not_valid_handle"


def test_scenario8_unavailable_poisons_headline():
    v = build([VERIFIED_P, UNAVAIL], None, [], [], {}, {})
    assert v["headline"]["state"] == UNVERIFIABLE  # never more positive than least-certain input


def test_captcha_pending_surfaces():
    v = build([P("captcha_required")], None, [], [], {}, {})
    assert v["headline"]["state"] == CAPTCHA_PENDING


def test_verified_clean():
    v = build([VERIFIED_P], None, [], [], {}, {})
    assert v["headline"]["state"] == VERIFIED


def test_brand_vs_legal_name_mismatch_keeps_verified():
    """Groww→Nextbill-style: supporting flag only, headline stays VERIFIED."""
    v = build([VERIFIED_P], None, [],
              [{"id": "entity_name_mismatch", "handle": VERIFIED_P["value"],
                "entity_name": "NEXTBILL", "claimed_name": "GROWW"}], {}, {})
    assert v["headline"]["state"] == VERIFIED
    assert v["supporting"]["flags"][0]["id"] == "entity_name_mismatch"


def test_scenario3_category_mismatch_is_red_flag():
    """Brief §5.2.3: claims MF, handle registered as broker → RED FLAG even
    though the handle itself is genuine."""
    v = build([VERIFIED_P], None, [],
              [{"id": "category_mismatch", "handle": VERIFIED_P["value"],
                "claimed_category": "mf", "suffix": "brk"}], {}, {})
    assert v["headline"]["state"] == RED_FLAG
    assert "category_mismatch" in v["headline"]["reasons"]


def test_no_payment_info_is_never_all_clear():
    v = build([], REG_EXACT, [], [], {}, {})
    assert v["headline"]["state"] == CAUTION


def test_redflags_never_lift_headline():
    """A spotless message with a bad channel is still a red flag; a filthy
    message with a verified channel is still verified (chips shown)."""
    dirty = [{"id": "guaranteed_returns", "label": {"en": "x", "hi": "x"},
              "why": {"en": "y", "hi": "y"}, "matched": "30% monthly"}]
    assert build([INVALID], None, dirty, [], {}, {})["headline"]["state"] == RED_FLAG
    assert build([VERIFIED_P], None, dirty, [], {}, {})["headline"]["state"] == VERIFIED


def test_cross_check_category():
    extracted = {"claimed_category": "mf", "upi_links": []}
    p = dict(VERIFIED_P)  # .brk handle
    flags = cross_checks([p], extracted, "")
    assert any(f["id"] == "category_mismatch" for f in flags)


def test_cross_check_qr_payee_mismatch():
    extracted = {"claimed_category": None,
                 "upi_links": [{"pa": "taurus.cf.brk@validaxis", "pn": "Quick Money Pvt Ltd"}]}
    flags = cross_checks([dict(VERIFIED_P)], extracted, "")
    assert any(f["id"] == "qr_name_mismatch" for f in flags)


def test_policy_handle_parsing():
    info = policy.parse_valid_handle("taurus.cf.brk@validaxis")
    assert info["category"] == "brk" and info["username"] == "taurus.cf.brk"
    assert info["bank_hint"] == "axis"
    assert policy.parse_valid_handle("abc@okhdfcbank") is None
    assert policy.parse_valid_handle("x.mf@validicici")["category"] == "mf"
    # unknown last segment → category None but still @valid-shaped
    assert policy.parse_valid_handle("weird.name@validhdfc")["category"] is None


def test_policy_modes(monkeypatch):
    from datetime import date
    monkeypatch.setattr(policy, "MODE", "auto")
    assert policy.in_transition(date(2025, 6, 1)) is True
    assert policy.in_transition(date(2026, 9, 20)) is False
    monkeypatch.setattr(policy, "MODE", "transition")
    assert policy.in_transition(date(2026, 9, 20)) is True
    monkeypatch.setattr(policy, "MODE", "strict")
    assert policy.in_transition(date(2025, 1, 1)) is False
