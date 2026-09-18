"""Transition-period policy for the @valid handle mandate.

The strength of the "no @valid handle" signal depends on SEBI's transition
timeline, which is a moving regulatory fact — so it lives here as configuration,
never hardcoded into verdict copy.

Verified from circular SEBI/HO/DEPA-II/DEPA-II_SRG/P/CIR/2025/86 (June 11, 2025):
  - validated handles live w.e.f. Oct 1, 2025
  - old UPI IDs to be discontinued by T+180 days ≈ Dec 8, 2025
  - permanent carve-out: ongoing MF SIPs may continue on the old mode
The project brief's "Dec 11, 2026" could NOT be confirmed against any primary
source (see docs/RESEARCH.md §1). Override via env if an amendment surfaces.

Modes:
  auto       - strict after LEGACY_CUTOVER, transition wording before it
  transition - always use transition-period wording (strong red flag, not absolute)
  strict     - always use post-cutoff wording
"""
import os
from datetime import date, datetime

# Env-overridable policy knobs
LEGACY_CUTOVER = date.fromisoformat(os.environ.get("NR_LEGACY_CUTOVER", "2025-12-08"))
MODE = os.environ.get("NR_STRICT_MODE", "auto").lower()  # auto|transition|strict
assert MODE in ("auto", "transition", "strict"), f"bad NR_STRICT_MODE: {MODE}"


def in_transition(today: date | None = None) -> bool:
    """True while legacy handles may still legitimately circulate."""
    if MODE == "transition":
        return True
    if MODE == "strict":
        return False
    return (today or date.today()) < LEGACY_CUTOVER


def policy_summary() -> dict:
    return {
        "mode": MODE,
        "legacy_cutoff": LEGACY_CUTOVER.isoformat(),
        "in_transition": in_transition(),
        "circular": "SEBI/HO/DEPA-II/DEPA-II_SRG/P/CIR/2025/86",
        "sip_carveout": True,  # ongoing MF SIPs stay on legacy mode (Para 6.1.3)
    }


# Authoritative category suffixes — Annexure B of the circular (verified from PDF).
CATEGORY_SUFFIXES = {
    "brk": "Stock Broker",
    "bti": "Banker to an Issue",
    "dp": "Depository Participant",
    "ra": "Research Analyst",
    "ia": "Investment Adviser",
    "invit": "Infrastructure Investment Trust",
    "mf": "Mutual Fund",
    "pms": "Portfolio Manager",
    "sreit": "SM REIT",
    "reit": "Real Estate Investment Trust",
}

# Consumer/personal UPI handle suffixes (PSP handles issued to individuals).
# A payment request for investment money landing on one of these is the single
# strongest red flag: intermediaries collect via @valid, never via personal VPAs.
# NOTE: only unambiguously-consumer suffixes belong here. Bare bank names
# (@hdfcbank, @sbi, @icici…) are deliberately EXCLUDED — during/after the
# transition they may be legacy institutional handles; they classify as
# "unknown" → still a red flag, but with honest "not SEBI-verified" wording
# instead of an overclaimed "personal account" accusation.
PERSONAL_UPI_SUFFIXES = {
    # Google Pay consumer handles
    "okaxis", "okhdfcbank", "okicici", "oksbi",
    # PhonePe consumer handles
    "ybl", "apl", "axl", "ibl", "yapl",
    # Paytm / Freecharge / Amazon Pay / Mobikwik / Cred / Slice / Jupiter
    "paytm", "ptyes", "fbl", "freecharge", "amazonpay", "apay",
    "mobikwik", "mbk", "cred", "credcl", "slice", "jupiter", "jupiteraxis",
    # WhatsApp consumer handles
    "waaxis", "wahdfcbank", "waicici", "wasbi",
    # Kotak 811 (consumer neobank handle)
    "kotak811",
}


def classify_upi_suffix(handle: str) -> str:
    """Classify the PSP part of a UPI handle: valid | personal | unknown."""
    psp = handle.rsplit("@", 1)[-1].lower()
    if psp.startswith("valid"):
        return "valid"
    if psp in PERSONAL_UPI_SUFFIXES:
        return "personal"
    return "unknown"


def parse_valid_handle(handle: str) -> dict | None:
    """Parse `username.cat@validbank`. Returns None if not @valid-shaped.

    Username may contain dots (verified: taurus.cf.brk@validaxis), so the
    category is the LAST dot-segment before @ only if it's a known suffix.
    """
    h = handle.strip().lower()
    if "@" not in h:
        return None
    user, psp = h.rsplit("@", 1)
    if not psp.startswith("valid") or len(psp) <= 5:
        return None
    segs = user.split(".")
    category = segs[-1] if len(segs) > 1 and segs[-1] in CATEGORY_SUFFIXES else None
    return {
        "handle": h,
        "username": user,
        "psp": psp,
        "bank_hint": psp[5:],  # validhdfc -> hdfc
        "category": category,
        "category_label": CATEGORY_SUFFIXES.get(category) if category else None,
    }
