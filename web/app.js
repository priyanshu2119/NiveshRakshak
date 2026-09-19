/* NiveshRakshak frontend logic — no framework, no build step (DECISIONS.md §1).
   Flows: submit → progress → /api/check → render verdict card
          captcha_pending → solve → resubmit with captcha_text
          share → Web Share API / html2canvas PNG / clipboard text */
"use strict";

window.NR = { lastVerdict: null };

const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- toast ---------- */
let toastTimer;
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = el("div", "", ""); t.id = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3600);
}

/* ---------- language ---------- */
$("#lang-en").addEventListener("click", () => setLang("en"));
$("#lang-hi").addEventListener("click", () => setLang("hi"));
applyStatic();

/* ---------- image input ---------- */
const dz = $("#dropzone"), fileInput = $("#image"), dzPrev = $("#dz-preview"), dzThumb = $("#dz-thumb");
let imageFile = null;

function setImage(f) {
  if (f && !/^image\/(png|jpeg|webp)$/.test(f.type)) { toast(t("err_image")); return; }
  imageFile = f || null;
  if (imageFile) {
    dzThumb.src = URL.createObjectURL(imageFile);
    dzPrev.hidden = false;
  } else {
    dzThumb.src = ""; dzPrev.hidden = true;
  }
}
fileInput.addEventListener("change", () => setImage(fileInput.files[0]));
$("#dz-remove").addEventListener("click", () => { setImage(null); fileInput.value = ""; });
for (const ev of ["dragover", "dragenter"]) dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); });
for (const ev of ["dragleave", "drop"]) dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); });
dz.addEventListener("drop", (e) => setImage(e.dataTransfer.files[0]));

/* ---------- progress theatre (mirrors the real pipeline phases) ---------- */
let progTimers = [];
function progressOn() {
  const p = $("#progress"); p.hidden = false;
  const steps = [...p.querySelectorAll("li")];
  steps.forEach((li) => li.classList.remove("active", "done"));
  steps.forEach((li, i) => {
    progTimers.push(setTimeout(() => {
      li.classList.add("active");
      if (i > 0) steps[i - 1].classList.replace("active", "done");
    }, i * 450));
  });
}
function progressOff() {
  progTimers.forEach(clearTimeout); progTimers = [];
  const p = $("#progress");
  p.querySelectorAll("li").forEach((li) => li.classList.remove("active"));
  p.querySelectorAll("li").forEach((li) => li.classList.add("done"));
  setTimeout(() => { p.hidden = true; p.querySelectorAll("li").forEach((li) => li.classList.remove("done")); }, 500);
}

/* ---------- captcha ---------- */
let captchaId = null;
const capPanel = $("#captcha-panel"), capImg = $("#cap-img"), capText = $("#cap-text");

function showCaptcha(blob, note) {
  captchaId = blob.captcha_id;
  capImg.src = "data:image/png;base64," + blob.image_b64;
  capText.value = "";
  capPanel.hidden = false;
  if (note) toast(note);
  capPanel.scrollIntoView({ behavior: "smooth", block: "center" });
  capText.focus();
}
function hideCaptcha() { capPanel.hidden = true; captchaId = null; }

$("#cap-refresh").addEventListener("click", async () => {
  const r = await fetch("/api/captcha"); const j = await r.json();
  if (j.state === "ok") showCaptcha(j); else toast(t("hl_body.unverifiable"));
});
$("#cap-submit").addEventListener("click", () => submitCheck(true));

/* ---------- submit ---------- */
$("#check-form").addEventListener("submit", (e) => { e.preventDefault(); submitCheck(false); });

