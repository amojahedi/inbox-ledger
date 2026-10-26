// Ledger dashboard — dependency-free. Talks to the local FastAPI backend.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const INTERNAL = "__internal";  // chip key: moves between your own accounts (hidden from "All")
const VIA = "__via:";           // chip key prefix: charges paid through a pay-later provider
const SETTLED = "__settled";    // chip key: transfers that cancelled out (hidden from "All")
const HIDDEN = "__hidden";      // chip key: transactions marked "didn't happen" (hidden from "All")
const VIEWS = ["overview", "activity", "trends", "rules", "settings", "category"];
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

// ---------- category detail ----------
function openCategory(key) {
  state.detailCat = key;
  state.backTo = state.view === "category" ? state.backTo : state.view;
  go("category");
}

async function loadCategory() {
  const key = state.detailCat;
  if (!key) return go("overview");
  const d = await api(`/api/category/${encodeURIComponent(key)}?month=${state.month}`);
  $("#cat-eyebrow").innerHTML = `<span class="dot" style="background:${color(key)}"></span>${esc(catName(key))} · ${esc(monthName(state.month))}`;
  $("#cat-total").innerHTML = money(d.total);
  const change = d.previous ? Math.round(((d.total - d.previous) / d.previous) * 100) : null;
  $("#cat-sub").innerHTML = [
    change === null ? "" : `<span class="${change > 0 ? "delta-up" : "delta-down"}">${change > 0 ? "▲" : "▼"} ${Math.abs(change)}%</span> vs ${esc(monthName(prevMonth(state.month)).split(" ")[0])}`,
    `${plural(d.count, "purchase")} at ${plural(d.places.length, "place")}`,
  ].filter(Boolean).join(" · ");
  $("#cat-places-title").textContent = key === "dining" ? "Restaurants compared" : "Places compared";
  $("#cat-places-note").textContent = d.places.length ? "Bar = share of this month" : "";
  const top = Math.max(1, ...d.places.map((p) => p.total));  // a place that only refunded has a negative total
  $("#cat-places").innerHTML = d.places.map((p, i) => {
    const diff = p.previous ? Math.round(((p.total - p.previous) / p.previous) * 100) : null;
    return `<li>
      <span class="rank">${i + 1}</span>${avatar(p.merchant, p.brand, color(key), "sm")}
      <span class="p-main"><div class="p-name">${esc(p.merchant)}</div>
        <div class="p-sub">${plural(p.visits, "visit")} · ${money(p.average)} each${diff === null ? " · new" : ` · <span class="${diff > 0 ? "up" : "down"}">${diff > 0 ? "▲" : "▼"} ${Math.abs(diff)}%</span>`}</div>
        <div class="p-track"><div class="p-fill" style="width:${Math.max(0, p.total / top) * 100}%;background:${color(key)}"></div></div></span>
      <span class="p-amt">${money(p.total)}<small>${d.total > 0 ? `${Math.round((p.total / d.total) * 100)}%` : ""}</small></span></li>`;
  }).join("") || `<li class="muted">Nothing in ${esc(catName(key).toLowerCase())} this month.</li>`;
  barChart($("#cat-trend"), d.trend.map((m) => ({
    label: monthName(m.month, "short"), value: Math.max(0, m.total), hi: m.month === state.month, tip: `<b>${money(m.total)}</b>${monthName(m.month)}`,
  })));
}

// ---------- trends ----------
async function loadTrends() {
  const months = state.trendMonths || 12;
  $$("#trend-range button").forEach((b) => b.classList.toggle("on", +b.dataset.months === months));
  state.trends = await api(`/api/trends?month=${state.month}&months=${months}`);
  renderTrends();
}

function renderTrends() {
  const t = state.trends;
  if (!t || !t.months.length) return;
  const labels = t.months.map((m) => monthName(m, "short"));
  const full = (i) => monthName(t.months[i]);
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const avgOut = sum(t.spent) / t.months.length, avgIn = sum(t.received) / t.months.length;
  const saved = sum(t.received) - sum(t.spent);
  $("#flow-stats").innerHTML = [
    ["Average spent", money(avgOut)],
    ["Average came in", avgIn ? money(avgIn) : "—"],
    [saved >= 0 ? "Saved in total" : "Overspent", `${money(Math.abs(saved))}${sum(t.received) ? ` <small class="muted">${Math.round((saved / sum(t.received)) * 100)}%</small>` : ""}`],
  ].map(([p, v]) => `<div><p>${p}</p><strong>${v}</strong></div>`).join("");
  lineChart($("#flow-chart"), labels,
    sum(t.received) ? [{ name: "Came in", values: t.received, cls: "income", dots: true }] : [],
    { bars: { name: "Spent", values: t.spent.map((v) => Math.max(0, v)) }, tipTitle: (i) => `${full(i)} · ${t.received[i] >= t.spent[i] ? `saved ${money(t.received[i] - t.spent[i])}` : `over by ${money(t.spent[i] - t.received[i])}`}` });

  const keys = Object.keys(t.categories).sort((a, b) => sum(t.categories[b]) - sum(t.categories[a]));
  if (!state.trendOn) state.trendOn = new Set(keys.filter((k) => k !== "other").slice(0, 5));
  $("#trend-chips").innerHTML = keys.map((k) =>
    `<button class="chip ${state.trendOn.has(k) ? "" : "off"}" data-cat="${esc(k)}" aria-pressed="${state.trendOn.has(k)}"><span class="dot" style="background:${color(k)}"></span>${esc(catName(k))}</button>`).join("");
  $$("#trend-chips .chip").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.cat;
    state.trendOn.has(k) ? state.trendOn.delete(k) : state.trendOn.add(k);
    renderTrends();
  }));
  lineChart($("#cat-chart"), labels,
    keys.map((k) => ({ name: catName(k), values: t.categories[k].map((v) => Math.max(0, v)), color: color(k), off: !state.trendOn.has(k) })),
    { tipTitle: full });

  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], top = Math.max(...t.weekday);
  barChart($("#weekday-chart"), t.weekday.map((v, i) => ({
    label: days[i], value: v, hi: v === top && v > 0, tip: `<b>${money(v)}</b>Average ${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i]}`,
  })));
}

// ---------- overview ----------
function renderHero(s) {
  const parts = nf2.formatToParts(s.spent);
  const at = parts.findIndex((p) => p.type === "decimal");
  const int = parts.slice(0, at).map((p) => p.value).join("");
  const dec = parts.slice(at).map((p) => p.value).join("");
  const ccy = `<span class="ccy ${ccyMode()}">${esc(s.currency)}</span>`;
  $("#hero-eyebrow").textContent = `Spent in ${monthName(s.month).split(" ")[0]}`;
  $("#hero-number").innerHTML = `${ccyMode() === "code" ? ccy : ""}${int}<span class="dec">${dec}</span>${ccyMode() === "after" ? ccy : ""}`;
  const out = [];
  if (s.previous_spent > 0) {
    const pct = Math.round(((s.spent - s.previous_spent) / s.previous_spent) * 100);
    const prev = monthName(prevMonth(s.month)).split(" ")[0];
    out.push(pct === 0 ? `Same as ${prev}` :
      `<span class="nowrap"><span class="${pct > 0 ? "delta-up" : "delta-down"}"><span aria-hidden="true">${pct > 0 ? "▲" : "▼"}</span> ${Math.abs(pct)}%</span> ${pct > 0 ? "more" : "less"} than ${prev}</span>`);
  }
  if (s.received > 0) {
    out.push(`<span class="nowrap">${money(s.received)} came in</span>`);
    if (s.received > s.spent) out.push(`<span class="nowrap delta-down">${money(s.received - s.spent)} saved</span>`);
  }
  $("#hero-sub").innerHTML = out.join(" · ") || "&nbsp;";
}

