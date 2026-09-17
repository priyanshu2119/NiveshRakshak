"""Entity extraction from messy real-world scam input.

Deterministic, rule-based (see docs/DECISIONS.md §5 for why no LLM).
Handles: forwarded chat text (English/Hindi/Hinglish), OCR'd screenshot text,
decoded QR payloads. Extracts: UPI handles, upi:// deep links, bank account
numbers, IFSC codes, phone numbers, SEBI registration numbers, org-like claimed
names, and money amounts (context only).

Anti-evasion: strips zero-width joiners (scammers insert them to dodge filters),
normalizes "(at)"/"[at]" obfuscation with guards against false positives, and
distinguishes UPI handles from email addresses (email domains contain dots;
PSP handles never do).
"""
import re
from urllib.parse import parse_qs, urlparse

# Zero-width / invisible chars used to evade keyword filters
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

# UPI VPA: username (letters/digits/._-) @ psp (no dots — that's what separates
# it from email). Username may contain dots: taurus.cf.brk@validaxis (verified).
# The \b(?!\.[a-zA-Z]) guard stops "social@zerodha.com" backtracking into
# "social@zerodha"; a sentence-final period ("scam@ybl.") still matches.
_UPI = re.compile(r"\b([a-zA-Z0-9][a-zA-Z0-9._-]{1,253})@([a-zA-Z0-9][a-zA-Z0-9-]{1,63})\b(?!\.[a-zA-Z])")

_UPI_LINK = re.compile(r"upi://pay\?[^\s\"'<>\\]+", re.I)

_IFSC = re.compile(r"\b([A-Za-z]{4})0([A-Za-z0-9]{6})\b")

_PHONE = re.compile(r"(?<!\d)(\+?91[\s.-]?)?([6-9]\d{9})(?!\d)")

# SEBI registration numbers: INZ000031633, INA…, INH…, INP…, INF…
# (IN + letter + 8–10 digits; verified real: INZ000031633, INE261382431)
_REGNO = re.compile(r"\b(IN[A-Z]\d{8,10})\b")
# looser: "Reg. No.", "Registration No", "SEBI Reg" followed by a token
_REGNO_LOOSE = re.compile(
    r"(?:reg(?:istration|d|no)?|sebi\s*(?:reg|registration))[\s.:#\-no]*([A-Z]{2,4}[A-Z0-9/\-]{4,18})",
    re.I)

_DIGITS = re.compile(r"(?<!\d)(?<!\.\d)(\d{9,18})(?!\d)(?!\.\d)")

_ACC_KEYWORDS = re.compile(
    r"(a/?c|acc(?:oun)?t|account\s*(?:no|number|#)?|khata|bank|ifsc|neft|rtgs|imps|"
    r"खाता|बैंक|ख़ाता)", re.I)
_PHONE_KEYWORDS = re.compile(
    r"(call|contact|phone|mobile|whatsapp|telegram|no\.?\s*:?\s*$|पर\s*कॉल|फोन|संपर्क)", re.I)

_AMOUNT = re.compile(
    r"((?:₹|rs\.?|inr)\s*)([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr|k|l|c|m)?(?:\s*rupees)?",
    re.I)

# org-like name candidates: 2–6 capitalized words, filtered below for finance/org markers
_ORG_WORDS = (r"capital|securities|broking|brokers?|invest(?:ments?|ing)?|financial|"
              r"finance|fund|wealth|advis(?:ors?|ers?|ory)|holdings|enterprises?|"
              r"infotech|technologies|pvt|private|ltd|limited|amc|mutual|stock|"
              r"commodities|derivatives|asset|research|equities|trading|finserv|"
              r"cap|mart|money|share|bazaar|dealers")
_CAP_SEQ = re.compile(r"\b([A-Z][A-Za-z&'.\-]*(?:\s+[A-Z][A-Za-z&'.\-]*){1,5})\b")
_ORG_MARKER = re.compile(rf"\b(?:{_ORG_WORDS})\b", re.I)

# "(at)" obfuscation — guarded: only rewrite when it plausibly forms a handle.
# Bracketed form is unambiguous. Bare " at " only rewrites when the left token
# contains a dot (handle usernames like zerodha.brk do; English words don't)
# or the right token starts with "valid" (nobody says "at validhdfc" casually).
_AT_OBF = re.compile(r"([a-zA-Z0-9][a-zA-Z0-9._-]{1,253})\s*[\(\[]\s*at\s*[\)\]]\s*([a-zA-Z0-9][a-zA-Z0-9-]{1,63})", re.I)
_AT_WORD = re.compile(r"([a-zA-Z0-9][a-zA-Z0-9._-]*\.[a-zA-Z0-9._-]*)\s+at\s+([a-zA-Z0-9][a-zA-Z0-9-]{1,63})", re.I)
_AT_VALID = re.compile(r"([a-zA-Z0-9][a-zA-Z0-9._-]{1,253})\s+at\s+(valid[a-zA-Z0-9-]{1,63})", re.I)


