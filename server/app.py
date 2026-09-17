"""NiveshRakshak — FastAPI application.

Orchestrates: intake (text + image) → extraction → PRIMARY SEBI Check →
SECONDARY registry → supporting evidence → verdict assembly → audit log.

Privacy: raw messages and uploaded images are processed in memory and never
persisted; the audit log keeps only extracted identifiers (accounts/phones
masked) — see db.py docstring and README.
"""
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, extract, ocr, policy, redflags, registry, sebicheck, verdict

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "..", "web")

MAX_UPI_CHECKS = 3      # per request: latency + politeness to SEBI
MAX_ACC_CHECKS = 2
MAX_MESSAGE_LEN = 20_000

# --- simple per-IP token bucket (abuse resistance, brief §7) ------------------
_rl_lock = threading.Lock()
_rl: dict[str, list[float]] = {}
RL_LIMIT = int(os.environ.get("NR_RATE_LIMIT", "30"))   # checks…
RL_WINDOW = int(os.environ.get("NR_RATE_WINDOW", "600"))  # …per 10 min


def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl.get(ip, []) if now - t < RL_WINDOW]
        if len(hits) >= RL_LIMIT:
            _rl[ip] = hits
            return False
        hits.append(now)
        _rl[ip] = hits
        return True


# --- startup -------------------------------------------------------------------

