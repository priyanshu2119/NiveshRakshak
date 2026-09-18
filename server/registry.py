"""SEBI intermediary registry: live AJAX search + local mirror + near-miss.

Two independent sources (docs/RESEARCH.md §3):
  live    POST https://www.sebi.gov.in/sebiweb/ajax/other/getrecognisedintm.jsp
          (intmId, search, regNo) → HTML cards; substring matching; freshest
  mirror  daily-updated .xls exports per category (tools/refresh_registry.py)
          → local SQLite; enables edit-distance near-miss detection that the
          live substring search fundamentally cannot do

States returned: exact | near | not_found | unavailable — near-miss is its own
category and is NEVER folded into exact or not_found (brief §5.4).
"""
import html as htmllib
import re
import threading
import time

import requests
from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

from . import db

LIVE_URL = "https://www.sebi.gov.in/sebiweb/ajax/other/getrecognisedintm.jsp"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
LIVE_TIMEOUT = (8, 20)

# fuzzy thresholds (tuned in tests/test_registry.py against real registry shapes)
NAME_NEAR_CUTOFF = 88       # token_set_ratio
REGNO_NEAR_MAXDIST = 2      # Levenshtein

_LEGAL_SUFFIXES = re.compile(
    r"\b(PVT|PRIVATE|LIMITED|LTD|LLP|INC|CORP|CORPORATION|COMPANY|CO|COMPANIES|"
    r"PROPRIETORS|PARTNERS|HUF|HINDU\s+UNDEVIDED\s+FAMILY)\b[.,]?\s*", re.I)
_PUNCT = re.compile(r"[^A-Z0-9\s&]")
_WS = re.compile(r"\s+")

_names_cache: list[tuple[int, str]] | None = None
_regnos_cache: list[tuple[int, str]] | None = None
_cache_lock = threading.Lock()
_cache_loaded_at = 0.0


def normalize_name(name: str) -> str:
    """Uppercase, strip punctuation + legal suffixes, collapse spaces."""
    n = (name or "").upper()
    n = _LEGAL_SUFFIXES.sub(" ", n)
    n = _PUNCT.sub(" ", n)
    return _WS.sub(" ", n).strip()


def normalize_regno(reg: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (reg or "").upper())


def _load_fuzzy_caches(max_age: float = 3600.0) -> None:
    global _names_cache, _regnos_cache, _cache_loaded_at
    with _cache_lock:
        if _names_cache is not None and time.time() - _cache_loaded_at < max_age:
            return
        names, regnos = [], []
        for rid, name_norm, reg_norm in db.registry_all_names():
            if name_norm:
                names.append((rid, name_norm))
            if reg_norm:
                regnos.append((rid, reg_norm))
        _names_cache, _regnos_cache = names, regnos
        _cache_loaded_at = time.time()


# --- live AJAX search --------------------------------------------------------

_CARD_SPLIT = re.compile(r"<div class='fixed-table-body card-table'>")
_FIELD = re.compile(
    r"<div class='title'><span>([^<]*)</span></div>\s*"
    r"<div class='value[^']*'><span>(.*?)</span></div>", re.S)


def _parse_cards(html_text: str) -> list[dict]:
    cards = []
    for chunk in _CARD_SPLIT.split(html_text)[1:]:
        row = {}
        for title, value in _FIELD.findall(chunk):
            key = htmllib.unescape(title.strip().lower())
            val = htmllib.unescape(re.sub(r"<[^>]+>", "", value)).strip()
            row[key] = val
        if row.get("name"):
            cards.append({
                "name": row.get("name", ""),
                "trade_name": row.get("trade name", ""),
                "reg_no": row.get("registration no.", "") or row.get("registration no", ""),
                "type": row.get("type", ""),
                "validity": row.get("validity", ""),
                "exchange": row.get("exchange name", ""),
                "email": row.get("e-mail", ""),
                "source": "live",
            })
    return cards