function renderSource() {
  const src = state.meta.source, el = $("#source");
  el.classList.toggle("demo", src.demo);
  el.textContent = src.demo ? "Example numbers · not real data"
    : src.emails ? `From your email · ${plural(src.emails, "bank alert")} · ${shortDate(src.first)} – ${shortDate(src.last)}` : "No emails yet";
  $("#leave-demo").hidden = state.meta.mode !== "demo";
}

function renderCategories(s) {
  // Refunds can leave a category below zero: it stays in the list but takes no share of the bar.
  const total = s.by_category.reduce((a, c) => a + Math.max(0, c.total), 0) || 1;
  $("#stackbar").innerHTML = s.by_category.filter((c) => c.total > 0).map((c) =>
    `<span style="flex-grow:${c.total};background:${color(c.category)}"></span>`).join("");
  $("#stackbar").setAttribute("aria-label", s.by_category.map((c) => `${catName(c.category)} ${money(c.total)}`).join(", ") || "No spending");
  $("#legend").innerHTML = s.by_category.map((c) => `
    <li><button class="lg" data-cat="${esc(c.category)}" aria-label="${esc(catName(c.category))}, ${money(c.total)}${c.total > 0 ? `, ${Math.round((c.total / total) * 100)}%` : ""}. Show transactions">
      <span class="dot" style="background:${color(c.category)}"></span>
      <span class="lg-name">${esc(catName(c.category))}</span>
      <span class="lg-val">${money(c.total)}<span class="lg-pct">${c.total > 0 ? `${Math.round((c.total / total) * 100)}%` : ""}</span></span>
    </button></li>`).join("") || `<li class="muted">Nothing spent this month.</li>`;
  $$("#legend .lg").forEach((b) => b.addEventListener("click", () => openCategory(b.dataset.cat)));
}

function renderStats(s) {
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const today = new Date();
  const isCurrent = today.getFullYear() === y && today.getMonth() + 1 === m;
  const lastDataDay = s.by_day.length ? +s.by_day[s.by_day.length - 1].day.slice(8) : 0;
  const elapsed = isCurrent ? Math.max(today.getDate(), lastDataDay) : days;
  const projecting = isCurrent && elapsed < days;
  const perDay = s.spent / elapsed;
  const biggest = s.by_day.reduce((a, b) => (b.total > (a?.total || 0) ? b : a), null);
  const tiles = [
    ["Daily average", money(perDay), `Over ${elapsed} days`],
    projecting
      ? ["On pace for", money(perDay * days), "By the end of the month"]
      : ["Biggest day", biggest ? money(biggest.total) : "—", biggest ? shortDate(biggest.day + "T00:00") : ""],
    ["Transactions", nf0.format(s.count), s.top_merchants.length ? `Most at ${esc(s.top_merchants[0].merchant)}` : ""],
    ["Biggest purchase", s.biggest ? money(s.biggest.amount_base) : "—", s.biggest ? esc(s.biggest.merchant) : ""],
  ];
  $("#stats").innerHTML = tiles.map(([p, v, sm]) => `<div class="stat"><p>${p}</p><strong>${v}</strong><small>${sm}</small></div>`).join("");

  const cb = $("#callout");
  cb.hidden = !s.uncategorized;
  if (s.uncategorized) $("#callout-text").textContent =
    `${plural(s.uncategorized, "transaction")} ${s.uncategorized === 1 ? "needs" : "need"} a category. Teach Ledger once and it remembers.`;
}

function renderPayLater(s) {
  const el = $("#paylater");
  const pl = (s.pay_later || [])[0];
  el.hidden = !pl;
  if (!pl) return;
  const orders = pl.open_orders.slice(0, 6), stores = pl.stores.slice(0, 6);
  el.innerHTML = `
    <div class="card-head"><h2>Pay later</h2><button class="link" id="pl-see">See ${esc(pl.provider)} payments</button></div>
    <div class="pl-top">
      <div><p>Paid with ${esc(pl.provider)} this month</p><strong>${money(pl.paid)}</strong>
        <small>${plural(pl.payments, "instalment")}, counted under the real store</small></div>
      <div><p>Still to pay</p><strong>${money(pl.owed)}</strong>
        <small>Across ${plural(pl.open_orders.length, "open order")} · estimated from ${esc(pl.provider)}’s emails</small></div>
    </div>
    <div class="pl-cols">
      <div><h3>This month by store</h3><ul class="pl-list">${stores.map((x) =>
        `<li><span>${esc(x.store)}</span><span class="amt">${money(x.total)}</span></li>`).join("") || `<li class="muted">No instalments this month.</li>`}</ul></div>
      <div><h3>Open orders</h3><ul class="pl-list">${orders.map((o) =>
        `<li><span>${esc(o.store || "Order")}<small>${o.next_due ? `Next payment ${esc(o.next_due)}` : o.instalments ? `${o.instalments} instalments` : ""}</small></span><span class="amt">${money(o.remaining)}</span></li>`).join("") || `<li class="muted">Nothing left to pay.</li>`}</ul></div>
    </div>`;
  $("#pl-see").addEventListener("click", () => { state.cat = `${VIA}${pl.provider}`; go("activity"); });
}

function renderDaily(s) {
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const map = Object.fromEntries(s.by_day.map((d) => [d.day, d.total]));
  const data = Array.from({ length: days }, (_, i) => {
    const day = `${s.month}-${String(i + 1).padStart(2, "0")}`;
    const v = map[day] || 0;
    return { label: String(i + 1), value: Math.max(0, v), tip: `<b>${money(v)}</b>${dayName(day)}` };
  });
  const active = data.filter((d) => d.value > 0).length;
  $("#daily-note").textContent = `${plural(active, "day")} with spending`;
  barChart($("#daily-chart"), data, { avg: s.spent / days, labelEvery: days > 20 ? 5 : 1 });
}

function renderTrend(s) {
  const all = state.meta.months;
  const idx = all.findIndex((x) => x.month === s.month);
  const slice = all.slice(Math.max(0, idx - 5), idx + 1);
  const data = slice.map((x) => ({
    label: monthName(x.month, "short"), value: Math.max(0, x.spent), hi: x.month === s.month, month: x.month,
    tip: `<b>${money(x.spent)}</b>${monthName(x.month)}`,
  }));
  barChart($("#trend-chart"), data, { onClick: (d) => setMonth(d.month) });
}

