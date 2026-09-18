"""Live client for SEBI Check (siportal.sebi.gov.in) — the PRIMARY check.

Contract reverse-engineered from the portal's own JS and verified with live
requests on 2026-09-20 (see docs/RESEARCH.md §2):

  session   GET  /intermediary/sebi-check          → sets CA_SESSIONID (WAF
                                                     blocks POSTs without it: 505)
  upi       POST /intermediary/sebi-check/validate.html
            multipart: ctype=upi-check, upi, captcha
  account   POST /intermediary/sebi-check/accValidate.html
            multipart: ctype=account-check, ifsc, accNo=SHA512hex(accNo), captcha
  captcha   GET  /intermediary/sebi-check/captcha-data
            → {imageBase64, audioBase64, expiryMs, maxFailedAttempts}

  response  {status: success|error, entity: {name, regNo, role, desc,
             legalAccHolderName, ...}, errorCode, message, transactionId,
             isTemplateUpiId}
  header    X-Captcha-Required: true|false
  codes     419 captcha expired · 420 too many failed attempts · 429 rate
            limited · 432 captcha missing · 433 captcha incorrect · 505 WAF

Design rules:
  - captcha is PASSED THROUGH to the user, never bypassed or auto-solved
  - one shared session serialized by a lock (portal captcha state is
    session-scoped).  ponytail: global lock + shared session; per-user sessions
    if this ever serves concurrent traffic at scale.
  - circuit breaker: 3 consecutive transport failures → 5 min cooldown; the
    product then says "couldn't verify", never a silent pass
  - terminal results cached 6h in SQLite (viral scam handle checked 100× hits
    SEBI once); cached verdicts are labeled with checked_at
"""
import hashlib
import re
import threading
import time
from datetime import datetime, timezone

import requests

from . import db

BASE = "https://siportal.sebi.gov.in/intermediary/sebi-check"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "X-Requested-Via": "SI Portal",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE,
    "Origin": "https://siportal.sebi.gov.in",
    "Accept": "*/*",
}
TIMEOUT = (10, 25)          # connect, read
CACHE_TTL = 6 * 3600        # 6h
CIRCUIT_FAILS = 3
CIRCUIT_COOLDOWN = 300      # 5 min
CAPTCHA_TTL = 120           # matches portal expiryMs