def _maybe_refresh_registry() -> None:
    """Background refresh when the mirror is empty or stale (>24h)."""
    try:
        from tools.refresh_registry import refresh
        res = refresh()
        if not res.get("skipped"):
            print(f"[registry] refreshed: {res.get('imported', 0)} rows", flush=True)
    except Exception as e:  # never block startup on the mirror
        print(f"[registry] refresh failed: {e}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    purged = db.purge_old()
    if purged:
        print(f"[privacy] purged {purged} audit rows past retention", flush=True)
    if registry.mirror_count() == 0 or _mirror_stale():
        threading.Thread(target=_maybe_refresh_registry, daemon=True).start()
    # pre-warm the SEBI Check session so the first user check skips bootstrap
    threading.Thread(target=sebicheck.client.health, daemon=True).start()
    yield


def _mirror_stale() -> bool:
    ts = db.meta_get("registry_refreshed_at")
    return not ts or (time.time() - int(ts)) > 24 * 3600


app = FastAPI(title="NiveshRakshak", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        # style-src allows unsafe-inline ONLY because html2canvas (verdict-card
        # PNG export) injects inline styles into its clone; script-src stays
        # strict 'self' — that's the XSS-critical directive.
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; script-src 'self'; connect-src 'self'; "
        "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
    return resp


# --- core check -----------------------------------------------------------------

def _pair_accounts_ifsc(accounts: list[str], ifscs: list[str]) -> list[tuple[str, str]]:
    if len(ifscs) == 1 and accounts:
        return [(a, ifscs[0]) for a in accounts[:MAX_ACC_CHECKS]]
    if len(accounts) == 1 and ifscs:
        return [(accounts[0], i) for i in ifscs[:MAX_ACC_CHECKS]]
    return list(zip(accounts[:MAX_ACC_CHECKS], ifscs[:MAX_ACC_CHECKS]))


def run_check(message: str, image_bytes: bytes | None, claimed_name: str,
              claimed_regno: str, captcha_text: str) -> dict:
    t0 = time.time()
    texts = [(message or "")[:MAX_MESSAGE_LEN]]
    ocr_state = "none"
    if image_bytes:
        r = ocr.process_image(image_bytes)
        ocr_state = "ok" if r["ok"] else f"error:{r['error']}"
        if r["ok"]:
            texts.append(r["text"])
            texts.extend(r["qr"])
    merged = "\n".join(t for t in texts if t)
    extracted = extract.extract_all(merged)

    # --- PRIMARY: payment-channel checks -------------------------------------
    primaries: list[dict] = []
    captcha_blob = None

    def _take_captcha(res: dict) -> dict:
        nonlocal captcha_blob
        blob = res.pop("captcha", None)   # always pop: never serialize base64 per-primary
        if blob and captcha_blob is None:
            captcha_blob = blob
        return res

    for h in extracted["upis"][:MAX_UPI_CHECKS]:
        local = verdict.classify_upi_local(h)
        if local is not None:
            primaries.append(local)
            continue
        res = sebicheck.client.check_upi(h, captcha_text=captcha_text)
        info = policy.parse_valid_handle(h) or {}
        res = dict(res, category=info.get("category"),
                   category_label=info.get("category_label"),
                   bank_hint=info.get("bank_hint"))
        primaries.append(_take_captcha(res))
    pairs = _pair_accounts_ifsc(extracted["accounts"], extracted["ifscs"])
    for acc, ifsc in pairs:
        res = sebicheck.client.check_account(acc, ifsc, captcha_text=captcha_text)
        res = dict(res, account_masked=db.mask_account(acc), ifsc=ifsc)
        primaries.append(_take_captcha(res))
    if extracted["accounts"] and not pairs:
        # account number(s) present but no IFSC → SEBI account check impossible.
        # Honest unverifiable state with guidance, never a silent skip.
        for acc in extracted["accounts"][:MAX_ACC_CHECKS]:
            primaries.append({
                "kind": "account", "value": db.mask_account(acc),
                "account_masked": db.mask_account(acc), "ifsc": None,
                "state": "unavailable", "reason": "ifsc_missing",
                "reason_code": "ifsc_missing", "entity": None, "txn": None,
                "source": "policy", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })

    # --- SECONDARY: registry (context, never proof) ---------------------------
    regno = (claimed_regno or "").strip() or (extracted["regnos"][0] if extracted["regnos"] else "")
    name = (claimed_name or "").strip() or (extracted["org_names"][0] if extracted["org_names"] else "")
    reg_origin = "user" if (claimed_name or claimed_regno) else ("message" if (name or regno) else None)
    if not (name or regno):
        # nothing claimed — cross-check the entity SEBI Check itself returned
        # against the registry: two independent sources agreeing is worth showing
        for p in primaries:
            if p["state"] == "verified" and p.get("entity"):
                name = (p["entity"].get("name") or "").strip()
                regno = (p["entity"].get("regNo") or "").strip()
                reg_origin = "sebi_entity"
                break
    reg_result = registry.lookup(name, regno) if (name or regno) else None
    if reg_result is not None:
        reg_result["query"] = {"name": name, "regno": regno, "origin": reg_origin}

    # --- SUPPORTING: language + cross-checks ----------------------------------
    hits = redflags.scan(merged)
    flags = verdict.cross_checks(primaries, extracted, (claimed_name or "").strip())

    duration_ms = int((time.time() - t0) * 1000)
    sources = {
        "sebi_check": sebicheck.client.health()["state"],
        "registry_mirror_rows": registry.mirror_count(),
        "registry_as_of": registry.mirror_as_of(),
        "ocr": ocr_state,
    }
    v = verdict.build(primaries, reg_result, hits, flags, extracted,
                      {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "duration_ms": duration_ms, "sources": sources,
                       "policy": policy.policy_summary()})

    # --- audit (privacy-masked) ------------------------------------------------
    check_id = db.log_check({
        "upi": ",".join(extracted["upis"][:MAX_UPI_CHECKS]) or None,
        "account_ref": db.mask_account(extracted["accounts"][0]) if extracted["accounts"] else None,
        "claimed_name": name or None,
        "claimed_regno": regno or None,
        "headline": v["headline"]["state"],
        "primary": [{k: p.get(k) for k in ("kind", "value", "state", "reason_code", "txn")}
                    for p in primaries],
        "registry": {k: reg_result.get(k) for k in ("state", "sources")} if reg_result else None,
        "redflag_ids": [h["id"] for h in hits],
        "sebi_txn": next((p.get("txn") for p in primaries if p.get("txn")), None),
        "sources": sources,
        "duration_ms": duration_ms,
    })
    v["meta"]["check_id"] = check_id
    if captcha_blob:
        v["captcha"] = captcha_blob
    # phones masked in response payload (they may belong to third parties)
    v["supporting"]["phones"] = [db.mask_phone(p) for p in v["supporting"]["phones"]]
    return v


@app.post("/api/check")
async def api_check(request: Request,
                    message: str = Form(""),
                    claimed_name: str = Form(""),
                    claimed_regno: str = Form(""),
                    captcha_text: str = Form(""),
                    image: UploadFile | None = File(None)):
    ip = request.client.host if request.client else "?"
    if not _rate_ok(ip):
        return JSONResponse({"error": "rate_limited",
                             "retry_after_sec": RL_WINDOW}, status_code=429)
    img_bytes = None
    if image is not None:
        img_bytes = await image.read()
        if len(img_bytes) > ocr.MAX_BYTES:
            return JSONResponse({"error": "image_too_large"}, status_code=413)
    if not (message or "").strip() and not img_bytes:
        return JSONResponse({"error": "empty_input"}, status_code=422)
    try:
        return run_check(message, img_bytes, claimed_name, claimed_regno, captcha_text)
    except Exception as e:
        # honest failure — never a silent pass
        return JSONResponse({"error": "internal", "detail": str(e)[:200],
                             "headline": {"state": verdict.UNVERIFIABLE,
                                          "reasons": ["internal_error"], "policy_note": None},
                             "primaries": [], "registry": None,
                             "supporting": {"redflags": [], "flags": [], "amounts": [], "phones": []},
                             "meta": {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}},
                            status_code=200)


@app.get("/api/captcha")
async def api_captcha():
    return sebicheck.client.get_captcha()


@app.get("/api/health")
async def api_health():
    return {
        "sebi_check": sebicheck.client.health(),
        "registry": {"mirror_rows": registry.mirror_count(),
                     "as_of": registry.mirror_as_of(),
                     "stale": _mirror_stale()},
        "policy": policy.policy_summary(),
        "checks_run": db.total_checks(),
    }


@app.post("/api/admin/refresh-registry")
async def api_refresh(request: Request):
    ip = request.client.host if request.client else "?"
    if ip not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    threading.Thread(target=_maybe_refresh_registry, daemon=True).start()
    return {"started": True}


# static frontend (mounted last so /api/* wins)
app.mount("/", StaticFiles(directory=os.path.abspath(WEB_DIR), html=True), name="web")
