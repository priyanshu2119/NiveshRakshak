#!/usr/bin/env python
"""Download SEBI's daily-updated registry exports (.xls) into the local mirror.

Source (verified live 2026-09-20, docs/RESEARCH.md §3):
  POST https://www.sebi.gov.in/sebiweb/other/IntmExportAction.do?intmId=<N>
  → application/vnd.ms-excel, e.g. "Registered Stock Brokers in equity
    segment as on Sep 19 2026.xls"

Investor-facing categories only (skips FPI/SCSB/ASBA lists — not targets of
retail investment pitches; keeps the mirror lean). Add ids here if scope grows.

Usage:  .venv/bin/python -m tools.refresh_registry [--force]
Also runs automatically at server start when the mirror is empty or >24h old.
"""
import io
import re
import sys
import time

import requests
import xlrd

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from server import db, registry  # noqa: E402

EXPORT_URL = "https://www.sebi.gov.in/sebiweb/other/IntmExportAction.do?intmId={}"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
REFERER = "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognised=yes"

CATEGORIES = {
    13: "Investment Adviser",
    14: "Research Analyst",
    23: "Registered Mutual Funds",
    33: "Registered Portfolio Managers",
    30: "Registered Stock Brokers in equity segment",
    31: "Registered Stock Brokers in Equity Derivative Segment",
    32: "Registered Stock Brokers in Currency Derivative Segment",
    37: "Registered Stock Brokers in Debt Segment",
    38: "Registered Stock Brokers in Interest Rate Derivative Segment",
    2: "Registered Stock Brokers in Commodity Derivative Segment",
    18: "Registered Depository Participants - CDSL",
    19: "Registered Depository Participants - NSDL",
    9: "Merchant Bankers",
    16: "Registered Alternative Investment Funds",
    5: "Banker to an Issue",
    6: "Debentures Trustee",
    7: "Credit Rating Agency",
    10: "Registrars to an Issue and Share Transfer Agents",
    20: "Registered Infrastructure Investment Trusts",
    21: "Registered Venture Capital Funds",
    27: "Registered Custodians",
    42: "Real Estate Investment Trust",
    46: "Registered Vault Managers",
    47: "Registered ESG Rating Providers",
    48: "Registered SM REITs",
}

# header-cell text → canonical field
FIELD_MAP = [
    (re.compile(r"trade\s*name", re.I), "trade_name"),
    (re.compile(r"name\s*of\s*(the\s*)?(intermediary|entity|company|broker|member)|^name$", re.I), "name"),
    (re.compile(r"registration\s*(no|number|#)|reg\.?\s*no|sebi\s*reg", re.I), "reg_no"),
    (re.compile(r"^type$|intermediary\s*type|category", re.I), "type"),
    (re.compile(r"valid", re.I), "validity"),
    (re.compile(r"exchange", re.I), "exchange"),
]


def _map_headers(header_row: list) -> dict[int, str]:
    mapping = {}
    for idx, cell in enumerate(header_row):
        text = str(cell).strip()
        if not text:
            continue
        for rx, field in FIELD_MAP:
            if rx.search(text):
                mapping.setdefault(idx, field)
                break
    return mapping


def parse_xls(data: bytes, category: str) -> list[dict]:
    wb = xlrd.open_workbook(file_contents=data)
    sh = wb.sheet_by_index(0)
    # find the header row within the first 10 rows (files carry title rows)
    header_i, mapping = None, {}
    for i in range(min(10, sh.nrows)):
        m = _map_headers(sh.row_values(i))
        if "name" in m.values():
            header_i, mapping = i, m
            break
    if header_i is None:
        return []
    rows = []
    for i in range(header_i + 1, sh.nrows):
        vals = sh.row_values(i)
        rec = {}
        for idx, field in mapping.items():
            if idx < len(vals):
                v = vals[idx]
                if isinstance(v, float) and v == int(v):
                    v = int(v)
                rec[field] = str(v).strip()
        name = rec.get("name") or rec.get("trade_name") or ""
        if not name or len(name) < 2:
            continue
        rows.append({
            "name": name,
            "name_norm": registry.normalize_name(name),
            "trade_name": rec.get("trade_name", ""),
            "reg_no": rec.get("reg_no", ""),
            "reg_no_norm": registry.normalize_regno(rec.get("reg_no", "")),
            "type": rec.get("type", "") or category,
            "validity": rec.get("validity", ""),
            "exchange": rec.get("exchange", ""),
        })
    return rows


def download(intm_id: int) -> bytes | None:
    try:
        r = requests.post(EXPORT_URL.format(intm_id),
                          headers={"User-Agent": UA, "Referer": REFERER},
                          timeout=(10, 120))
        if r.status_code == 200 and len(r.content) > 2048:
            return r.content
    except requests.RequestException as e:
        print(f"  ! {intm_id}: {e}")
    return None


def refresh(force: bool = False, max_age_h: float = 24.0) -> dict:
    db.init()
    last = db.meta_get("registry_refreshed_at")
    if last and not force and (time.time() - int(last)) < max_age_h * 3600:
        return {"skipped": True, "rows": db.registry_count(),
                "as_of": registry.mirror_as_of()}
    total, per_cat = 0, {}
    for iid, cat in CATEGORIES.items():
        data = download(iid)
        if data is None:
            per_cat[iid] = "download_failed"
            continue
        try:
            rows = parse_xls(data, cat)
        except Exception as e:  # corrupt/changed layout → keep old rows, report
            per_cat[iid] = f"parse_failed: {e}"
            continue
        if rows:
            db.registry_replace_rows(iid, rows)
            per_cat[iid] = len(rows)
            total += len(rows)
        else:
            per_cat[iid] = "empty"
        time.sleep(0.4)  # be polite to sebi.gov.in
    if total:
        db.meta_set("registry_refreshed_at", int(time.time()))
    return {"skipped": False, "imported": total, "per_category": per_cat,
            "mirror_rows": db.registry_count()}


if __name__ == "__main__":
    res = refresh(force="--force" in sys.argv)
    print(res)