# Loose UPI shape gate (saves SEBI calls for obvious garbage; anything looser
# than this the portal itself would reject client-side).
_UPI_SHAPE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,253}@[a-zA-Z0-9][a-zA-Z0-9-]{1,63}$")
_IFSC_SHAPE = re.compile(r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class SebiCheckClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: requests.Session | None = None
        self._fails = 0
        self._circuit_open_until = 0.0
        self._captchas: dict[str, float] = {}   # captcha_id → issued_ts

    # -- session ---------------------------------------------------------
    def _bootstrap(self) -> bool:
        """GET the portal page to obtain CA_SESSIONID. True on success."""
        try:
            s = requests.Session()
            r = s.get(BASE, headers={"User-Agent": UA}, timeout=TIMEOUT)
            if r.status_code == 200 and any(
                    c.name == "CA_SESSIONID" for c in s.cookies):
                self._session = s
                return True
            # some deployments set the cookie on a redirect hop; accept any 200
            if r.status_code == 200:
                self._session = s
                return True
        except requests.RequestException:
            pass
        return False

    def _ensure_session(self) -> bool:
        if self._session is not None:
            return True
        return self._bootstrap()

    def _trip(self, cooldown: float = CIRCUIT_COOLDOWN) -> None:
        self._fails += 1
        if self._fails >= CIRCUIT_FAILS:
            self._circuit_open_until = time.time() + cooldown

    def _ok(self) -> None:
        self._fails = 0

    # -- captcha ---------------------------------------------------------
    def get_captcha(self) -> dict:
        """Fetch a fresh captcha challenge for pass-through to the user."""
        with self._lock:
            if time.time() < self._circuit_open_until:
                return {"state": "unavailable", "reason": "circuit_open"}
            if not self._ensure_session():
                self._trip()
                return {"state": "unavailable", "reason": "session"}
            try:
                r = self._session.get(f"{BASE}/captcha-data", headers=HEADERS,
                                      timeout=TIMEOUT)
                data = r.json()
                cid = hashlib.sha1(
                    f"{time.time()}{data.get('imageBase64', '')[:64]}".encode()
                ).hexdigest()[:16]
                self._captchas[cid] = time.time()
                self._prune_captchas()
                self._ok()
                return {"state": "ok", "captcha_id": cid,
                        "image_b64": data["imageBase64"],
                        "expires_in": int(data.get("expiryMs", 120000)) // 1000,
                        "max_failed": data.get("maxFailedAttempts", 3)}
            except (requests.RequestException, KeyError, ValueError):
                self._trip()
                return {"state": "unavailable", "reason": "captcha_fetch"}

    def _prune_captchas(self) -> None:
        cutoff = time.time() - CAPTCHA_TTL
        self._captchas = {k: v for k, v in self._captchas.items() if v > cutoff}

    def captcha_valid(self, captcha_id: str) -> bool:
        ts = self._captchas.get(captcha_id)
        return ts is not None and (time.time() - ts) <= CAPTCHA_TTL

    # -- core POST -------------------------------------------------------
    def _post(self, path: str, fields: dict) -> dict:
        """POST multipart with session/WAF/captcha/rate-limit handling.
        Returns {http, json?, captcha_required, reason?}.
        Holds the session lock for the whole exchange: the portal session is
        stateful (cookies + captcha), so concurrent use would race."""
        with self._lock:
            return self._post_locked(path, fields)

    def _post_locked(self, path: str, fields: dict) -> dict:
        if time.time() < self._circuit_open_until:
            return {"http": 0, "reason": "circuit_open"}
        if not self._ensure_session():
            self._trip()
            return {"http": 0, "reason": "session"}
        for attempt in (1, 2):
            try:
                r = self._session.post(f"{BASE}/{path}", headers=HEADERS,
                                       files={k: (None, v) for k, v in fields.items()},
                                       timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == 1:
                    time.sleep(1.0)
                    continue
                self._trip()
                return {"http": 0, "reason": "timeout"}
            cap_req = r.headers.get("X-Captcha-Required", "").lower() == "true"
            if r.status_code == 505:      # WAF: stale/blocked session → re-bootstrap once
                self._session = None
                if attempt == 1 and self._ensure_session():
                    continue
                self._trip()
                return {"http": 505, "reason": "waf"}
            if r.status_code == 429:
                self._trip(cooldown=60)
                return {"http": 429, "reason": "rate_limited", "captcha_required": cap_req}
            if r.status_code == 420:
                self._trip(cooldown=120)
                return {"http": 420, "reason": "too_many_attempts", "captcha_required": cap_req}
            if r.status_code in (419, 432, 433):
                self._ok()
                return {"http": r.status_code,
                        "reason": {419: "captcha_expired", 432: "captcha_missing",
                                   433: "captcha_incorrect"}[r.status_code],
                        "captcha_required": True}
            if r.status_code != 200:
                self._trip()
                return {"http": r.status_code, "reason": f"http_{r.status_code}",
                        "captcha_required": cap_req}
            try:
                payload = r.json()
            except ValueError:
                self._trip()
                return {"http": 200, "reason": "parse_error"}
            self._ok()
            return {"http": 200, "json": payload, "captcha_required": cap_req}
        return {"http": 0, "reason": "exhausted"}

    # -- public API ------------------------------------------------------
    def check_upi(self, upi: str, captcha_text: str = "") -> dict:
        upi = (upi or "").strip().lower()
        if not _UPI_SHAPE.match(upi):
            return self._result("invalid", error_code="FORMAT", reason_code="format_invalid",
                                message="Not a UPI-ID shaped string",
                                txn=None, entity=None, source="local")
        cache_key = f"upi:{upi}"
        cached = db.cache_get(cache_key, CACHE_TTL)
        if cached and not captcha_text:
            cached["source"] = "cache"
            return cached
        res = self._post("validate.html",
                         {"ctype": "upi-check", "upi": upi, "captcha": captcha_text or ""})
        out = self._interpret(res, kind="upi", value=upi)
        if out["state"] in ("verified", "invalid") and out.get("source") == "live":
            db.cache_set(cache_key, {k: v for k, v in out.items() if k != "captcha"})
        return out

    def check_account(self, acc: str, ifsc: str, captcha_text: str = "") -> dict:
        acc = (acc or "").strip()
        ifsc = (ifsc or "").strip().upper()
        if not acc.isalnum() or not _IFSC_SHAPE.match(ifsc):
            return self._result("invalid", error_code="FORMAT", reason_code="format_invalid",
                                message="Account/IFSC shape invalid",
                                txn=None, entity=None, source="local")
        acc_hash = hashlib.sha512(acc.encode()).hexdigest()  # portal's fetchAccNo()
        cache_key = f"acc:{hashlib.sha256((acc + ifsc).encode()).hexdigest()[:16]}"
        cached = db.cache_get(cache_key, CACHE_TTL)
        if cached and not captcha_text:
            cached["source"] = "cache"
            return cached
        res = self._post("accValidate.html",
                         {"ctype": "account-check", "ifsc": ifsc,
                          "accNo": acc_hash, "captcha": captcha_text or ""})
        out = self._interpret(res, kind="account", value=f"{ifsc}•{acc[-4:]}")
        if out["state"] in ("verified", "invalid") and out.get("source") == "live":
            db.cache_set(cache_key, {k: v for k, v in out.items() if k != "captcha"})
        return out

    # -- response interpretation ------------------------------------------
    def _interpret(self, res: dict, kind: str, value: str) -> dict:
        if res.get("json") is None:
            reason = res.get("reason", "unknown")
            if res.get("captcha_required") or reason in (
                    "captcha_missing", "captcha_incorrect", "captcha_expired"):
                cap = self.get_captcha()
                if cap["state"] == "ok":
                    return self._result("captcha_required", reason=reason,
                                        captcha=cap, kind=kind, value=value)
                return self._result("unavailable", reason="captcha_unavailable",
                                    kind=kind, value=value)
            return self._result("unavailable", reason=reason, kind=kind, value=value)
        j = res["json"]
        status = (j.get("status") or "").lower()
        entity = j.get("entity") or None
        txn = j.get("transactionId")
        if status == "success" and entity:
            return self._result("verified", entity=entity, txn=txn,
                                error_code=None, message=j.get("message"),
                                kind=kind, value=value,
                                is_template=bool(j.get("isTemplateUpiId")))
        # status == error (or anything unexpected) → not verified. Definitive
        # "not found / not valid" codes map to invalid (the portal itself shows
        # "No Match Found" for these); genuinely unknown/system codes stay
        # unavailable so we never overclaim in either direction.
        code = (j.get("errorCode") or "").upper()
        NOT_FOUND_CODES = ("UPI_ID_INVALID", "ACCOUNT_INVALID", "NO_MATCH",
                           "ACCOUNT_NOT_FOUND", "UPI_ID_NOT_FOUND",
                           "DATA_NOT_FOUND", "NOT_FOUND", "NO_RECORD",
                           "INVALID_IFSC", "IFSC_NOT_FOUND")
        if code in NOT_FOUND_CODES or \
                "not valid" in (j.get("message") or "").lower() or \
                "no match" in (j.get("message") or "").lower() or \
                "not found" in (j.get("message") or "").lower():
            reason = ("format_invalid" if code == "FORMAT" else
                      "sebi_says_invalid" if kind == "upi" else "account_no_match")
            return self._result("invalid", entity=None, txn=txn, error_code=code,
                                reason_code=reason,
                                message=j.get("message"), kind=kind, value=value,
                                is_template=bool(j.get("isTemplateUpiId")))
        return self._result("unavailable", reason=f"sebi_error_{code or 'unknown'}",
                            reason_code=f"sebi_error_{code or 'unknown'}",
                            txn=txn, message=j.get("message"), kind=kind, value=value)

    def _result(self, state: str, **kw) -> dict:
        out = {"state": state, "source": kw.pop("source", "live"),
               "checked_at": _now(), "kind": kw.pop("kind", None),
               "value": kw.pop("value", None)}
        out.update(kw)
        return out

    def health(self) -> dict:
        with self._lock:
            if time.time() < self._circuit_open_until:
                return {"state": "circuit_open",
                        "retry_in": int(self._circuit_open_until - time.time())}
            ok = self._ensure_session()
            return {"state": "ok" if ok else "unreachable", "fails": self._fails}


client = SebiCheckClient()

# --- self-check (offline-safe: shape gate + interpretation logic only) -------
if __name__ == "__main__":
    db.init()
    r = client.check_upi("not a upi")
    assert r["state"] == "invalid" and r["error_code"] == "FORMAT", r
    r = client.check_account("123", "BADIFSC")
    assert r["state"] == "invalid" and r["error_code"] == "FORMAT", r
    fake = {"http": 200, "json": {"status": "success",
            "entity": {"name": "X LTD", "regNo": "INZ1", "role": "Broker"},
            "transactionId": "TXN-1", "isTemplateUpiId": None}}
    out = client._interpret(fake, "upi", "x.brk@validhdfc")
    assert out["state"] == "verified" and out["entity"]["name"] == "X LTD", out
    fake_err = {"http": 200, "json": {"status": "error", "errorCode": "UPI_ID_INVALID",
                "message": "UPI Id is not valid!", "transactionId": "TXN-2", "entity": None}}
    out = client._interpret(fake_err, "upi", "fake.brk@validhdfc")
    assert out["state"] == "invalid" and out["txn"] == "TXN-2", out
    out = client._interpret({"http": 0, "reason": "timeout"}, "upi", "x@y")
    assert out["state"] == "unavailable" and out["reason"] == "timeout", out
    print("sebicheck.py self-check OK (offline logic)")