function renderHours(s) {
  const map = Object.fromEntries(s.by_hour.map((h) => [h.hour, h.total]));
  const label = (h) => (h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`);
  const data = Array.from({ length: 24 }, (_, h) => ({
    label: label(h), value: map[h] || 0, tip: `<b>${money(map[h] || 0)}</b>${label(h)}–${label((h + 1) % 24)}`,
  }));
  barChart($("#hour-chart"), data, { labelEvery: 3 });
}

// How much is left for the rest of the month: from what came in, and from the budgets set.
function renderLeft(s) {
  const el = $("#left-card");
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate(), today = new Date();
  const current = today.getFullYear() === y && today.getMonth() + 1 === m;
  const lastDay = s.by_day.length ? +s.by_day[s.by_day.length - 1].day.slice(8) : 0;
  const daysLeft = current ? Math.max(0, days - Math.max(today.getDate(), lastDay)) : 0;
  const spentBy = Object.fromEntries(s.by_category.map((c) => [c.category, c.total]));
  const budgeted = Object.entries(s.budgets || {});
  const budgetTotal = budgeted.reduce((a, [, v]) => a + v, 0);
  const budgetUsed = budgeted.reduce((a, [k]) => a + (spentBy[k] || 0), 0);
  const income = s.received || 0;
  if (!income && !budgetTotal) { el.hidden = true; return; }
  el.hidden = false;
  const aside = income ? s.moved || 0 : 0;  // money moved to your own savings isn't there to spend
  const base = income || budgetTotal, used = income ? s.spent : budgetUsed;
  const left = base - used - aside, share = Math.max(0, Math.min(1, left / base));
  const title = !current ? (left >= 0 ? `Left over in ${monthName(s.month).split(" ")[0]}` : `Over in ${monthName(s.month).split(" ")[0]}`)
    : "Left for the rest of the month";
  const perDay = current && daysLeft > 0 && left > 0 ? `About <b>${money(left / daysLeft)}</b> a day for the next ${plural(daysLeft, "day")}` :
    current && daysLeft === 0 ? "Last day of the month" : left < 0 ? "You spent more than came in" : "";
  el.innerHTML = `
    <div>
      <p class="eyebrow">${esc(title)}</p>
      <div class="left-big ${left < 0 ? "neg" : ""}">${left < 0 ? "−" : ""}${money(Math.abs(left))}</div>
      <p class="left-sub">${perDay}</p>
      <div class="left-meter" role="progressbar" aria-label="Share left" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(share * 100)}">
        <div class="${share < 0.1 ? "none" : share < 0.3 ? "low" : ""}" style="width:${share * 100}%"></div></div>
      <p class="left-sum">${income
        ? `${money(income)} came in − ${money(s.spent)} spent${aside ? ` − ${money(aside)} put aside` : ""} = <b>${left < 0 ? "−" : ""}${money(Math.abs(left))} left</b>`
        : `${money(budgetTotal)} budgeted − ${money(budgetUsed)} used = <b>${money(left)} left</b>`}</p>
    </div>
    <div class="left-side">
      ${income ? `<div><p>Came in</p><strong>${money(income)}</strong></div>` : ""}
      ${budgetTotal ? (budgetUsed > budgetTotal
        ? `<div><p>Budgets</p><strong class="delta-up">Over by ${money(budgetUsed - budgetTotal)}</strong><small>of ${money(budgetTotal)}</small></div>`
        : `<div><p>Budgets left</p><strong>${money(budgetTotal - budgetUsed)}</strong><small>of ${money(budgetTotal)}</small></div>`) : ""}
      ${income ? `<div><p>Saved this month</p><strong>${money(Math.max(0, income - s.spent))}</strong><small>${aside ? `${money(aside)} put aside + ${money(Math.max(0, left))} unspent` : "not spent yet"}</small></div>` : ""}
    </div>`;
}

function renderBudgets(s) {
  const spent = Object.fromEntries(s.by_category.map((c) => [c.category, c.total]));
  const keys = state.meta.categories.map((c) => c.key)
    .filter((k) => !["income"].includes(k) && (spent[k] || s.budgets[k]));
  $("#budgets").innerHTML = keys.map((k) => {
    const used = spent[k] || 0, limit = s.budgets[k];
    const pct = limit ? Math.max(0, Math.min(100, (used / limit) * 100)) : 0;
    const over = limit && used > limit;
    return `<li>
      <div class="b-row">
        <span class="dot" style="background:${color(k)}"></span>
        <span class="b-name">${esc(catName(k))}${over ? `<span class="b-status">Over by ${money(used - limit)}</span>` : limit ? `<span class="b-left">${money(limit - used)} left</span>` : ""}</span>
        <span class="b-amt">${money(used)}</span>
        <button class="b-limit ${limit ? "" : "unset"}" data-cat="${k}" aria-label="${limit ? `Change ${esc(catName(k))} limit, now ${nf0.format(limit)}` : `Set a limit for ${esc(catName(k))}`}">${limit ? `of ${nf0.format(limit)}` : "Set limit"}</button>
      </div>
      ${limit ? `<div class="b-track" role="progressbar" aria-label="${esc(catName(k))} budget used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(pct)}"><div class="b-fill ${over ? "over" : ""}" style="width:${pct}%"></div></div>` : ""}
    </li>`;
  }).join("") || `<li class="muted">No spending this month.</li>`;
  $$(".b-limit").forEach((b) => b.addEventListener("click", () => editBudget(b, s.budgets[b.dataset.cat])));
}

function editBudget(btn, current) {
  const input = document.createElement("input");
  input.type = "text"; input.inputMode = "decimal"; input.value = current || "";
  input.placeholder = "Limit"; input.className = "b-input";
  input.setAttribute("aria-label", "Monthly limit");
  btn.replaceWith(input); input.focus();
  const commit = async () => {
    const v = parseFloat(input.value.replace(/[^\d.]/g, ""));
    await api(`/api/budgets/${btn.dataset.cat}`, { method: "PUT", body: JSON.stringify({ monthly: isNaN(v) ? null : v }) });
    await loadMonth();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); if (e.key === "Escape") { input.value = current || ""; input.blur(); } });
  input.addEventListener("blur", commit, { once: true });
}

function renderMerchants(s) {
  $("#merchants").innerHTML = s.top_merchants.map((m) => `
    <li>${avatar(m.merchant, m.brand, color(m.category), "sm")}
      <span class="m-name">${esc(m.merchant)}<small>${esc(catName(m.category))} · ${m.count} time${m.count > 1 ? "s" : ""}</small></span>
      <span class="m-amt">${money(m.total)}</span></li>`).join("") || `<li class="muted">No merchants this month.</li>`;
}

// ---------- activity ----------
function renderChips() {
  const chips = [{ key: null, name: "All" }, { key: "other", name: "Needs review", color: "gray" },
    ...(state.meta.pay_later || []).map((p) => ({ key: `${VIA}${p}`, name: `Paid with ${p}`, color: "gray" })),
    ...state.meta.categories.filter((c) => c.key !== "other").map((c) => ({ ...c, name: catName(c.key) })),
    { key: INTERNAL, name: "Between my accounts", color: "gray" },
    { key: SETTLED, name: "Settled", color: "gray" }, { key: HIDDEN, name: "Show hidden", color: "gray" }];
  $("#chips").innerHTML = chips.map((c) =>
    `<button class="chip ${state.cat === c.key ? "on" : ""}" aria-pressed="${state.cat === c.key}" data-cat="${c.key ?? ""}">${c.key ? `<span class="dot" style="background:var(--c-${c.color})"></span>` : ""}${esc(c.name)}</button>`).join("");
  $$(".chip").forEach((b) => b.addEventListener("click", () => { state.cat = b.dataset.cat || null; loadActivity(); }));
  $(".chip.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function activityEmpty() {
  if (!state.meta.months.length) return ["No transactions yet", "Add your bank alerts in Settings and they’ll show up here."];
  const month = monthName(state.month).split(" ")[0];
  if (state.q) return [`No results for “${state.q}”`, `Nothing in ${month} matches. Try another month or a shorter search.`];
  if (state.cat === "other") return ["All caught up", `Every transaction in ${month} has a category.`];
  if (state.cat === INTERNAL) return ["No moves between your accounts", `Transfers between your own accounts in ${month} would appear here.`];
  if (state.cat === SETTLED) return ["Nothing settled", `Money you sent someone and got back from them within 45 days would appear here, left out of your totals.`];
  if (state.cat === HIDDEN) return ["Nothing hidden", `Transactions you mark as “didn’t happen” in ${month} would appear here, left out of your totals.`];
  if (state.cat?.startsWith(VIA)) return ["No pay-later payments", `Nothing was paid with ${state.cat.slice(VIA.length)} in ${month}.`];
  if (state.cat) return [`No ${catName(state.cat).toLowerCase()} in ${month}`, "Pick another category or month."];
  return [`Nothing in ${month}`, "Pick another month."];
}

function renderActivity() {
  renderChips();
  const groups = new Map();
  for (const t of state.txs) {
    const d = t.occurred_at.slice(0, 10);
    if (!groups.has(d)) groups.set(d, []);
    groups.get(d).push(t);
  }
  let html = "";
  for (const [day, list] of groups) {
    const net = list.reduce((a, t) => a + (t.spend || 0), 0);  // what the day cost, refunds taken off
    html += `<li class="tx-day"><span>${dayName(day)}</span><span>${net ? `${net < 0 ? "−" : ""}${money(Math.abs(net))}` : ""}</span></li>`;
    for (const t of list) {
      const refund = t.extra?.refund, settled = !!t.extra?.settled, gone = !!t.hidden;
      const sign = t.direction === "in" ? "+" : t.direction === "internal" ? "" : "−";
      const fx = t.currency !== state.meta.currency ? `<small>${esc(t.currency)} ${nf2.format(t.amount)}</small>` : "";
      const tag = t.category_source === "learned" ? ` · <span class="learned">Learned</span>` : t.category_source === "manual" ? ` · <span class="learned">Edited</span>` : "";
      const status = gone ? "Didn’t happen" : settled ? "Settled" : refund ? "Refund" : t.extra?.refunded_by ? "Refunded" : t.extra?.payback ? "Paid back" : "";
      const sub = (t.direction === "internal" ? "Between your accounts" : catName(t.category)) + (t.extra?.via ? ` · via ${t.extra.via}` : "");
      const fallback = t.direction === "internal" ? "var(--c-gray)" : color(t.category);
      const verb = sign === "−" ? "spent" : refund ? "refunded" : sign === "+" ? "received" : "moved";
      const label = `${t.merchant}, ${verb} ${money(t.amount_base, true)}, ${status ? `${status}, ` : ""}${sub}, ${timeOf(t.occurred_at)}`;
      html += `<li class="tx ${gone ? "gone" : settled ? "settled" : ""}" data-id="${t.id}" tabindex="0" role="button" aria-label="${esc(label)}">
        ${avatar(t.merchant, t.brand, fallback)}
        <span class="tx-main"><span class="tx-name">${esc(t.merchant)}${status ? ` <span class="tx-badge ${refund || t.extra?.refunded_by ? "refund" : ""}">${status}</span>` : ""}</span><span class="tx-sub">${esc(sub)} · ${timeOf(t.occurred_at)}${tag}${t.note ? ` · ${esc(t.note)}` : ""}</span></span>
        <span class="tx-amt ${t.direction}">${sign}${nf2.format(t.amount_base)}${fx}</span>
      </li>`;
    }
  }
  $("#tx-list").innerHTML = html;
  const empty = $("#tx-empty");
  empty.hidden = state.txs.length > 0;
  if (!state.txs.length) { const [h, p] = activityEmpty(); empty.innerHTML = `<strong>${esc(h)}</strong><span>${esc(p)}</span>`; }
  $$(".tx").forEach((li) => {
    const open = () => openSheet(state.txs.find((t) => t.id === li.dataset.id), li);
    li.addEventListener("click", open);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });
}

// ---------- sheet ----------
function openSheet(t, from) {
  state.editing = { t, category: t.category, direction: t.direction, from };
  $("#sheet-date").textContent = `${dayName(t.occurred_at.slice(0, 10))} · ${timeOf(t.occurred_at)}`;
  $("#sheet-title").textContent = t.merchant;
  $("#sheet-amount").textContent = money(t.amount_base, true);
  $("#sheet-merchant").textContent = t.merchant;
  $("#sheet-note").value = t.note || "";
  $("#sheet-name").value = t.merchant;
  $("#sheet-name").placeholder = t.extra?.original_merchant || t.merchant_raw;
  $("#sheet-hidden").checked = !!t.hidden;
  $("#sheet-remember").checked = true;
  $("#sheet-match-amount").checked = false;
  $("#sheet-amount-match").textContent = `${t.currency} ${nf2.format(t.amount)}`;
  $("#sheet-amount-row").hidden = false;
  const meta = [["From email", t.merchant_raw], ["Account", t.account ? `•••• ${t.account}` : "—"], ["Bank", t.bank]];
  if (t.currency !== state.meta.currency) meta.push(["Charged", `${t.currency} ${nf2.format(t.amount)}`]);
  if (t.extra?.via) meta.push(["Paid with", t.extra.order ? `${t.extra.via} · order ${t.extra.order}` : t.extra.via]);
  if (t.extra?.refund) meta.push(["Refund", t.extra.refund_of ? "Taken off the purchase it undoes" : "No earlier purchase found; taken off this merchant’s spending"]);
  if (t.extra?.refunded_by) meta.push(["Refunded", "A later refund is taken off this purchase"]);
  if (t.extra?.settled) meta.push(["Settled", "Cancelled out by a matching transfer; not counted"]);
  if (t.extra?.payback) meta.push(["Paid back", "Taken off what you sent this person"]);
  $("#sheet-meta").innerHTML = meta.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
  renderSheetCats();
  $("#new-cat").hidden = true;
  syncSheet();
  $("#scrim").hidden = $("#sheet").hidden = false;
  ($(`#sheet-cats [data-cat="${t.category}"]`) || $("#sheet-cats button"))?.focus({ preventScroll: true });
}