def normalize(text: str) -> str:
    text = _INVISIBLE.sub("", text or "")
    text = _AT_OBF.sub(r"\1@\2", text)
    text = _AT_WORD.sub(r"\1@\2", text)
    text = _AT_VALID.sub(r"\1@\2", text)
    return text


def _is_email(user: str, domain: str) -> bool:
    # email domains contain dots (gmail.com); UPI PSP handles never do.
    return "." in domain


def extract_upi(text: str) -> list[str]:
    out = []
    for m in _UPI.finditer(text):
        user, dom = m.group(1), m.group(2)
        if _is_email(user, dom):
            continue
        h = f"{user}@{dom}".lower()
        if h not in out:
            out.append(h)
    return out


def extract_upi_links(text: str) -> list[dict]:
    """upi://pay?pa=handle&pn=Payee%20Name&am=50000 — QR payloads land here."""
    out = []
    for m in _UPI_LINK.finditer(text):
        raw = m.group(0)
        try:
            q = parse_qs(urlparse(raw).query)
        except ValueError:
            continue
        pa = (q.get("pa") or [""])[0].lower()
        if not pa:
            continue
        entry = {"raw": raw, "pa": pa,
                 "pn": (q.get("pn") or [""])[0],
                 "am": (q.get("am") or [""])[0],
                 "mam": (q.get("mam") or [""])[0]}
        if entry not in out:
            out.append(entry)
    return out


def extract_ifsc(text: str) -> list[str]:
    out = []
    for m in _IFSC.finditer(text):
        code = (m.group(1) + "0" + m.group(2)).upper()
        if code not in out:
            out.append(code)
    return out


def extract_phones(text: str) -> list[str]:
    out = []
    for m in _PHONE.finditer(text):
        p = m.group(2)
        if p not in out:
            out.append(p)
    return out


def extract_accounts(text: str) -> list[str]:
    """9–18 digit runs classified by the CLOSEST nearby keyword: an account
    keyword wins → account; a phone keyword wins (or no keyword and it matches
    the phone pattern) → skip, it's a phone number."""
    out = []
    phones = set(extract_phones(text))
    for m in _DIGITS.finditer(text):
        digits = m.group(1)
        before = text[max(0, m.start() - 50):m.start()]
        after = text[m.end():m.end() + 30]
        acc_b = _ACC_KEYWORDS.search(before)
        acc_a = _ACC_KEYWORDS.search(after)
        ph_b = _PHONE_KEYWORDS.search(before)
        acc_dists = [len(before) - acc_b.end()] if acc_b else []
        if acc_a:
            acc_dists.append(acc_a.start())
        acc_dist = min(acc_dists) if acc_dists else None
        ph_dist = (len(before) - ph_b.end()) if ph_b else None
        if digits in phones:
            # phone-pattern digits: only an account if an account keyword is
            # strictly closer than any phone keyword
            if acc_dist is not None and (ph_dist is None or acc_dist < ph_dist):
                if digits not in out:
                    out.append(digits)
            continue
        if acc_dist is not None or len(digits) >= 11:
            if digits not in out:
                out.append(digits)
    return out


def extract_regnos(text: str) -> list[str]:
    out = []
    for m in _REGNO.finditer(text):
        if m.group(1) not in out:
            out.append(m.group(1))
    for m in _REGNO_LOOSE.finditer(text):
        tok = m.group(1).upper().rstrip(".,;:")
        # registration numbers always carry digits; pure-word captures are noise
        # (e.g. "SEBI registered" must not yield "ISTERED")
        if tok not in out and not _REGNO.fullmatch(tok) and any(ch.isdigit() for ch in tok):
            out.append(tok)
    return out


def extract_amounts(text: str) -> list[str]:
    out = []
    for m in _AMOUNT.finditer(text):
        amt = f"{m.group(1)}{m.group(2)}" + (f" {m.group(3)}" if m.group(3) else "")
        amt = amt.replace("..", ".").strip()
        if amt not in out:
            out.append(amt)
    return out[:6]


def extract_org_names(text: str) -> list[str]:
    out = []
    for m in _CAP_SEQ.finditer(text):
        name = m.group(1).strip(" .,-")
        if not (4 < len(name) < 90):
            continue
        if not _ORG_MARKER.search(name):
            continue
        if name.lower() not in [o.lower() for o in out]:
            out.append(name)
    return out[:5]


