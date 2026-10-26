// Ledger dashboard — shared helpers and charts. Talks to the local FastAPI backend.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const INTERNAL = "__internal";  // chip key: moves between your own accounts (hidden from "All")
const VIA = "__via:";           // chip key prefix: charges paid through a pay-later provider
const SETTLED = "__settled";    // chip key: transfers that cancelled out (hidden from "All")
const HIDDEN = "__hidden";      // chip key: transactions marked "didn't happen" (hidden from "All")
const VIEWS = ["overview", "activity", "trends", "plan", "wishlist", "rules", "settings", "category"];
const REPO = "https://github.com/amojahedi/inbox-ledger";
const state = { meta: null, month: null, view: "overview", summary: null, txs: [], cat: null, q: "", editing: null,
  noLogo: new Set(), settings: null };

// ---------- formatting ----------
const LOCALES = { en: "en-US", de: "de-DE", fr: "fr-FR" };
let nf0, nf2;
function setNumberFormat(pref) {
  const base = LOCALES[pref] || navigator.language || "en-US";
  const make = (opts) => { try { return new Intl.NumberFormat(`${base}-u-nu-latn`, opts); } catch { return new Intl.NumberFormat("en-US", opts); } };
  nf0 = make({ maximumFractionDigits: 0 });
  nf2 = make({ minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
setNumberFormat("en");
const ccyMode = () => state.meta?.settings?.currency || "code";
const money = (v, dec = false) => {
  const n = (dec ? nf2 : nf0).format(v || 0), c = state.meta.currency;
  return ccyMode() === "after" ? `${n} ${c}` : ccyMode() === "none" ? n : `${c} ${n}`;
};
const monthName = (m, style = "long") => {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString("en-US", style === "long" ? { month: "long", year: "numeric" } : { month: "short" });
};
const dayName = (d) => new Date(d + "T00:00").toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" });
const shortDate = (d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const timeOf = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const plural = (n, word, many = `${word}s`) => `${nf0.format(n)} ${n === 1 ? word : many}`;

// Built-in category names are written in title case in categories.yaml; the UI uses sentence case.
const sentence = (name) => name.split(" ").map((w, i) => (i === 0 || /^[A-Z0-9&+]{2,}$/.test(w) ? w : w.toLowerCase())).join(" ");
const cat = (key) => state.meta.categories.find((c) => c.key === key) || { key, name: key, color: "gray" };
const catName = (key) => { const c = cat(key); return c.custom ? c.name : sentence(c.name); };
const color = (key) => `var(--c-${cat(key).color || "gray"})`;
const initials = (name) => (name || "?").replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "•";

// Readable monogram text on any brand colour.
function inkOn(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return "#fff";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#1d1d1f" : "#fff";
}

// The round merchant icon: the brand's logo when logos are on, otherwise a monogram in the
// brand's colour (or the category colour for merchants Ledger doesn't know).
function avatar(name, brand, fallback, extra = "") {
  const tint = brand?.color;
  const style = tint ? `background:${tint};color:${inkOn(tint)}` : `background:${fallback}`;
  const logo = brand && state.meta.logos && !state.noLogo.has(brand.key)
    ? `<img src="/api/logo/${encodeURIComponent(brand.key)}" alt="" loading="lazy" decoding="async" data-brand="${esc(brand.key)}">` : "";
  return `<span class="avatar ${extra}" style="${style}" aria-hidden="true">${esc(initials(brand?.name || name))}${logo}</span>`;
}
document.addEventListener("error", (e) => {
  const img = e.target;
  if (img instanceof HTMLImageElement && img.dataset.brand) { state.noLogo.add(img.dataset.brand); img.remove(); }
}, true);
document.addEventListener("load", (e) => {
  if (e.target instanceof HTMLImageElement && e.target.dataset.brand) e.target.parentElement?.classList.add("has-logo");
}, true);

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2800);
}

// ---------- icons (hand-drawn, SF Symbols-like) ----------
const ICONS = {
  mail: `<rect x="3.5" y="6" width="17" height="12" rx="2.5"/><path d="m4.5 7.5 7.5 6 7.5-6"/>`,
  tray: `<path d="M12 4v11m-4.5-4.5L12 15l4.5-4.5"/><path d="M4.5 15.5v2a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2"/>`,
  play: `<path d="M8 5.5v13l10-6.5z"/>`,
  sparkle: `<path d="M12 4.5l1.6 4.4 4.4 1.6-4.4 1.6L12 16.5l-1.6-4.4L6 10.5l4.4-1.6zM18 15l.7 1.8 1.8.7-1.8.7L18 20l-.7-1.8-1.8-.7 1.8-.7z"/>`,
  lock: `<rect x="5.5" y="10.5" width="13" height="9.5" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>`,
  envelope: `<rect x="3.5" y="6" width="17" height="12" rx="2.5"/><path d="m4.5 7.5 7.5 6 7.5-6"/>`,
  wand: `<path d="M5 19 15.5 8.5M14 5v2m4.5 3.5h-2M17.5 6.5 16 8M11 4.5l.5 1.5M20 13l-1.5-.5"/>`,
  check: `<path d="m6 12.5 4 4 8-9"/>`,
  chevron: `<path d="m9.5 6 6 6-6 6"/>`,
  bank: `<path d="M4 9.5 12 5l8 4.5M5.5 10v7m4.5-7v7m4-7v7m4.5-7v7M4 19h16"/>`,
  question: `<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4"/><circle cx="12" cy="16.6" r=".4" fill="currentColor"/>`,
  code: `<path d="m8.5 8-4 4 4 4m7-8 4 4-4 4"/>`,
};
const icon = (name, cls = "") => `<svg class="ic ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

// ---------- tooltip ----------
const tip = $("#tooltip");
function showTip(evt, html) {
  tip.innerHTML = html; tip.hidden = false;
  const r = evt.currentTarget.getBoundingClientRect();
  tip.style.left = `${Math.min(Math.max(r.left + r.width / 2, 80), innerWidth - 80)}px`;
  tip.style.top = `${r.top}px`;
}
const hideTip = () => (tip.hidden = true);

// ---------- charts ----------
// Bars with a 4px rounded data-end and a square baseline.
function barPath(x, y, w, h, r = 4) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((n) => n >= v);
}

function barChart(el, data, { avg = null, labelEvery = 1, onClick = null } = {}) {
  const W = el.clientWidth, H = el.clientHeight;
  const pad = { t: 10, r: 4, b: 22, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const max = niceMax(Math.max(...data.map((d) => d.value), avg || 0));
  const step = iw / data.length, bw = Math.max(2, Math.min(step * 0.62, 36));
  const y = (v) => pad.t + ih - (v / max) * ih;
  const ticks = [0, max / 2, max];
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(el.dataset.label || "")}"><g class="grid">`;
  for (const t of ticks) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/>`;
  svg += `</g><g class="axis">`;
  for (const t of ticks) svg += `<text x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${t >= 1000 ? +(t / 1000).toFixed(1) + "k" : nf0.format(t)}</text>`;
  data.forEach((d, i) => {
    if (i % labelEvery === 0 || d.hi) svg += `<text x="${pad.l + step * i + step / 2}" y="${H - 6}" text-anchor="middle">${esc(d.label)}</text>`;
  });
  svg += `</g><g>`;
  data.forEach((d, i) => {
    const x = pad.l + step * i + (step - bw) / 2;
    svg += `<rect class="hit" data-i="${i}" x="${pad.l + step * i}" y="${pad.t}" width="${step}" height="${ih}"/>`;
    svg += `<path class="bar ${d.hi ? "hi" : ""}" d="${barPath(x, y(d.value), bw, (d.value / max) * ih)}"/>`;
  });
  svg += `</g>`;
  if (avg) svg += `<line class="avg" x1="${pad.l}" x2="${W - pad.r}" y1="${y(avg)}" y2="${y(avg)}"/><text class="avg-label" x="${W - pad.r}" y="${y(avg) - 6}" text-anchor="end">avg</text>`;
  el.innerHTML = svg + `</svg>`;
  $$(".hit", el).forEach((h) => {
    const d = data[+h.dataset.i];
    h.addEventListener("mouseenter", (e) => { h.nextElementSibling.classList.add("hover"); showTip(e, d.tip); });
    h.addEventListener("mouseleave", () => { h.nextElementSibling.classList.remove("hover"); hideTip(); });
    if (onClick) { h.style.cursor = "pointer"; h.addEventListener("click", () => onClick(d)); }
  });
}

// Line chart: one series per entry; a vertical crosshair shows every visible value for that x.
function lineChart(el, labels, series, { tipTitle = (i) => labels[i], bars = null } = {}) {
  const W = el.clientWidth, H = el.clientHeight;
  const pad = { t: 12, r: 10, b: 22, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b, n = labels.length;
  const vis = series.filter((x) => !x.off);
  const max = niceMax(Math.max(1, ...vis.flatMap((x) => x.values), ...(bars ? bars.values : [])));
  const step = iw / n, x = (i) => pad.l + step * i + step / 2, y = (v) => pad.t + ih - (v / max) * ih;
  const ticks = [0, max / 2, max];
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(el.dataset.label || "")}"><g class="grid">`;
  for (const t of ticks) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/>`;
  svg += `</g><g class="axis">`;
  for (const t of ticks) svg += `<text x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${t >= 1000 ? +(t / 1000).toFixed(1) + "k" : nf0.format(t)}</text>`;
  const every = n > 8 && W < 520 ? 2 : 1;
  labels.forEach((l, i) => { if (i % every === 0) svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${esc(l)}</text>`; });
  svg += `</g>`;
  if (bars) {
    const bw = Math.max(4, Math.min(step * 0.56, 34));
    bars.values.forEach((v, i) => { svg += `<path class="bar" d="${barPath(x(i) - bw / 2, y(v), bw, (v / max) * ih)}"/>`; });
  }
  for (const sr of series) {
    if (sr.off) continue;
    const d = sr.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    svg += `<path class="${sr.cls || "series"}" d="${d}" ${sr.color ? `style="stroke:${sr.color}"` : ""}/>`;
    if (sr.dots) sr.values.forEach((v, i) => { svg += `<circle class="${sr.cls}-dot" cx="${x(i)}" cy="${y(v)}" r="3.5"/>`; });
  }
  svg += `<line class="cross" id="cross-${el.id}" x1="0" x2="0" y1="${pad.t}" y2="${pad.t + ih}" visibility="hidden"/><g id="pts-${el.id}"></g>`;
  labels.forEach((_, i) => { svg += `<rect class="hit" data-i="${i}" x="${pad.l + step * i}" y="${pad.t}" width="${step}" height="${ih}"/>`; });
  el.innerHTML = svg + `</svg>`;
  const cross = $(`#cross-${el.id}`, el), pts = $(`#pts-${el.id}`, el);
  $$(".hit", el).forEach((h) => {
    const i = +h.dataset.i;
    h.addEventListener("mouseenter", (e) => {
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      pts.innerHTML = vis.filter((sr) => sr.color).map((sr) => `<circle class="pt" cx="${x(i)}" cy="${y(sr.values[i])}" r="4" style="fill:${sr.color}"/>`).join("");
      const rows = [...(bars ? [{ name: bars.name, v: bars.values[i] }] : []), ...vis.map((sr) => ({ name: sr.name, v: sr.values[i], color: sr.color }))]
        .sort((a, b) => b.v - a.v).slice(0, 8);
      showTip(e, `<b>${esc(tipTitle(i))}</b>` + rows.map((r) => `<div class="tip-row"><span>${r.color ? `<span class="dot" style="background:${r.color};display:inline-block;width:8px;height:8px;margin-right:6px"></span>` : ""}${esc(r.name)}</span><span>${money(r.v)}</span></div>`).join(""));
    });
    h.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); pts.innerHTML = ""; hideTip(); });
  });
}