const COLORS = ["blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red", "brown", "teal", "cyan", "navy", "plum", "olive", "slate", "forest", "tan", "gray"];

function renderSheetCats() {
  $("#sheet-cats").innerHTML = state.meta.categories.map((c) =>
    `<button role="radio" data-cat="${c.key}"><span class="dot" style="background:var(--c-${c.color})"></span>${esc(catName(c.key))}</button>`).join("") +
    `<button class="add" data-add="1">＋ New category</button>`;
  if (state.editing) syncSheet();
}

function openNewCategory() {
  const f = $("#new-cat");
  f.hidden = false;
  $("#new-cat-name").value = "";
  state.newColor = state.newColor || "aqua";
  $("#new-cat-colors").innerHTML = COLORS.map((c) =>
    `<button type="button" role="radio" data-color="${c}" aria-label="${c}" aria-checked="${c === state.newColor}" class="${c === state.newColor ? "on" : ""}" style="background:var(--c-${c})"></button>`).join("");
  $("#new-cat-name").focus();
}

async function createCategory() {
  const name = $("#new-cat-name").value.trim();
  if (!name) return $("#new-cat-name").focus();
  try {
    const c = await api("/api/categories", { method: "POST", body: JSON.stringify({ name, color: state.newColor }) });
    state.meta = await api("/api/meta");
    state.editing.category = c.key;
    $("#new-cat").hidden = true;
    renderSheetCats();
    toast(`Added ${c.name}`);
  } catch (e) { toast(e.message); }
}

function syncSheet() {
  const e = state.editing;
  $$("#sheet-direction button").forEach((b) => { b.classList.toggle("on", b.dataset.dir === e.direction); b.setAttribute("aria-checked", b.dataset.dir === e.direction); });
  $$("#sheet-cats button[data-cat]").forEach((b) => { b.classList.toggle("on", b.dataset.cat === e.category); b.setAttribute("aria-checked", b.dataset.cat === e.category); });
}

function closeSheet() {
  const from = state.editing?.from;
  $("#scrim").hidden = $("#sheet").hidden = true; state.editing = null;
  if (from?.isConnected) from.focus({ preventScroll: true });
}

async function saveSheet() {
  const { t, category, direction } = state.editing;
  const remember = $("#sheet-remember").checked;
  const matchAmount = remember && $("#sheet-match-amount").checked;
  const note = $("#sheet-note").value.trim();
  const name = $("#sheet-name").value.trim(), hidden = $("#sheet-hidden").checked;
  const body = { remember, match_amount: matchAmount };
  if (name !== t.merchant) body.name = name === (t.extra?.original_merchant ?? t.merchant) ? "" : name;
  if (hidden !== !!t.hidden) body.hidden = hidden;
  if (category !== t.category) body.category = category;
  if (direction !== t.direction) body.direction = direction;
  if (note !== (t.note || "")) body.note = note;
  if (Object.keys(body).length === 2) return closeSheet();
  await api(`/api/transactions/${t.id}`, { method: "PATCH", body: JSON.stringify(body) });
  closeSheet();
  const what = direction === "internal" ? "a transfer between your accounts" : catName(category);
  const at = matchAmount ? ` at ${t.currency} ${nf2.format(t.amount)}` : "";
  toast("hidden" in body ? (hidden ? "Left out of your totals" : "Back in your totals")
    : remember && (body.category || body.direction) ? `Got it. ${t.merchant}${at} will always be ${what}.`
    : remember && body.name ? `Renamed everywhere to ${body.name}` : "Saved");
  state.meta = await api("/api/meta");
  await Promise.all([loadMonth(), state.view === "activity" ? loadActivity() : null]);
}