async function submitCheck(fromCaptcha) {
  const msg = $("#message").value.trim();
  if (!msg && !imageFile) { toast(t("err_empty")); $("#message").focus(); return; }
  const fd = new FormData();
  fd.append("message", msg);
  fd.append("claimed_name", $("#claimed-name").value.trim());
  fd.append("claimed_regno", $("#claimed-regno").value.trim());
  if (fromCaptcha && captchaId) fd.append("captcha_text", capText.value.trim());
  if (imageFile) fd.append("image", imageFile);

  $("#submit-btn").disabled = true;
  progressOn();
  try {
    const r = await fetch("/api/check", { method: "POST", body: fd });
    if (r.status === 429) { toast(t("err_rate")); return; }
    const v = await r.json();
    if (v.error === "image_too_large" || v.error && v.error.startsWith("image")) { toast(t("err_image")); return; }
    if (v.error) { toast(t("err_internal")); renderVerdict(v); return; }
    if (v.headline.state === "captcha_pending" && v.captcha) {
      hideCaptcha();
      showCaptcha(v.captcha, fromCaptcha ? t("cap_bad") : null);
      renderVerdict(v);
      return;
    }
    hideCaptcha();
    renderVerdict(v);
  } catch (err) {
    toast(t("err_internal"));
  } finally {
    $("#submit-btn").disabled = false;
    progressOff();
  }
}

/* ---------- verdict rendering ---------- */
const ICONS = {
  red_flag: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M12 2 22 20H2Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 9v5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><circle cx="12" cy="17" r="1.2" fill="currentColor"/></svg>',
  verified: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M12 2 21 5.5V11c0 5.7-3.9 10-9 11.3C5.9 21 2 16.7 2 11V5.5Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M8 12.2 11 15.2 16.5 9.2" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  caution: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><circle cx="12" cy="12" r="9.2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7.5V13" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><circle cx="12" cy="16.4" r="1.25" fill="currentColor"/></svg>',
  unverifiable: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 16 21.5 21.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M7.8 10.5h5.4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  captcha_pending: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><rect x="3" y="8" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 8V6a4 4 0 018 0v2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="14" r="1.6" fill="currentColor"/></svg>',
};
const PILL_CLASS = { invalid: "pill-bad", verified: "pill-ok", unavailable: "pill-unk", captcha_required: "pill-unk" };

function reasonText(p) {
  const code = p.reason_code || p.reason || "";
  const vars = { psp: p.psp || "", claimed: "", actual: "" };
  return t("reason_body." + code, vars) !== "reason_body." + code
    ? t("reason_body." + code, vars)
    : (t("reason_body." + (p.state === "unavailable" ? (code in { timeout: 1, rate_limited: 1, circuit_open: 1 } ? code : "timeout") : "format_invalid")));
}

function primaryRow(p) {
  const row = el("div", "prow");
  const pill = el("span", "pill " + (PILL_CLASS[p.state] || "pill-unk"), t("pill." + p.state));
  const val = p.kind === "account"
    ? `${esc(p.ifsc || "—")} • ${esc(p.account_masked || p.value || "")}`
    : esc(p.value || "");
  const top = el("div", "top"); top.append(pill, el("span", "val", val));
  row.append(top);

  if (p.state === "verified" && p.entity) {
    const e = p.entity;
    row.append(el("div", "sub", t("belongs_to", { name: esc(e.name || "?") })));
    if (e.regNo || e.role) {
      row.append(el("div", "sub", t("reg_no_line", { regno: esc(e.regNo || "—"), role: esc(e.role || "") })));
    }
    if (e.legalAccHolderName && p.kind === "account") {
      row.append(el("div", "sub", t("legal_holder", { name: esc(e.legalAccHolderName) })));
    }
  } else if (p.state === "invalid" || p.state === "unavailable") {
    row.append(el("div", "sub", reasonText(p)));
  }
  const meta = [];
  if (p.txn) meta.push(esc(p.txn));
  if (p.source === "cache" && p.checked_at) meta.push("cached · " + esc(p.checked_at));
  if (meta.length) row.append(el("div", "txn", meta.join(" · ")));
  return row;
}

