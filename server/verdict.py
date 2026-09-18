"""Verdict assembly — strict precedence, calibrated certainty.

The load-bearing rules (brief §5.2.3, §5.5, §5.7; ADVERSARIAL-REVIEW §8):
  1. The headline is driven ONLY by the payment-channel (primary) results.
  2. A failed primary check produces a red flag REGARDLESS of any registry
     match or clean language — secondary signals can never override it.
  3. Supporting evidence can never manufacture an all-clear.
  4. An UNAVAILABLE primary poisons the headline: the verdict can never be
     more positive than its least-certain load-bearing input.
  5. Near-miss registry results stay their own visible category.
  6. Certainty language follows policy.in_transition() — never overclaimed.

The backend emits states + structured facts; all display copy lives in the
frontend i18n dictionary (single place for EN/HI wording).
"""
from rapidfuzz import fuzz

from . import policy

# headline states
RED_FLAG = "red_flag"
VERIFIED = "verified"
CAUTION = "caution"
UNVERIFIABLE = "unverifiable"
CAPTCHA_PENDING = "captcha_pending"


def classify_upi_local(handle: str) -> dict | None:
    """Non-@valid handles never go to SEBI Check: only NPCI issues @valid, so
    anything else is by definition not a validated intermediary handle.
    Returns a primary result dict, or None if the handle is @valid-shaped and
    must be checked live."""
    info = policy.parse_valid_handle(handle)
    if info is not None:
        return None  # needs live SEBI Check
    psp = handle.rsplit("@", 1)[-1].lower()
    kind = policy.classify_upi_suffix(handle)
    return {
        "kind": "upi",
        "value": handle,
        "state": "invalid",
        "reason_code": "personal_handle" if kind == "personal" else "not_valid_handle",
        "psp": psp,
        "entity": None, "txn": None, "source": "policy",
        "category": None,
    }


def cross_checks(primaries: list[dict], extracted: dict, claimed_name: str) -> list[dict]:
    """Supporting-evidence comparisons.

    category_mismatch is the one flag the brief (§5.2.3) elevates to a red
    flag: sender claims intermediary type X, but the handle's suffix / SEBI's
    own entity role says type Y. entity_name_mismatch (brand vs legal name —
    e.g. "Groww" vs "Nextbill Technologies") is common and legitimate, so it
    stays a prominent supporting flag and never downgrades the headline.
    """
    flags = []
    claimed_cat = extracted.get("claimed_category")
    for p in primaries:
        if p["state"] != "verified" or not p.get("entity"):
            continue
        ent_name = (p["entity"].get("name") or "").strip()
        # 1) claimed name vs SEBI-returned entity name (supporting only)
        claim = (claimed_name or "").strip()
        if claim and ent_name:
            ratio = fuzz.token_set_ratio(claim.upper(), ent_name.upper())
            if ratio < 60:
                flags.append({"id": "entity_name_mismatch", "handle": p["value"],
                              "entity_name": ent_name, "claimed_name": claim})
        # 2) claimed category vs handle suffix (brief §5.2.3 → red flag)
        info = policy.parse_valid_handle(p["value"]) if p["kind"] == "upi" else None
        if claimed_cat and info and info["category"] and info["category"] != claimed_cat:
            flags.append({"id": "category_mismatch", "handle": p["value"],
                          "claimed_category": claimed_cat,
                          "claimed_label": policy.CATEGORY_SUFFIXES.get(claimed_cat),
                          "suffix": info["category"],
                          "suffix_label": info["category_label"]})
        # 3) SEBI-returned role vs handle suffix (internal inconsistency)
        role = (p["entity"].get("role") or "").lower()
        if info and info["category"] and role:
            label = (info["category_label"] or "").lower()
            if label and label not in role and info["category"] not in role:
                flags.append({"id": "role_suffix_mismatch", "handle": p["value"],
                              "suffix": info["category"], "suffix_label": info["category_label"],
                              "entity_role": p["entity"].get("role")})
    # 4) QR payee name vs verified entity name
    for link in extracted.get("upi_links", []):
        pn = (link.get("pn") or "").strip()
        if not pn:
            continue
        for p in primaries:
            if p["value"] == link["pa"] and p["state"] == "verified" and p.get("entity"):
                ent = (p["entity"].get("name") or "")
                if ent and fuzz.token_set_ratio(pn.upper(), ent.upper()) < 60:
                    flags.append({"id": "qr_name_mismatch", "handle": p["value"],
                                  "qr_payee": pn, "entity_name": ent})
    # dedupe
    seen, out = set(), []
    for f in flags:
        k = (f["id"], f.get("handle"))
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def build(primaries: list[dict], registry_result: dict | None,
          redflags_hits: list[dict], flags: list[dict],
          extracted: dict, meta: dict) -> dict:
    """Assemble the final verdict structure consumed by the frontend."""
    states = [p["state"] for p in primaries]

    # --- headline precedence (rules 1–4 above) ---
    if any(s == "invalid" for s in states):
        headline = RED_FLAG
    elif any(f["id"] == "category_mismatch" for f in flags):
        # brief §5.2.3: claimed category ≠ registered category is a red flag
        # even when the handle itself is genuine
        headline = RED_FLAG
    elif any(s == "captcha_required" for s in states):
        headline = CAPTCHA_PENDING
    elif any(s == "unavailable" for s in states):
        headline = UNVERIFIABLE
    elif primaries and all(s == "verified" for s in states):
        headline = VERIFIED
    else:
        # no payment destination found at all → nothing to verify.
        # Never an all-clear: a pitch without payment details is still a pitch.
        headline = CAUTION

    # reason codes present (frontend picks copy variants)
    reasons = sorted({p.get("reason_code") for p in primaries if p.get("reason_code")})
    if headline == RED_FLAG and any(f["id"] == "category_mismatch" for f in flags):
        reasons = sorted(set(reasons) | {"category_mismatch"})

    # policy note for non-@valid red flags: transition wording vs post-cutoff
    note = None
    if headline == RED_FLAG and any(r in ("not_valid_handle", "personal_handle") for r in reasons):
        note = {
            "in_transition": policy.in_transition(),
            "legacy_cutoff": policy.LEGACY_CUTOVER.isoformat(),
            "sip_carveout": registry_result is not None and registry_result.get("state") == "exact",
        }

    return {
        "headline": {
            "state": headline,
            "reasons": reasons,
            "policy_note": note,
        },
        "primaries": primaries,
        "registry": registry_result,
        "supporting": {
            "redflags": redflags_hits,
            "flags": flags,
            "amounts": extracted.get("amounts", []),
            "phones": extracted.get("phones", [])[:3],
        },
        "meta": meta,
    }