// ---------- rules ----------
function renderCustomCats() {
  const mine = state.meta.categories.filter((c) => c.custom);
  $("#cat-section").hidden = !mine.length;
  $("#cat-list").innerHTML = mine.map((c) => `
    <li class="rule">
      <span class="rule-name"><span class="dot inline" style="background:var(--c-${c.color})"></span>${esc(c.name)}</span>
      <span></span>
      <button class="btn-del" data-cat="${esc(c.key)}" aria-label="Delete category ${esc(c.name)}">Delete</button>
    </li>`).join("");
  $$("#cat-list .btn-del").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/categories/${encodeURIComponent(b.dataset.cat)}`, { method: "DELETE" });
    state.meta = await api("/api/meta");
    toast("Category deleted"); renderCustomCats(); loadRules(); loadMonth();
  }));
}

async function loadRules() {
  renderCustomCats();
  const rules = await api("/api/rules");
  $("#rule-empty").hidden = rules.length > 0;
  const dirName = { out: "Spending", in: "Income", internal: "Between my accounts" };
  $("#rule-list").innerHTML = rules.map((r) => `
    <li class="rule">
      <span class="rule-name">${esc(r.merchant || r.merchant_key)}${r.amount ? ` <span class="muted">at ${nf2.format(r.amount)}</span>` : ""}<small>Learned ${shortDate(r.created_at)}</small></span>
      <span class="pill">${r.category ? `<span class="dot" style="background:${color(r.category)}"></span>${esc(catName(r.category))}` : ""}${r.direction ? `${r.category ? " · " : ""}${dirName[r.direction]}` : ""}</span>
      <button class="btn-del" data-key="${esc(r.merchant_key)}" data-amount="${r.amount || 0}" aria-label="Forget rule for ${esc(r.merchant || r.merchant_key)}">Forget</button>
    </li>`).join("");
  $$("#rule-list .btn-del").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/rules/${encodeURIComponent(b.dataset.key)}?amount=${b.dataset.amount}`, { method: "DELETE" });
    toast("Rule removed"); loadRules(); loadMonth();
  }));
}

// ---------- settings ----------
function applyTheme(pref) {
  const forced = new URLSearchParams(location.search).get("theme");
  const t = forced || pref;
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("ledger-theme", pref); } catch { /* private mode */ }
}

function applyPrefs() {
  const p = state.meta.settings;
  applyTheme(p.theme);
  setNumberFormat(p.number);
}

const ago = (iso) => {
  if (!iso) return "";
  const days = Math.round((Date.now() - new Date(iso)) / 864e5);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : days < 30 ? `${days} days ago` : shortDate(iso);
};

function gmailSummary(g) {
  if (g.sync.state === "running") return g.sync.message || "Syncing…";
  if (g.sync.state === "error") return `Couldn’t sync: ${g.sync.message}`;
  if (g.connected) return `Connected, read-only${g.last_email ? ` · newest alert ${ago(g.last_email)}` : ""}`;
  if (g.credentials) return "Ready to connect";
  return "Not connected";
}

async function loadSettings() {
  const s = state.settings = await api("/api/settings");
  const g = s.gmail;
  $("#gmail-status").textContent = gmailSummary(g);
  $("#gmail-status").classList.toggle("bad", g.sync.state === "error");
  const gb = $("#gmail-btn");
  gb.textContent = !g.credentials ? "Set up…" : g.connected ? "Sync now" : "Connect";
  gb.disabled = g.sync.state === "running";
  gb.classList.toggle("busy", g.sync.state === "running");
  const chosen = s.banks.length ? s.banks : s.banks_available;
  $("#banks-status").textContent = chosen.length ? `${chosen.join(", ")}${s.pay_later.length ? ` · plus ${s.pay_later.join(", ")} for pay later` : ""}` : "None yet";
  const demoDir = s.demo_dir && !s.demo;
  $("#demo-title").textContent = s.demo ? "You’re exploring the demo" : demoDir ? "This folder holds example data" : "Try the demo";
  $("#demo-sub").textContent = s.demo ? "Example numbers, kept apart from your own ledger." :
    demoDir ? "It was created with “inbox_ledger demo”. Point INBOX_LEDGER_DATA at another folder for your own data." :
    "Six months of made-up spending to explore. Your own data isn’t touched.";
  $("#demo-btn").textContent = s.demo ? "Leave demo" : "Open demo";
  $("#demo-btn").hidden = demoDir;
  $$("#theme-seg button").forEach((b) => { const on = b.dataset.themeOpt === s.theme; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  $("#currency-sel").value = s.currency;
  const sample = nf0.format(1234);
  $("#currency-sel").options[0].textContent = `${state.meta.currency} ${sample}`;
  $("#currency-sel").options[1].textContent = `${sample} ${state.meta.currency}`;
  $("#currency-sel").options[2].textContent = `${sample} (no currency)`;
  $("#number-sel").value = s.number;
  $("#logos-toggle").checked = s.logos_enabled;
  $("#logos-foot").textContent = s.logos_key === "demo_logos"
    ? "In the demo, logos are on: they’re fetched from each brand’s own website, and the shops are made up."
    : "Shows each shop’s icon, downloaded once from that brand’s own website and kept on this computer. Off by default, because fetching an icon tells that website someone here shops there. Turning it off deletes downloaded icons.";
  $("#data-path").textContent = s.data_dir;
  $("#version").textContent = `Version ${s.version} · Open source, MIT licence`;
  if (g.sync.state === "running") pollSync(() => loadSettings());
}

async function savePref(changes) {
  try {
    await api("/api/settings", { method: "PATCH", body: JSON.stringify(changes) });
    state.meta = await api("/api/meta");
    applyPrefs();
    await loadSettings();
    if (state.summary) await loadMonth();
  } catch (e) { toast(e.message); }
}

function chooseFile(input) {
  return new Promise((resolve) => {
    input.value = "";
    input.onchange = () => resolve(input.files[0] || null);
    input.click();
  });
}

// Upload with progress (fetch can't report upload progress).
function upload(url, file, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let body = {};
      try { body = JSON.parse(x.responseText); } catch { /* not JSON */ }
      x.status < 300 ? resolve(body) : reject(new Error(body.detail || `Upload failed (${x.status})`));
    };
    x.onerror = () => reject(new Error("Couldn’t reach Ledger. Is it still running?"));
    x.send(file);
  });
}

const importFile = (file, onProgress) => upload(`/api/import?filename=${encodeURIComponent(file.name)}`, file, onProgress);

async function startSync() {
  await api("/api/sync", { method: "POST" });
}

function pollSync(onUpdate) {
  clearTimeout(pollSync.timer);
  return new Promise((resolve) => {
    const tick = async () => {
      const s = await api("/api/sync").catch(() => ({ state: "error", message: "Lost connection to Ledger" }));
      onUpdate(s);
      if (s.state === "running") pollSync.timer = setTimeout(tick, 1000);
      else resolve(s);
    };
    tick();
  });
}

async function settingsImport() {
  const file = await chooseFile($("#file-input"));
  if (!file) return;
  const st = $("#import-status"), btn = $("#import-btn");
  btn.disabled = true;
  try {
    const r = await importFile(file, (p) => (st.textContent = `Uploading ${file.name}… ${Math.round(p * 100)}%`));
    toast(`Imported ${plural(r.added, "new email")} · ${plural(r.transactions, "transaction")} in total`);
    await refreshAll();
  } catch (e) { toast(e.message); }
  st.textContent = "A .mbox from Google Takeout, or a .jsonl of emails";
  btn.disabled = false;
}