# Claimed intermediary category from message wording → Annexure B suffix.
# Only unambiguous claims count; a wrong guess here would wrongly red-flag a
# legitimate handle, so anything unclear returns None (no category check).
_CATEGORY_CLAIMS = [
    ("mf", re.compile(r"(mutual[\s-]+fund|एम्?एफ[\s-]+फंड|म्यूचुअल[\s-]+फंड|\bsip\b|amc|asset[\s-]+management)", re.I)),
    ("brk", re.compile(r"(stock[\s-]+brok\w*|broking|broker(?:age)?[\s-]+(?:firm|house|account)?|"
                       r"शेयर[\s-]+ब्रोकर|ब्रोकर(?:ेज)?[\s-]+(?:फर्म|हाउस)|trading[\s-]+(?:account|platform)|"
                       r"demat[\s-]+account[\s-]+provider|discount[\s-]+broker)", re.I)),
    ("ia", re.compile(r"(investment[\s-]+advis(?:or|er|ory)|financial[\s-]+advis(?:or|er|ory)|"
                      r"निवेश[\s-]+सलाहकार|पोर्टफोलियो[\s-]+एडवाइजर|registered[\s-]+advisor)", re.I)),
    ("pms", re.compile(r"(portfolio[\s-]+management[\s-]+(?:scheme|service)|\bpms\b)", re.I)),
    ("ra", re.compile(r"(research[\s-]+analyst|रिसर्च[\s-]+एनालिस्ट)", re.I)),
]


def extract_claimed_category(text: str) -> str | None:
    """Return the Annexure-B suffix the message explicitly claims, else None.
    Conflicting claims (e.g. both mf and brk wording) → None (ambiguous)."""
    found = [cat for cat, rx in _CATEGORY_CLAIMS if rx.search(text)]
    return found[0] if len(found) == 1 else None


def extract_all(text: str) -> dict:
    """One call → everything, de-duplicated and cross-consistent."""
    text = normalize(text)
    links = extract_upi_links(text)
    upis = extract_upi(text)
    for l in links:  # QR-decoded handles count as UPI mentions too
        if l["pa"] not in upis:
            upis.append(l["pa"])
    return {
        "text_normalized": text,
        "upis": upis,
        "upi_links": links,
        "ifscs": extract_ifsc(text),
        "accounts": extract_accounts(text),
        "phones": extract_phones(text),
        "regnos": extract_regnos(text),
        "amounts": extract_amounts(text),
        "org_names": extract_org_names(text),
        "claimed_category": extract_claimed_category(text),
    }


# --- self-check (ponytail: non-trivial parser leaves one runnable check) -----
if __name__ == "__main__":
    demo = ("🚀 Join our VIP tips group! SEBI registered advisor Rakesh Capital "
            "Securities (Reg No INZ000031633). Guaranteed 30% monthly return! "
            "Pay ₹50,000 to groww.brk(at)validhdfc or scan QR. "
            "Bank: HDFC0001234, A/C 50100234567890. Call 9876543210. "
            "Withdrawal blocked? Pay unlock fee आज ही! upi://pay?pa=fraud99@ybl&pn=Quick%20Money")
    r = extract_all(demo)
    assert "groww.brk@validhdfc" in r["upis"], r["upis"]          # (at) obfuscation
    assert "fraud99@ybl" in r["upis"], r["upis"]                  # deep link
    assert "HDFC0001234" in r["ifscs"], r["ifscs"]
    assert "50100234567890" in r["accounts"], r["accounts"]
    assert "9876543210" not in r["accounts"], r["accounts"]       # phone, not account
    assert "9876543210" in r["phones"], r["phones"]
    assert "INZ000031633" in r["regnos"], r["regnos"]
    assert "ISTERED" not in r["regnos"], r["regnos"]              # loose-pattern noise guard
    assert any("Rakesh Capital Securities" in o for o in r["org_names"]), r["org_names"]
    assert r["upi_links"][0]["pn"] == "Quick Money"
    assert r["claimed_category"] == "ia", r["claimed_category"]   # "SEBI registered advisor"
    # conflicting category claims → None (ambiguous, no category check)
    assert extract_all("mutual fund SIP and stock broker account")["claimed_category"] is None
    # email must NOT be extracted as UPI
    assert "social@zerodha.com" not in extract_all("mail social@zerodha.com now")["upis"]
    # zero-width evasion
    assert extract_all("pay\u200b to scam@ybl")["upis"] == ["scam@ybl"]
    print("extract.py self-check OK:", {k: v for k, v in r.items() if k != "text_normalized"})