def live_search(search: str = "", regno: str = "", intm_id: str = "") -> list[dict] | None:
    """Live registry search. Returns cards, or None if the source failed."""
    try:
        r = requests.post(
            LIVE_URL,
            headers={"User-Agent": UA,
                     "Content-type": "application/x-www-form-urlencoded",
                     "Referer": "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognised=yes"},
            data={"intmId": intm_id, "search": search, "regNo": regno},
            timeout=LIVE_TIMEOUT)
        if r.status_code != 200:
            return None
        if "No record" in r.text:
            return []
        return _parse_cards(r.text)
    except requests.RequestException:
        return None


# --- local mirror queries ----------------------------------------------------

def mirror_exact_name(name_norm: str, limit: int = 12) -> list[dict]:
    rows = db.conn().execute(
        "SELECT name,trade_name,reg_no,type,validity,exchange FROM registry "
        "WHERE name_norm=? OR name_norm LIKE ? LIMIT ?",
        (name_norm, f"%{name_norm}%", limit)).fetchall()
    return [dict(r, source="mirror") for r in rows]


def mirror_exact_regno(reg_norm: str, limit: int = 12) -> list[dict]:
    rows = db.conn().execute(
        "SELECT name,trade_name,reg_no,type,validity,exchange FROM registry "
        "WHERE reg_no_norm=? LIMIT ?", (reg_norm, limit)).fetchall()
    return [dict(r, source="mirror") for r in rows]


def mirror_near_names(name_norm: str, limit: int = 5) -> list[dict]:
    _load_fuzzy_caches()
    if not _names_cache:
        return []
    # rapidfuzz dict-choices results are (value, score, key) tuples
    hits = process.extract(name_norm, {rid: n for rid, n in _names_cache},
                           scorer=fuzz.token_set_ratio, limit=limit,
                           score_cutoff=NAME_NEAR_CUTOFF)
    out = []
    for _, score, key in hits:
        row = db.conn().execute(
            "SELECT name,trade_name,reg_no,type,validity,exchange FROM registry WHERE id=?",
            (key,)).fetchone()
        if row is not None:
            out.append(dict(row, source="mirror", fuzzy_score=round(score, 1)))
    return out[:limit]


def mirror_near_regnos(reg_norm: str, limit: int = 5) -> list[dict]:
    _load_fuzzy_caches()
    if not _regnos_cache or len(reg_norm) < 6:
        return []
    ids = []
    for rid, cand in _regnos_cache:
        if cand == reg_norm:
            continue
        if len(cand) == len(reg_norm) and \
                Levenshtein.distance(reg_norm, cand, score_cutoff=REGNO_NEAR_MAXDIST) <= REGNO_NEAR_MAXDIST:
            ids.append(rid)
            if len(ids) >= limit:
                break
    rows = db.registry_rows_by_ids(ids)
    return [dict(r, source="mirror") for r in rows]


def mirror_as_of() -> str | None:
    ts = db.meta_get("registry_refreshed_at")
    if not ts:
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))


def mirror_count() -> int:
    return db.registry_count()


# --- orchestrator -------------------------------------------------------------

def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        key = (r.get("name", "").upper(), normalize_regno(r.get("reg_no", "")),
               r.get("type", ""))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def mirror_fresh(max_age_h: float = 24.0) -> bool:
    ts = db.meta_get("registry_refreshed_at")
    return bool(ts) and (time.time() - int(ts)) < max_age_h * 3600 and mirror_count() > 0