async function settingsGmail() {
  const g = state.settings.gmail;
  if (!g.credentials) return openOnboarding(2, { gmail: true });
  try {
    await startSync();
    $("#gmail-btn").disabled = true;
    const s = await pollSync((s) => { $("#gmail-status").textContent = s.message || "Syncing…"; });
    if (s.state === "done") toast(`Synced · ${s.message}`);
    await refreshAll();
  } catch (e) { toast(e.message); loadSettings(); }
}

async function enterDemo() {
  await api("/api/demo", { method: "POST" });
  await refreshAll();
}

async function leaveDemo() {
  await api("/api/demo", { method: "DELETE" });
  toast("Left the demo");
  await refreshAll();
}

async function refreshAll() {
  state.meta = await api("/api/meta");
  state.noLogo.clear();
  applyPrefs();
  const months = state.meta.months.map((m) => m.month);
  if (!months.includes(state.month)) state.month = state.meta.current;
  await loadMonth();
  if (state.view === "activity") await loadActivity();
  if (state.view === "rules") await loadRules();
  if (state.view === "settings") await loadSettings();
}

// ---------- welcome / setup ----------
const ob = { step: 0, banks: new Set(), gmail: false, missing: false, result: null, busy: false, closable: true };
const OB_STEPS = 4;

function openOnboarding(step = 0, opts = {}) {
  ob.step = step; ob.shown = -1; ob.gmail = !!opts.gmail; ob.only = !!opts.only; ob.missing = false; ob.result = null; ob.error = "";
  ob.banks = new Set(state.meta.settings.banks);
  ob.firstRun = !state.meta.source.emails && !state.meta.settings.onboarded;
  $("#onboarding").hidden = false;
  document.body.classList.add("locked");
  renderOnboarding();
  api("/api/settings").then((s) => { state.settings = s; if (ob.step === 2) renderOnboarding(); }).catch(() => {});
}

async function closeOnboarding(markDone = true) {
  $("#onboarding").hidden = true;
  ob.only = false;
  document.body.classList.remove("locked");
  if (markDone && !state.meta.settings.onboarded) {
    await api("/api/settings", { method: "PATCH", body: JSON.stringify({ onboarded: true }) }).catch(() => {});
  }
  await refreshAll();
}

function bankTile(b) {
  const on = ob.banks.has(b.name);
  return `<button class="bank-tile ${on ? "on" : ""}" role="checkbox" aria-checked="${on}" data-bank="${esc(b.name)}">
    <span class="bank-mark">${esc(initials(b.name))}</span>
    <span class="bank-name">${esc(b.name)}</span>
    <span class="bank-sub">${esc(b.country || (b.gmail ? "Email alerts" : "Built in"))}</span>
    <span class="tick" aria-hidden="true">${icon("check")}</span>
  </button>`;
}

function stepWelcome() {
  return `
    <div class="ob-step">
      <img class="ob-app" src="icon.svg" alt="" width="88" height="88">
      <h1 id="ob-title">Welcome to Ledger</h1>
      <p class="ob-lead">Your bank already emails you about every payment. Ledger turns those emails into a clear monthly budget.</p>
      <ul class="features">
        <li><span class="f-icon" style="color:var(--c-blue)">${icon("envelope")}</span><div><strong>Reads your bank alerts</strong><span>Card payments, transfers and income, from the emails your bank already sends.</span></div></li>
        <li><span class="f-icon" style="color:var(--c-orange)">${icon("wand")}</span><div><strong>Learns from one correction</strong><span>Change a merchant’s category once and Ledger remembers it, past and future.</span></div></li>
        <li><span class="f-icon" style="color:var(--good)">${icon("lock")}</span><div><strong>Private by design</strong><span>Everything stays on this computer. No account, no cloud, no tracking.</span></div></li>
      </ul>
      <div class="ob-actions"><button class="btn primary large" data-ob="next">Continue</button></div>
    </div>`;
}

function stepBanks() {
  const banks = state.meta.bank_profiles || [];
  return `
    <div class="ob-step">
      <span class="ob-glyph" style="--tint:var(--c-green)">${icon("bank")}</span>
      <h1 id="ob-title">Which bank do you use?</h1>
      <p class="ob-lead">Ledger reads the alert emails your bank sends. Choose every bank you get alerts from.</p>
      <div class="bank-grid">
        ${banks.map(bankTile).join("")}
        <button class="bank-tile other ${ob.missing ? "on" : ""}" aria-expanded="${ob.missing}" data-missing="1">
          <span class="bank-mark">${icon("question")}</span>
          <span class="bank-name">My bank isn’t here</span>
          <span class="bank-sub">See your options</span>
        </button>
      </div>
      <div class="missing" ${ob.missing ? "" : "hidden"}>
        <p class="missing-lead">You can still use Ledger. There are three ways in:</p>
        <ul class="missing-list">
          <li><span class="f-icon sm" style="color:var(--c-blue)">${icon("envelope")}</span><div><strong>Try it anyway</strong><span>Ledger’s generic reader understands many alert emails: the amount, the merchant and the date. Import a few and see what it finds.</span></div></li>
          <li><span class="f-icon sm" style="color:var(--c-orange)">${icon("sparkle")}</span><div><strong>Bring your own Claude</strong><span>Add your own Anthropic API key and Claude reads the emails Ledger doesn’t recognise. Those emails go to Anthropic under your key, and nowhere else.</span></div></li>
          <li><span class="f-icon sm" style="color:var(--c-violet)">${icon("code")}</span><div><strong>Help add your bank</strong><span>Share one alert email with personal details removed, or write a short YAML profile. No code needed. <a href="${REPO}/issues/new?title=${encodeURIComponent("Bank request: ")}" target="_blank" rel="noopener">Request your bank</a></span></div></li>
        </ul>
      </div>
      <div class="ob-actions">
        <button class="btn primary large" data-ob="next" ${ob.banks.size || ob.missing || ob.only ? "" : "disabled"}>${ob.only ? "Done" : "Continue"}</button>
        ${ob.banks.size || ob.missing || ob.only ? "" : `<button class="link" data-ob="next">Skip for now</button>`}
      </div>
    </div>`;
}

function stepSource() {
  const s = state.settings || {};
  const g = s.gmail || {};
  const gmailPanel = !ob.gmail ? "" : `
    <div class="panel" id="gmail-panel">
      ${g.credentials ? `
        <p><strong>${g.connected ? "Gmail is connected." : "Your Google client file is ready."}</strong> ${g.connected ? "Ledger will fetch alerts newer than the last one it saw." : "Next, Google asks you to allow read-only access in a new browser tab."}</p>
        <div class="panel-actions"><button class="btn primary" data-ob="sync">${g.connected ? "Sync now" : "Connect Gmail"}</button></div>` : `
        <p>Ledger talks to Gmail through your own Google Cloud app, so nobody else sits in the middle. Setup takes about three minutes:</p>
        <ol class="steps">
          <li>In Google Cloud Console, create a project and enable the <strong>Gmail API</strong>.</li>
          <li>Set up the OAuth consent screen as <strong>External</strong> and add yourself as a test user.</li>
          <li>Create an OAuth client ID of type <strong>Desktop app</strong>, then download its JSON file.</li>
        </ol>
        <div class="panel-actions">
          <a class="btn secondary" href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Open Google Cloud</a>
          <button class="btn primary" data-ob="cred">Choose JSON file…</button>
        </div>`}
      <div class="progress" id="ob-progress" hidden><span class="spinner" aria-hidden="true"></span><span id="ob-progress-text"></span></div>
      <p class="error" id="ob-error" role="alert" ${ob.error ? "" : "hidden"}>${esc(ob.error)}</p>
    </div>`;
  return `
    <div class="ob-step">
      <span class="ob-glyph" style="--tint:var(--c-blue)">${icon("tray")}</span>
      <h1 id="ob-title">Bring in your transactions</h1>
      <p class="ob-lead">Choose how Ledger gets your bank alerts. You can add more later in Settings.</p>
      <div class="group options">
        <button class="row option ${ob.gmail ? "open" : ""}" data-ob="gmail" aria-expanded="${ob.gmail}">
          <span class="row-icon" style="--tint:var(--c-red)">${icon("mail")}</span>
          <span class="row-main"><span class="row-title">Connect Gmail</span><span class="row-sub">Read-only. Ledger only searches for your bank’s alerts.</span></span>
          ${icon("chevron", "chev")}
        </button>
        ${gmailPanel}
        <button class="row option" data-ob="import">
          <span class="row-icon" style="--tint:var(--c-blue)">${icon("tray")}</span>
          <span class="row-main"><span class="row-title">Import a file</span><span class="row-sub">A .mbox from Google Takeout, or a .jsonl of emails.</span></span>
          ${icon("chevron", "chev")}
        </button>
        <button class="row option" data-ob="demo">
          <span class="row-icon" style="--tint:var(--c-yellow)">${icon("play")}</span>
          <span class="row-main"><span class="row-title">Try the demo</span><span class="row-sub">Six months of made-up spending, kept apart from your own data.</span></span>
          ${icon("chevron", "chev")}
        </button>
      </div>
      ${!ob.gmail ? `<div class="progress" id="ob-progress" hidden><span class="spinner" aria-hidden="true"></span><span id="ob-progress-text"></span></div>
      <p class="error" id="ob-error" role="alert" ${ob.error ? "" : "hidden"}>${esc(ob.error)}</p>` : ""}
      <p class="ob-note">${icon("lock", "inline")} Emails are stored only in your data folder on this computer.</p>
    </div>`;
}