function registrySection(reg) {
  const sec = el("section", "vsec");
  sec.append(el("h3", "", `${t("sec_registry")} <span class="tag">${t("tag_registry")}</span>`));
  if (reg && reg.query && reg.query.origin === "sebi_entity") {
    sec.append(el("p", "caveat", t("reg_origin_sebi")));
  }
  if (!reg) {
    sec.append(el("div", "regbox none", `<h4>${t("reg_summaries.none")}</h4>`));
    return sec;
  }
  const q = reg.query || {};
  const claim = q.name || q.regno || "";
  if (reg.state === "exact") {
    const box = el("div", "regbox");
    box.append(el("h4", "", t("reg_exact_title")));
    // group segment-wise registrations of the same entity (same name+regno)
    const grouped = new Map();
    for (const m of (reg.matches || [])) {
      const k = (m.name || "") + "|" + (m.reg_no || "");
      if (!grouped.has(k)) grouped.set(k, []);
      grouped.get(k).push(m);
    }
    let shown = 0;
    for (const [, ms] of grouped) {
      if (shown++ >= 4) break;
      const m = ms[0];
      const more = ms.length > 1 ? ` <span class="mono">(+${ms.length - 1} ${LANG === "hi" ? "और पंजीकरण" : "more registrations"})</span>` : "";
      box.append(el("div", "match",
        `<b>${esc(m.name)}</b>${m.trade_name && m.trade_name !== m.name ? ` (${esc(m.trade_name)})` : ""}<br>` +
        `<span class="mono">${esc(m.reg_no || "—")} · ${esc(m.type || "")}${m.validity ? " · " + esc(m.validity) : ""}</span>${more}`));
    }
    box.append(el("p", "caveat", t("reg_caveat")));
    sec.append(box);
  } else if (reg.state === "near") {
    const box = el("div", "regbox near");
    box.append(el("h4", "", "⚠ " + t("reg_near_title")));
    for (const m of (reg.near || []).slice(0, 3)) {
      box.append(el("div", "", t("reg_near_body", { claim: esc(claim), real: esc(m.name) }) +
        `<div class="match"><span class="mono">${esc(m.reg_no || "—")} · ${esc(m.type || "")}</span></div>`));
    }
    sec.append(box);
  } else if (reg.state === "not_found") {
    sec.append(el("div", "regbox none",
      `<h4>${t("reg_notfound_title")}</h4><p class="sub">${t("reg_notfound_body", {
        claim: esc(claim), rows: (reg.mirror_rows || 0).toLocaleString(LANG === "hi" ? "hi-IN" : "en-IN"),
        as_of: esc(reg.as_of || "?") })}</p>`));
  } else {
    sec.append(el("div", "regbox none",
      `<h4>${t("reg_unavailable_title")}</h4><p class="sub">${t("reg_unavailable_body")}</p>`));
  }
  const src = (reg.sources || []).join("+") || "—";
  const asof = reg.as_of ? ` · as of ${esc(reg.as_of)}` : "";
  sec.append(el("p", "caveat", t("reg_source", { source: esc(src), asof: asof })));
  return sec;
}