# --- self-check: precedence rules are money paths, they get tests -------------
if __name__ == "__main__":
    inv = {"kind": "upi", "value": "x@ybl", "state": "invalid", "reason_code": "personal_handle"}
    ver = {"kind": "upi", "value": "t.cf.brk@validaxis", "state": "verified",
           "entity": {"name": "TAURUS", "role": "Broker"}, "txn": "TXN-1"}
    unav = {"kind": "upi", "value": "a@b", "state": "unavailable", "reason": "timeout"}
    cap = {"kind": "upi", "value": "a@b", "state": "captcha_required"}
    reg_exact = {"state": "exact", "matches": [{"name": "ZERODHA BROKING LIMITED"}]}
    # rule 2: invalid primary + exact registry match → still RED FLAG
    v = build([inv], reg_exact, [], [], {}, {})
    assert v["headline"]["state"] == RED_FLAG, v["headline"]
    # rule 4: unavailable poisons an otherwise verified set
    v = build([ver, unav], None, [], [], {}, {})
    assert v["headline"]["state"] == UNVERIFIABLE, v["headline"]
    # captcha pending surfaces
    v = build([cap], None, [], [], {}, {})
    assert v["headline"]["state"] == CAPTCHA_PENDING
    # verified alone
    v = build([ver], None, [], [], {}, {})
    assert v["headline"]["state"] == VERIFIED
    # verified + brand-vs-legal name mismatch → STILL VERIFIED (supporting flag
    # only; Groww→Nextbill-style differences are legitimate)
    v = build([ver], None, [], [{"id": "entity_name_mismatch", "handle": ver["value"]}], {}, {})
    assert v["headline"]["state"] == VERIFIED
    # verified + category mismatch (claims MF, handle is .brk) → RED FLAG (brief §5.2.3)
    v = build([ver], None, [], [{"id": "category_mismatch", "handle": ver["value"],
                                 "claimed_category": "mf", "suffix": "brk"}], {}, {})
    assert v["headline"]["state"] == RED_FLAG, v["headline"]
    assert "category_mismatch" in v["headline"]["reasons"]
    # no primaries → caution (never all-clear)
    v = build([], reg_exact, [], [], {}, {})
    assert v["headline"]["state"] == CAUTION
    # local classification
    assert classify_upi_local("scam@ybl")["reason_code"] == "personal_handle"
    assert classify_upi_local("scam@kotak811")["reason_code"] == "personal_handle"
    assert classify_upi_local("oldbroker@hdfcbank")["reason_code"] == "not_valid_handle"
    assert classify_upi_local("taurus.cf.brk@validaxis") is None  # → live check
    print("verdict.py self-check OK (precedence rules hold)")