def lookup(claimed_name: str = "", claimed_regno: str = "") -> dict:
    """Registry lookup for a claimed identity. Context, never proof (brief §5.3).

    Precedence: exact regno > exact name > near-miss > not found.
    MIRROR-FIRST: the local mirror is built from SEBI's own daily-updated
    exports — the same data the live endpoint serves — and answers in ~ms
    instead of the multi-second live call. The live AJAX endpoint is the
    fallback when the mirror is empty (fresh install, failed refresh), keeping
    the product working even before the first refresh completes.
    """
    use_mirror = mirror_count() > 0
    result = {"state": "not_found", "matches": [], "near": [],
              "sources": [], "as_of": mirror_as_of(),
              "mirror_rows": mirror_count(),
              "mirror_fresh": mirror_fresh()}
    name_norm = normalize_name(claimed_name)
    reg_norm = normalize_regno(claimed_regno)
    if not name_norm and not reg_norm:
        result["state"] = "unavailable"
        result["reason"] = "nothing_to_look_up"
        return result

    # 1) exact registration number (strongest identity anchor)
    if reg_norm:
        exact = []
        if use_mirror:
            exact = _dedupe(mirror_exact_regno(reg_norm))
            if exact:
                result["sources"].append("mirror")
        if not exact and not use_mirror:
            live = live_search(regno=reg_norm)
            if live is not None:
                result["sources"].append("live")
                exact = _dedupe(live)
        if exact:
            result.update(state="exact", matches=exact[:8])
            return result

    # 2) exact/substring name
    if name_norm:
        exact = []
        if use_mirror:
            exact = _dedupe(mirror_exact_name(name_norm))
            if exact:
                result["sources"].append("mirror")
        if not exact and not use_mirror:
            live = live_search(search=name_norm)
            if live is not None:
                result["sources"].append("live")
                exact = [c for c in _dedupe(live)
                         if normalize_name(c["name"]) == name_norm
                         or name_norm in normalize_name(c["name"])]
        if exact:
            result.update(state="exact", matches=exact[:8])
            return result

    # 3) near-miss (own category — never folded into not_found)
    near = []
    if name_norm:
        near += mirror_near_names(name_norm)
    if reg_norm:
        near += mirror_near_regnos(reg_norm)
    if near:
        result["sources"].append("mirror-fuzzy")
        result.update(state="near", near=_dedupe(near)[:6])
        return result

    # 4) not found — mirror answered (or live did); if neither could, say so
    if use_mirror:
        result["sources"].append("mirror")
    else:
        result["state"] = "unavailable"
        result["reason"] = "registry_unreachable"
    return result


# --- self-check ----------------------------------------------------------------
if __name__ == "__main__":
    import os
    import tempfile
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.sqlite")
    db.init()
    assert normalize_name("Zerodha Broking Limited") == "ZERODHA BROKING"
    assert normalize_name("  A.B. Capital  Pvt. Ltd. ") == "A B CAPITAL"
    assert normalize_regno("inz-000031633") == "INZ000031633"
    # card parser against a captured live response shape
    sample = ("<div class='fixed-table-body card-table'><div class='card-table-left right'>"
              "<div class='number'><span>1</span></div>"
              "<div class='card-view'><div class='title'><span>Name</span></div>"
              "<div class='value varun-text'><span>ZERODHA BROKING LIMITED</span></div></div>"
              "<div class='card-view'><div class='title'><span>Registration No.</span></div>"
              "<div class='value'><span>INZ000031633</span></div></div>"
              "<div class='card-view'><div class='title'><span>Type</span></div>"
              "<div class='value'><span>Registered Stock Brokers in equity segment</span></div></div>"
              "</div></div>")
    cards = _parse_cards(sample)
    assert cards and cards[0]["reg_no"] == "INZ000031633", cards
    # fuzzy near-miss on fixture rows
    db.registry_replace_rows(30, [
        {"name": "ZERODHA BROKING LIMITED", "name_norm": normalize_name("ZERODHA BROKING LIMITED"),
         "reg_no": "INZ000031633", "reg_no_norm": "INZ000031633", "type": "broker"},
        {"name": "TAURUS CORPORATE ADVISORY SERVICES LIMITED",
         "name_norm": normalize_name("TAURUS CORPORATE ADVISORY SERVICES LIMITED"),
         "reg_no": "INZ000012345", "reg_no_norm": "INZ000012345", "type": "broker"},
    ])
    near = mirror_near_names(normalize_name("Zerodha Broking Limted"))
    assert near and near[0]["name"].startswith("ZERODHA"), near
    near_r = mirror_near_regnos("INZ000031634")   # one digit off
    assert near_r and near_r[0]["reg_no"] == "INZ000031633", near_r
    print("registry.py self-check OK (parser + normalization + fuzzy)")