function supportingSection(sup, headlineState) {
  const sec = el("section", "vsec");
  sec.append(el("h3", "", `${t("sec_supporting")} <span class="tag">${t("tag_supporting")}</span>`));
  let any = false;
  for (const f of (sup.flags || [])) {
    any = true;
    const cls = f.id === "category_mismatch" ? "flagbox bad" : "flagbox";
    const vars = {
      entity_name: esc(f.entity_name || ""), claimed_name: esc(f.claimed_name || ""),
      claimed: esc(f.claimed_label || f.claimed_category || ""), actual: esc(f.suffix_label || f.suffix || ""),
      role: esc(f.entity_role || ""), suffix_label: esc(f.suffix_label || ""), qr_payee: esc(f.qr_payee || ""),
    };
    sec.append(el("div", cls, t("flag_" + f.id, vars)));
  }
  const rf = sup.redflags || [];
  if (rf.length) {
    any = true;
    const chips = el("div", "chips");
    const why = el("div", "chipwhy"); why.hidden = true;
    rf.forEach((h, i) => {
      const b = el("button", "chip", `${esc(h.label[LANG])}: “${esc(h.matched)}”`);
      b.type = "button"; b.setAttribute("aria-expanded", "false");
      b.addEventListener("click", () => {
        const open = b.getAttribute("aria-expanded") === "true";
        chips.querySelectorAll(".chip").forEach((c) => { c.setAttribute("aria-expanded", "false"); });
        if (open) { why.hidden = true; return; }
        b.setAttribute("aria-expanded", "true");
        why.innerHTML = `<b>${esc(h.label[LANG])}</b> — ${esc(h.why[LANG])}`;
        why.hidden = false;
      });
      chips.append(b);
    });
    sec.append(chips, why);
  }
  if ((sup.amounts || []).length) {
    any = true;
    sec.append(el("p", "clean", t("amounts_line", { amounts: sup.amounts.map(esc).join(" · ") })));
  }
  if (!any) sec.append(el("p", "clean", t("supporting_clean")));
  return sec;
}