function stepDone() {
  const r = ob.result || {};
  const demo = r.kind === "demo";
  const facts = demo ? "Six months of example spending, with budgets and a few merchants left for you to teach."
    : r.transactions != null ? `Ledger read ${plural(r.messages ?? r.read ?? 0, "email")} and found ${plural(r.transactions, "transaction")}.${r.unparsed ? ` ${plural(r.unparsed, "email")} didn’t look like bank alerts.` : ""}`
    : "Your ledger is ready.";
  const tips = demo ? [
    ["play", "var(--c-yellow)", "Everything here is example data", "Leave the demo anytime from the banner on Overview or from Settings."],
    ["wand", "var(--c-orange)", "Try teaching it", "Open a transaction under “Needs review” and pick a category."],
  ] : [
    ["wand", "var(--c-orange)", "Fix a category once", "Open any transaction and choose a category. Ledger remembers it for that merchant."],
    ["sparkle", "var(--c-violet)", "Set a few budgets", "Select “Set limit” next to a category on Overview."],
  ];
  return `
    <div class="ob-step">
      <span class="ob-done" aria-hidden="true">${icon("check")}</span>
      <h1 id="ob-title">${demo ? "The demo is ready" : "You’re all set"}</h1>
      <p class="ob-lead">${esc(facts)}</p>
      <ul class="features">${tips.map(([i, c, t, s]) => `<li><span class="f-icon" style="color:${c}">${icon(i)}</span><div><strong>${t}</strong><span>${s}</span></div></li>`).join("")}</ul>
      <div class="ob-actions"><button class="btn primary large" data-ob="finish">Open Ledger</button></div>
    </div>`;
}

function renderOnboarding() {
  const steps = [stepWelcome, stepBanks, stepSource, stepDone];
  $("#ob-body").innerHTML = steps[ob.step]();
  $(".ob-step").classList.toggle("enter", ob.shown !== ob.step);  // animate only when the step changes
  const moved = ob.shown !== ob.step;
  ob.shown = ob.step;
  $$("#ob-dots span").forEach((d, i) => d.classList.toggle("on", i === ob.step));
  $("#ob-back").style.visibility = ob.step > 0 && ob.step < OB_STEPS - 1 && !ob.only ? "visible" : "hidden";
  $("#ob-dots").style.visibility = ob.only ? "hidden" : "visible";
  $("#ob-close").textContent = ob.firstRun ? "Set up later" : "Close";
  $("#ob-close").style.visibility = ob.step < OB_STEPS - 1 ? "visible" : "hidden";
  $("#onboarding").scrollTop = 0;
  // Move focus to the new step's title so screen readers announce it.
  $("#ob-title").setAttribute("tabindex", "-1");
  if (moved) $("#ob-title").focus({ preventScroll: true });
}

function obProgress(text) {
  const p = $("#ob-progress"), e = $("#ob-error");
  if (e) e.hidden = true;
  if (!p) return;
  p.hidden = !text;
  $("#ob-progress-text").textContent = text || "";
}

function obError(msg) {
  ob.error = msg;
  obProgress("");
  const e = $("#ob-error");
  if (e) { e.textContent = msg; e.hidden = false; }
  ob.busy = false;
}

async function obAction(kind, el) {
  if (ob.busy && kind !== "bank") return;
  if (kind === "next") {
    if (ob.step === 1) await api("/api/settings", { method: "PATCH", body: JSON.stringify({ banks: [...ob.banks] }) }).catch(() => {});
    if (ob.step === 1) state.settings = await api("/api/settings");
    if (ob.only) return closeOnboarding(false);
    ob.step++; ob.error = ""; return renderOnboarding();
  }
  if (kind === "back") { ob.step--; ob.error = ""; return renderOnboarding(); }
  if (kind === "finish") return closeOnboarding(true);
  if (kind === "bank") {
    const name = el.dataset.bank;
    ob.banks.has(name) ? ob.banks.delete(name) : ob.banks.add(name);
    renderOnboarding();
    return $(`#ob-body [data-bank="${CSS.escape(name)}"]`)?.focus();
  }
  if (kind === "missing") { ob.missing = !ob.missing; renderOnboarding(); return $("#ob-body [data-missing]")?.focus(); }
  if (kind === "gmail") {
    ob.gmail = !ob.gmail; ob.error = "";
    state.settings = await api("/api/settings");
    renderOnboarding();
    return $("#ob-body [data-ob=gmail]")?.focus();
  }
  if (kind === "cred") {
    const file = await chooseFile($("#cred-input"));
    if (!file) return;
    try {
      await upload("/api/gmail/credentials", file);
      state.settings = await api("/api/settings");
      ob.error = ""; renderOnboarding();
      toast("Google client file added");
    } catch (e) { obError(e.message); }
    return;
  }
  if (kind === "sync") {
    ob.busy = true;
    try {
      await startSync();
      const s = await pollSync((s) => obProgress(s.message || "Syncing…"));
      if (s.state !== "done") return obError(`Couldn’t sync: ${s.message}`);
      ob.result = { kind: "gmail", ...s.result }; ob.busy = false;
      ob.step = 3; return renderOnboarding();
    } catch (e) { return obError(e.message); }
  }
  if (kind === "import") {
    const file = await chooseFile($("#file-input"));
    if (!file) return;
    ob.busy = true;
    try {
      obProgress(`Uploading ${file.name}…`);
      const r = await importFile(file, (p) => obProgress(p < 1 ? `Uploading ${file.name}… ${Math.round(p * 100)}%` : "Reading emails…"));
      ob.result = { kind: "import", ...r }; ob.busy = false;
      ob.step = 3; return renderOnboarding();
    } catch (e) { return obError(e.message); }
  }
  if (kind === "demo") {
    ob.busy = true;
    try {
      obProgress("Making up six months of spending…");
      await api("/api/demo", { method: "POST" });
      ob.result = { kind: "demo" }; ob.busy = false;
      ob.step = 3; return renderOnboarding();
    } catch (e) { return obError(e.message); }
  }
}

// ---------- navigation ----------
const prevMonth = (m) => { const [y, mo] = m.split("-").map(Number); return mo === 1 ? `${y - 1}-12` : `${y}-${String(mo - 1).padStart(2, "0")}`; };

function setMonth(m) { state.month = m; syncHash(); loadMonth(); if (state.view === "activity") loadActivity(); if (state.view === "trends") loadTrends(); if (state.view === "category") loadCategory(); }