function renderVerdict(v) {
  window.NR.lastVerdict = v;
  const host = $("#result");
  host.innerHTML = "";
  const state = v.headline.state;

  const card = el("article", "verdict"); card.id = "verdict-card";
  // head
  const head = el("div", "verdict-head");
  head.append(el("div", "who",
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 1.8 21.2 5.3V11c0 5.7-3.9 10-9.2 11.3C6.7 21 2.8 16.7 2.8 11V5.3Z" fill="#22324F"/><path d="M12 6.2 17.8 15.9H6.2Z" fill="#157F3D"/><path d="M9.9 12.9 11.5 14.6 14.7 10.4" fill="none" stroke="#F7F3EC" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg><b>NiveshRakshak</b>'));
  const meta = v.meta || {};
  const timeStr = (meta.checked_at || "").replace("T", " ").slice(0, 16);
  head.append(el("div", "ids",
    `${t("check_id", { id: meta.check_id ?? "—" })}<br>${t("checked_at", { time: esc(timeStr) })}${meta.duration_ms ? "<br>" + t("took", { ms: meta.duration_ms }) : ""}`));
  const st = t("stamp." + state);
  head.append(el("div", "stamp st-" + state, `${esc(st[0])}<small>${esc(st[1])}</small>`));
  card.append(head);

  // headline
  const hl = el("div", "headline hl-" + state);
  hl.append(el("div", "ico", ICONS[state] || ICONS.caution));
  let body = t("hl_body." + state);
  if (state === "red_flag") {
    const firstBad = (v.primaries || []).find((p) => p.state === "invalid");
    const catMis = (v.supporting?.flags || []).find((f) => f.id === "category_mismatch");
    if (catMis) {
      body = t("reason_body.category_mismatch", {
        claimed: esc(catMis.claimed_label || catMis.claimed_category || "?"),
        actual: esc(catMis.suffix_label || catMis.suffix || "?") });
    } else if (firstBad) {
      body = reasonText(firstBad);
    }
  }
  const h2 = el("h2", "", t("hl_title." + state)); h2.tabIndex = -1;
  hl.append(el("div", "", ""));
  hl.lastChild.append(h2, el("p", "", body));
  card.append(hl);

  // primary
  if ((v.primaries || []).length) {
    const sec = el("section", "vsec");
    sec.append(el("h3", "", `${t("sec_primary")} <span class="tag">${t("tag_primary")}</span>`));
    for (const p of v.primaries) sec.append(primaryRow(p));
    const note = v.headline.policy_note;
    if (note) {
      if (note.sip_carveout) sec.append(el("p", "caveat", t("sip_note")));
      if (note.in_transition) sec.append(el("p", "caveat", t("transition_note", { cutoff: esc(note.legacy_cutoff) })));
    }
    card.append(sec);
  }

  card.append(registrySection(v.registry));
  card.append(supportingSection(v.supporting || {}, state));

  // next action
  const na = el("div", "nextaction");
  na.append(el("h3", "", t("next_h")));
  na.append(el("p", "", t("next." + state)));
  if (state === "red_flag" || state === "unverifiable") na.append(el("p", "helpline", t("helpline")));
  card.append(na);

  // foot
  const src = meta.sources || {};
  const pol = meta.policy || {};
  card.append(el("footer", "verdict-foot",
    `<p class="vns">${t("vns_line")}</p>` +
    `<p>SEBI Check: ${esc(src.sebi_check || "?")} · registry mirror: ${(src.registry_mirror_rows || 0).toLocaleString("en-IN")} rows${src.registry_as_of ? " (" + esc(src.registry_as_of) + ")" : ""}${src.ocr && src.ocr !== "none" ? " · OCR: " + esc(src.ocr) : ""} · policy: ${esc(pol.mode || "?")}/${esc(pol.legacy_cutoff || "?")}</p>`));

  host.append(card);

  // share row
  const row = el("div", "sharerow");
  const bShare = el("button", "main", `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 3v12m0-12 4 4m-4-4L8 7M5 14v5h14v-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg> ${t("share_btn")}`);
  bShare.type = "button"; bShare.addEventListener("click", shareWeb);
  const bPng = el("button", "", t("share_png")); bPng.type = "button"; bPng.addEventListener("click", sharePng);
  const bCopy = el("button", "", t("share_copy")); bCopy.type = "button"; bCopy.addEventListener("click", shareCopy);
  row.append(bShare, bPng, bCopy);
  host.append(row);

  h2.focus({ preventScroll: true });
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- sharing ---------- */
window.NR.renderVerdict = renderVerdict;   // i18n.js re-renders on language switch

function shareText() {
  const v = window.NR.lastVerdict; if (!v) return "";
  const st = t("stamp." + v.headline.state)[0];
  const p0 = (v.primaries || [])[0];
  const primary = p0 ? `${p0.value || p0.account_masked || ""} → ${t("pill." + p0.state)}` : t("hl_title." + v.headline.state);
  const reg = v.registry ? t("reg_summaries." + v.registry.state) : t("reg_summaries.none");
  return t("share_text", {
    stamp: st, title: t("hl_title." + v.headline.state), primary,
    reg, id: v.meta?.check_id ?? "—",
    time: (v.meta?.checked_at || "").replace("T", " ").slice(0, 16),
  });
}

async function shareWeb() {
  const text = shareText();
  if (navigator.share) {
    try { await navigator.share({ text }); toast(t("toast_shared")); return; }
    catch (e) { if (e.name === "AbortError") return; }
  }
  // fallback: try file share via PNG, else copy
  try { await sharePng(true); } catch { await shareCopy(); }
}

async function sharePng(quiet) {
  const card = $("#verdict-card"); if (!card || !window.html2canvas) return;
  const canvas = await html2canvas(card, { backgroundColor: "#F7F3EC", scale: 2, useCORS: false });
  canvas.toBlob(async (blob) => {
    if (!blob) return;
    const file = new File([blob], "niveshrakshak-verdict.png", { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], text: shareText() }); toast(t("toast_shared")); return; }
      catch (e) { if (e.name === "AbortError") return; }
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = file.name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    if (!quiet) toast(t("toast_png"));
  }, "image/png");
}

async function shareCopy() {
  try { await navigator.clipboard.writeText(shareText()); toast(t("toast_copied")); }
  catch { toast(t("toast_share_fail")); }
}

/* ---------- footer build info ---------- */
(async function buildInfo() {
  try {
    const r = await fetch("/api/health"); const h = await r.json();
    $("#build-info").textContent = t("build_line", {
      rows: (h.registry?.mirror_rows || 0).toLocaleString("en-IN"),
      as_of: h.registry?.as_of || "?",
      policy: `${h.policy?.mode}/${h.policy?.legacy_cutoff}`,
    });
  } catch { /* offline — leave empty */ }
})();