function go(view) {
  state.view = view;
  $$(".segmented[role=tablist] button").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === view));
  $("#settings-btn").classList.toggle("on", view === "settings");
  $("#settings-btn").setAttribute("aria-pressed", view === "settings");
  $("#month-switch").classList.toggle("off", view === "settings" || view === "rules" || !state.meta.months.length);
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  syncHash();
  if (view === "activity") loadActivity();
  if (view === "rules") loadRules();
  if (view === "settings") loadSettings();
  if (view === "trends") loadTrends();
  if (view === "category") loadCategory();
  if (view === "overview" && state.summary) renderCharts();
  scrollTo({ top: 0 });
}

function syncHash() { history.replaceState(null, "", `${location.search}#${state.view}/${state.month}`); }

function syncMonthNav() {
  const months = state.meta.months.map((m) => m.month);
  const i = months.indexOf(state.month);
  $("#month-label").textContent = monthName(state.month);
  $("#prev").disabled = i <= 0;
  $("#next").disabled = i === -1 || i >= months.length - 1;
}

async function loadMonth() {
  syncMonthNav();
  const empty = !state.meta.months.length;
  $("#month-switch").classList.toggle("off", empty || ["settings", "rules"].includes(state.view));
  $("#overview-empty").hidden = !empty;
  $("#overview-content").hidden = empty;
  $(".hero", $("#view-overview")).hidden = empty && !state.meta.source.demo;
  const s = state.summary = await api(`/api/summary?month=${state.month}`);
  renderHero(s); renderSource();
  if (empty) return;
  renderCategories(s); renderLeft(s); renderStats(s); renderPayLater(s); renderBudgets(s); renderMerchants(s);
  if (state.view === "overview") renderCharts();
}

function renderCharts() { if (!state.meta.months.length) return; const s = state.summary; renderDaily(s); renderTrend(s); renderHours(s); }

async function loadActivity() {
  const p = new URLSearchParams({ month: state.month });
  if (state.cat === INTERNAL) p.set("internal", "only");
  else if (state.cat === SETTLED || state.cat === HIDDEN) { p.set("show", state.cat === SETTLED ? "settled" : "hidden"); p.set("internal", "show"); }
  else if (state.cat?.startsWith(VIA)) p.set("via", state.cat.slice(VIA.length));
  else if (state.cat) p.set("category", state.cat);
  if (state.q) p.set("q", state.q);
  state.txs = await api(`/api/transactions?${p}`);
  renderActivity();
}

function wire() {
  $$(".segmented[role=tablist] button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  $("#settings-btn").addEventListener("click", () => go(state.view === "settings" ? "overview" : "settings"));
  // Arrow keys move between tabs, as in a native tab bar.
  $(".segmented[role=tablist]").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const tabs = $$(".segmented[role=tablist] button"), i = tabs.indexOf(document.activeElement);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    next.focus(); go(next.dataset.view);
  });
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => { state.cat = null; go(b.dataset.goto); }));
  const months = () => state.meta.months.map((m) => m.month);
  $("#prev").addEventListener("click", () => setMonth(months()[months().indexOf(state.month) - 1]));
  $("#next").addEventListener("click", () => setMonth(months()[months().indexOf(state.month) + 1]));
  $("#callout-btn").addEventListener("click", () => { state.cat = "other"; go("activity"); });
  $("#leave-demo").addEventListener("click", () => leaveDemo().catch((e) => toast(e.message)));
  $("#empty-start").addEventListener("click", () => openOnboarding(state.meta.settings.onboarded ? 2 : 0));
  $("#empty-demo").addEventListener("click", () => enterDemo().catch((e) => toast(e.message)));
  let qTimer;
  $("#search").addEventListener("input", (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); loadActivity(); }, 180); });

  // sheet
  $("#sheet-direction").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.editing.direction = b.dataset.dir; syncSheet(); } });
  $("#sheet-cats").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.add) return openNewCategory();
    state.editing.category = b.dataset.cat; syncSheet();
  });
  $("#new-cat-colors").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.newColor = b.dataset.color;
    $$("#new-cat-colors button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
  });
  $("#new-cat-add").addEventListener("click", createCategory);
  $("#new-cat-name").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); createCategory(); } });
  $("#sheet-remember").addEventListener("change", (e) => ($("#sheet-amount-row").hidden = !e.target.checked));
  $("#sheet-cancel").addEventListener("click", closeSheet);
  $("#scrim").addEventListener("click", closeSheet);
  $("#sheet-save").addEventListener("click", () => saveSheet().catch((e) => toast(e.message)));
  addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#sheet").hidden) closeSheet();
    else if (!$("#onboarding").hidden && $("#ob-close").style.visibility !== "hidden") closeOnboarding(true);
  });
  // Keep keyboard focus inside the sheet while it is open.
  $("#sheet").addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = $$("button, input, [tabindex]", $("#sheet")).filter((x) => !x.closest("[hidden]") && !x.disabled);
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });

  // settings
  $("#theme-seg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) savePref({ theme: b.dataset.themeOpt }); });
  $("#currency-sel").addEventListener("change", (e) => savePref({ currency: e.target.value }));
  $("#number-sel").addEventListener("change", (e) => savePref({ number: e.target.value }));
  $("#logos-toggle").addEventListener("change", (e) => savePref({ [state.settings.logos_key]: e.target.checked }));
  $("#gmail-btn").addEventListener("click", () => settingsGmail());
  $("#import-btn").addEventListener("click", () => settingsImport());
  $("#banks-btn").addEventListener("click", () => openOnboarding(1, { only: true }));
  $("#setup-btn").addEventListener("click", () => openOnboarding(0));
  $("#demo-btn").addEventListener("click", () => (state.settings.demo ? leaveDemo() : enterDemo().then(() => go("overview"))).catch((e) => toast(e.message)));
  $("#copy-path").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(state.settings.data_dir); toast("Path copied"); }
    catch { getSelection().selectAllChildren($("#data-path")); }
  });

  // onboarding
  $("#ob-back").addEventListener("click", () => obAction("back"));
  $("#ob-close").addEventListener("click", () => closeOnboarding(true));
  $("#ob-body").addEventListener("click", (e) => {
    const b = e.target.closest("[data-ob], [data-bank], [data-missing]");
    if (!b) return;
    obAction(b.dataset.ob || (b.dataset.bank ? "bank" : "missing"), b).catch((err) => obError(err.message));
  });

  let rTimer;
  addEventListener("resize", () => { clearTimeout(rTimer); rTimer = setTimeout(() => {
    if (state.view === "overview" && state.summary) renderCharts();
    if (state.view === "trends") renderTrends();
  }, 120); });
  $("#cat-back").addEventListener("click", () => go(state.backTo || "overview"));
  $("#cat-all").addEventListener("click", () => { state.cat = state.detailCat; go("activity"); });
  $("#trend-range").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.trendMonths = +b.dataset.months; loadTrends();
  });
  addEventListener("hashchange", () => {
    const [v, m] = location.hash.slice(1).split("/");
    if (m && m !== state.month && months().includes(m)) setMonth(m);
    if (v && v !== state.view && VIEWS.includes(v)) go(v);
  });
}

async function init() {
  wire();
  state.meta = await api("/api/meta");
  applyPrefs();
  const [view, month] = location.hash.slice(1).split("/");
  state.month = state.meta.months.some((m) => m.month === month) ? month : state.meta.current;
  await loadMonth();
  go(VIEWS.includes(view) ? view : "overview");
  const firstRun = !state.meta.source.emails && !state.meta.settings.onboarded && !state.meta.source.demo;
  if (view === "welcome" || firstRun) {
    state.settings = await api("/api/settings");
    openOnboarding(view === "welcome" ? Math.min(+month || 0, OB_STEPS - 1) : 0);
  }
}

init().catch((e) => {
  document.querySelector("main").innerHTML = `<div class="hero"><h1 class="hero-title">Couldn’t load your ledger</h1><p class="hero-sub">${esc(e.message)}</p></div>`;
});
