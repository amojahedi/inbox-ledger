// Ledger dashboard — dependency-free. Talks to the local FastAPI backend.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const INTERNAL = "__internal";
const VIA = "__via:";  // chip key prefix: charges paid through a pay-later provider  // chip key: moves between your own accounts (hidden from "All")
const state = { meta: null, month: null, view: "overview", summary: null, txs: [], cat: null, q: "", editing: null };

// ---------- formatting ----------
const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = (v, dec = false) => `${state.meta.currency} ${(dec ? nf2 : nf0).format(v || 0)}`;
const monthName = (m, style = "long") => {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString("en-US", style === "long" ? { month: "long", year: "numeric" } : { month: "short" });
};
const dayName = (d) => new Date(d + "T00:00").toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" });
const timeOf = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const cat = (key) => state.meta.categories.find((c) => c.key === key) || { key, name: key, color: "gray" };
const color = (key) => `var(--c-${cat(key).color || "gray"})`;
const initials = (name) => (name || "?").replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "•";

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2600);
}

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

// ---------- overview ----------
function renderHero(s) {
  const [int, dec] = nf2.format(s.spent).split(".");
  $("#hero-eyebrow").textContent = `Spent in ${monthName(s.month).split(" ")[0]}`;
  $("#hero-number").innerHTML = `<span class="ccy">${esc(s.currency)}</span>${int}<span class="dec">.${dec}</span>`;
  const parts = [];
  if (s.previous_spent > 0) {
    const pct = Math.round(((s.spent - s.previous_spent) / s.previous_spent) * 100);
    const prev = monthName(prevMonth(s.month)).split(" ")[0];
    parts.push(pct === 0 ? `Same as ${prev}` :
      `<span class="${pct > 0 ? "delta-up" : "delta-down"}">${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}%</span> ${pct > 0 ? "more" : "less"} than ${prev}`);
  }
  if (s.received > 0) {
    parts.push(`${money(s.received)} came in`);
    if (s.received > s.spent) parts.push(`<span class="delta-down">${money(s.received - s.spent)} saved</span>`);
  }
  $("#hero-sub").innerHTML = parts.join(" · ") || "&nbsp;";
}

function renderSource() {
  const src = state.meta.source, el = $("#source");
  const short = (d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  el.classList.toggle("demo", src.demo);
  el.textContent = src.demo ? "Example numbers · not real data"
    : src.emails ? `From your email · ${nf0.format(src.emails)} bank alerts · ${short(src.first)} – ${short(src.last)}` : "No emails yet · run sync";
}

function renderCategories(s) {
  const total = s.spent || 1;
  $("#stackbar").innerHTML = s.by_category.map((c) =>
    `<span style="flex-grow:${c.total};background:${color(c.category)}" title="${esc(cat(c.category).name)}"></span>`).join("");
  $("#stackbar").setAttribute("aria-label", s.by_category.map((c) => `${cat(c.category).name} ${money(c.total)}`).join(", "));
  $("#legend").innerHTML = s.by_category.map((c) => `
    <li data-cat="${esc(c.category)}">
      <span class="dot" style="background:${color(c.category)}"></span>
      <span class="lg-name">${esc(cat(c.category).name)}</span>
      <span class="lg-val">${money(c.total)}<span class="lg-pct">${Math.round((c.total / total) * 100)}%</span></span>
    </li>`).join("") || `<li class="muted">Nothing spent yet.</li>`;
  $$("#legend li[data-cat]").forEach((li) => li.addEventListener("click", () => { state.cat = li.dataset.cat; go("activity"); }));
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
    ["Daily average", money(perDay), `over ${elapsed} days`],
    projecting
      ? ["On pace for", money(perDay * days), "by month end"]
      : ["Biggest day", biggest ? money(biggest.total) : "—", biggest ? new Date(biggest.day + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""],
    ["Transactions", nf0.format(s.count), s.top_merchants.length ? `Most at ${esc(s.top_merchants[0].merchant)}` : ""],
    ["Biggest purchase", s.biggest ? money(s.biggest.amount_base) : "—", s.biggest ? esc(s.biggest.merchant) : ""],
  ];
  $("#stats").innerHTML = tiles.map(([p, v, sm]) => `<div class="stat"><p>${p}</p><strong>${v}</strong><small>${sm}</small></div>`).join("");

  const cb = $("#callout");
  cb.hidden = !s.uncategorized;
  if (s.uncategorized) $("#callout-text").textContent =
    `${s.uncategorized} transaction${s.uncategorized > 1 ? "s" : ""} couldn’t be categorized. Teach Ledger once and it remembers.`;
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
      <div><p>Paid via ${esc(pl.provider)} this month</p><strong>${money(pl.paid)}</strong>
        <small>${pl.payments} instalment${pl.payments === 1 ? "" : "s"}, counted under the real store</small></div>
      <div><p>Still to pay</p><strong>${money(pl.owed)}</strong>
        <small>across ${pl.open_orders.length} open order${pl.open_orders.length === 1 ? "" : "s"} · estimated from ${esc(pl.provider)}’s emails</small></div>
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
    return { label: String(i + 1), value: v, tip: `<b>${money(v)}</b>${dayName(day)}` };
  });
  const active = data.filter((d) => d.value > 0).length;
  $("#daily-note").textContent = `${active} day${active === 1 ? "" : "s"} with spending`;
  barChart($("#daily-chart"), data, { avg: s.spent / days, labelEvery: days > 20 ? 5 : 1 });
}

function renderTrend(s) {
  const all = state.meta.months;
  const idx = all.findIndex((x) => x.month === s.month);
  const slice = all.slice(Math.max(0, idx - 5), idx + 1);
  const data = slice.map((x) => ({
    label: monthName(x.month, "short"), value: x.spent, hi: x.month === s.month, month: x.month,
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

function renderBudgets(s) {
  const spent = Object.fromEntries(s.by_category.map((c) => [c.category, c.total]));
  const keys = state.meta.categories.map((c) => c.key)
    .filter((k) => !["income"].includes(k) && (spent[k] || s.budgets[k]));
  $("#budgets").innerHTML = keys.map((k) => {
    const used = spent[k] || 0, limit = s.budgets[k];
    const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
    const over = limit && used > limit;
    return `<li>
      <div class="b-row">
        <span class="dot" style="background:${color(k)}"></span>
        <span class="b-name">${esc(cat(k).name)}${over ? `<span class="b-status">Over by ${money(used - limit)}</span>` : ""}</span>
        <span class="b-amt">${money(used)}</span>
        <button class="b-limit" data-cat="${k}">${limit ? `of ${nf0.format(limit)}` : "Set limit"}</button>
      </div>
      ${limit ? `<div class="b-track"><div class="b-fill ${over ? "over" : ""}" style="width:${pct}%"></div></div>` : ""}
    </li>`;
  }).join("");
  $$(".b-limit").forEach((b) => b.addEventListener("click", () => editBudget(b, s.budgets[b.dataset.cat])));
}

function editBudget(btn, current) {
  const input = document.createElement("input");
  input.type = "text"; input.inputMode = "decimal"; input.value = current || "";
  input.placeholder = "Limit"; input.style.cssText = "width:96px;padding:4px 10px;font-size:14px;text-align:right";
  btn.replaceWith(input); input.focus();
  const commit = async () => {
    const v = parseFloat(input.value.replace(/,/g, ""));
    await api(`/api/budgets/${btn.dataset.cat}`, { method: "PUT", body: JSON.stringify({ monthly: isNaN(v) ? null : v }) });
    await loadMonth();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); if (e.key === "Escape") { input.value = current || ""; input.blur(); } });
  input.addEventListener("blur", commit, { once: true });
}

function renderMerchants(s) {
  $("#merchants").innerHTML = s.top_merchants.map((m, i) => `
    <li><span class="rank">${i + 1}</span>
      <span class="m-name">${esc(m.merchant)}<small>${esc(cat(m.category).name)} · ${m.count} time${m.count > 1 ? "s" : ""}</small></span>
      <span class="m-amt">${money(m.total)}</span></li>`).join("") || `<li class="muted">No merchants yet.</li>`;
}

// ---------- activity ----------
function renderChips() {
  const chips = [{ key: null, name: "All" }, { key: "other", name: "Needs review", color: "gray" },
    ...(state.meta.pay_later || []).map((p) => ({ key: `${VIA}${p}`, name: `Pay later · ${p}`, color: "gray" })),
    ...state.meta.categories.filter((c) => c.key !== "other"), { key: INTERNAL, name: "My accounts", color: "gray" }];
  $("#chips").innerHTML = chips.map((c) =>
    `<button class="chip ${state.cat === c.key ? "on" : ""}" data-cat="${c.key ?? ""}">${c.key ? `<span class="dot" style="background:var(--c-${c.color})"></span>` : ""}${esc(c.name)}</button>`).join("");
  $$(".chip").forEach((b) => b.addEventListener("click", () => { state.cat = b.dataset.cat || null; loadActivity(); }));
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
    const out = list.filter((t) => t.direction === "out").reduce((a, t) => a + t.amount_base, 0);
    html += `<li class="tx-day"><span>${dayName(day)}</span><span>${out ? money(out) : ""}</span></li>`;
    for (const t of list) {
      const sign = t.direction === "in" ? "+" : t.direction === "internal" ? "" : "−";
      const fx = t.currency !== state.meta.currency ? `<small>${esc(t.currency)} ${nf2.format(t.amount)}</small>` : "";
      const tag = t.category_source === "learned" ? ` · <span class="learned">Learned</span>` : t.category_source === "manual" ? ` · <span class="learned">Edited</span>` : "";
      const sub = (t.direction === "internal" ? "Between your accounts" : cat(t.category).name) +
        (t.extra?.via ? ` · via ${t.extra.via}` : "");
      html += `<li class="tx" data-id="${t.id}" tabindex="0">
        <span class="tx-icon" style="background:${t.direction === "internal" ? "var(--c-gray)" : color(t.category)}">${esc(initials(t.merchant))}</span>
        <span class="tx-main"><div class="tx-name">${esc(t.merchant)}</div><div class="tx-sub">${esc(sub)} · ${timeOf(t.occurred_at)}${tag}${t.note ? ` · ${esc(t.note)}` : ""}</div></span>
        <span class="tx-amt ${t.direction}">${sign}${nf2.format(t.amount_base)}${fx}</span>
      </li>`;
    }
  }
  $("#tx-list").innerHTML = html;
  $("#tx-empty").hidden = state.txs.length > 0;
  $$(".tx").forEach((li) => {
    const open = () => openSheet(state.txs.find((t) => t.id === li.dataset.id));
    li.addEventListener("click", open);
    li.addEventListener("keydown", (e) => e.key === "Enter" && open());
  });
}

// ---------- sheet ----------
function openSheet(t) {
  state.editing = { t, category: t.category, direction: t.direction };
  $("#sheet-date").textContent = `${dayName(t.occurred_at.slice(0, 10))} · ${timeOf(t.occurred_at)}`;
  $("#sheet-title").textContent = t.merchant;
  $("#sheet-amount").textContent = money(t.amount_base, true);
  $("#sheet-merchant").textContent = t.merchant;
  $("#sheet-note").value = t.note || "";
  $("#sheet-remember").checked = true;
  $("#sheet-match-amount").checked = false;
  $("#sheet-amount-match").textContent = `${t.currency} ${nf2.format(t.amount)}`;
  $("#sheet-amount-row").hidden = false;
  const meta = [["From email", t.merchant_raw], ["Account", t.account ? `•••• ${t.account}` : "—"], ["Bank", t.bank]];
  if (t.currency !== state.meta.currency) meta.push(["Charged", `${t.currency} ${nf2.format(t.amount)}`]);
  if (t.extra?.via) meta.push(["Paid with", t.extra.order ? `${t.extra.via} · order ${t.extra.order}` : t.extra.via]);
  $("#sheet-meta").innerHTML = meta.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
  renderSheetCats();
  $("#new-cat").hidden = true;
  syncSheet();
  $("#scrim").hidden = $("#sheet").hidden = false;
  $(`#sheet-cats [data-cat="${t.category}"]`)?.focus({ preventScroll: true });
}

const COLORS = ["blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red", "gray"];

function renderSheetCats() {
  $("#sheet-cats").innerHTML = state.meta.categories.map((c) =>
    `<button data-cat="${c.key}"><span class="dot" style="background:var(--c-${c.color})"></span>${esc(c.name)}</button>`).join("") +
    `<button class="add" data-add="1">＋ New category</button>`;
  if (state.editing) syncSheet();
}

function openNewCategory() {
  const f = $("#new-cat");
  f.hidden = false;
  $("#new-cat-name").value = "";
  state.newColor = state.newColor || "aqua";
  $("#new-cat-colors").innerHTML = COLORS.map((c) =>
    `<button type="button" data-color="${c}" aria-label="${c}" class="${c === state.newColor ? "on" : ""}" style="background:var(--c-${c})"></button>`).join("");
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
  $$("#sheet-direction button").forEach((b) => b.classList.toggle("on", b.dataset.dir === e.direction));
  $$("#sheet-cats button").forEach((b) => b.classList.toggle("on", b.dataset.cat === e.category));
}

function closeSheet() { $("#scrim").hidden = $("#sheet").hidden = true; state.editing = null; }

async function saveSheet() {
  const { t, category, direction } = state.editing;
  const remember = $("#sheet-remember").checked;
  const matchAmount = remember && $("#sheet-match-amount").checked;
  const note = $("#sheet-note").value.trim();
  const body = { remember, match_amount: matchAmount };
  if (category !== t.category) body.category = category;
  if (direction !== t.direction) body.direction = direction;
  if (note !== (t.note || "")) body.note = note;
  if (Object.keys(body).length === 2) return closeSheet();
  await api(`/api/transactions/${t.id}`, { method: "PATCH", body: JSON.stringify(body) });
  closeSheet();
  const what = direction === "internal" ? "a transfer between your accounts" : cat(category).name;
  const at = matchAmount ? ` at ${t.currency} ${nf2.format(t.amount)}` : "";
  toast(remember && (body.category || body.direction) ? `Got it — ${t.merchant}${at} will always be ${what}.` : "Saved");
  state.meta = await api("/api/meta");
  await Promise.all([loadMonth(), state.view === "activity" ? loadActivity() : null]);
}

// ---------- rules ----------
function renderCustomCats() {
  const mine = state.meta.categories.filter((c) => c.custom);
  $("#cat-section").hidden = !mine.length;
  $("#cat-list").innerHTML = mine.map((c) => `
    <li class="rule">
      <span class="rule-name"><span class="dot" style="background:var(--c-${c.color});display:inline-block;margin-right:8px"></span>${esc(c.name)}</span>
      <span></span>
      <button class="btn-del" data-cat="${esc(c.key)}">Delete</button>
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
      <span class="rule-name">${esc(r.merchant || r.merchant_key)}${r.amount ? ` <span class="muted">at ${nf2.format(r.amount)}</span>` : ""}<small>Learned ${new Date(r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</small></span>
      <span class="pill">${r.category ? `<span class="dot" style="background:${color(r.category)}"></span>${esc(cat(r.category).name)}` : ""}${r.direction ? `${r.category ? " · " : ""}${dirName[r.direction]}` : ""}</span>
      <button class="btn-del" data-key="${esc(r.merchant_key)}" data-amount="${r.amount || 0}">Forget</button>
    </li>`).join("");
  $$(".btn-del").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/rules/${encodeURIComponent(b.dataset.key)}?amount=${b.dataset.amount}`, { method: "DELETE" });
    toast("Rule removed"); loadRules(); loadMonth();
  }));
}

// ---------- navigation ----------
const prevMonth = (m) => { const [y, mo] = m.split("-").map(Number); return mo === 1 ? `${y - 1}-12` : `${y}-${String(mo - 1).padStart(2, "0")}`; };

function setMonth(m) { state.month = m; syncHash(); loadMonth(); if (state.view === "activity") loadActivity(); }

function go(view) {
  state.view = view;
  $$(".segmented[role=tablist] button").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === view));
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  syncHash();
  if (view === "activity") loadActivity();
  if (view === "rules") loadRules();
  if (view === "overview" && state.summary) renderCharts();
  scrollTo({ top: 0 });
}

function syncHash() { history.replaceState(null, "", `#${state.view}/${state.month}`); }

function syncMonthNav() {
  const months = state.meta.months.map((m) => m.month);
  const i = months.indexOf(state.month);
  $("#month-label").textContent = monthName(state.month);
  $("#prev").disabled = i <= 0;
  $("#next").disabled = i === -1 || i >= months.length - 1;
}

async function loadMonth() {
  syncMonthNav();
  const s = state.summary = await api(`/api/summary?month=${state.month}`);
  renderHero(s); renderSource(); renderCategories(s); renderStats(s); renderPayLater(s); renderBudgets(s); renderMerchants(s);
  if (state.view === "overview") renderCharts();
}

function renderCharts() { const s = state.summary; renderDaily(s); renderTrend(s); renderHours(s); }

async function loadActivity() {
  const p = new URLSearchParams({ month: state.month });
  if (state.cat === INTERNAL) p.set("internal", "only");
  else if (state.cat?.startsWith(VIA)) p.set("via", state.cat.slice(VIA.length));
  else if (state.cat) p.set("category", state.cat);
  if (state.q) p.set("q", state.q);
  state.txs = await api(`/api/transactions?${p}`);
  renderActivity();
}

async function init() {
  const theme = new URLSearchParams(location.search).get("theme");
  if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
  state.meta = await api("/api/meta");
  const [view, month] = location.hash.slice(1).split("/");
  state.month = state.meta.months.some((m) => m.month === month) ? month : state.meta.current;
  $$(".segmented[role=tablist] button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => { state.cat = null; go(b.dataset.goto); }));
  const months = () => state.meta.months.map((m) => m.month);
  $("#prev").addEventListener("click", () => setMonth(months()[months().indexOf(state.month) - 1]));
  $("#next").addEventListener("click", () => setMonth(months()[months().indexOf(state.month) + 1]));
  $("#callout-btn").addEventListener("click", () => { state.cat = "other"; go("activity"); });
  let qTimer;
  $("#search").addEventListener("input", (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); loadActivity(); }, 180); });
  $("#sheet-direction").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.editing.direction = b.dataset.dir; syncSheet(); } });
  $("#sheet-cats").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.add) return openNewCategory();
    state.editing.category = b.dataset.cat; syncSheet();
  });
  $("#new-cat-colors").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.newColor = b.dataset.color;
    $$("#new-cat-colors button").forEach((x) => x.classList.toggle("on", x === b));
  });
  $("#new-cat-add").addEventListener("click", createCategory);
  $("#new-cat-name").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); createCategory(); } });
  $("#sheet-remember").addEventListener("change", (e) => ($("#sheet-amount-row").hidden = !e.target.checked));
  $("#sheet-cancel").addEventListener("click", closeSheet);
  $("#scrim").addEventListener("click", closeSheet);
  $("#sheet-save").addEventListener("click", () => saveSheet().catch((e) => toast(e.message)));
  addEventListener("keydown", (e) => e.key === "Escape" && !$("#sheet").hidden && closeSheet());
  let rTimer;
  addEventListener("resize", () => { clearTimeout(rTimer); rTimer = setTimeout(() => state.view === "overview" && state.summary && renderCharts(), 120); });

  addEventListener("hashchange", () => {
    const [v, m] = location.hash.slice(1).split("/");
    if (m && m !== state.month && months().includes(m)) setMonth(m);
    if (v && v !== state.view && ["overview", "activity", "rules"].includes(v)) go(v);
  });

  await loadMonth();
  go(["overview", "activity", "rules"].includes(view) ? view : "overview");
}

init().catch((e) => {
  document.querySelector("main").innerHTML = `<div class="hero"><h1 class="hero-title">Couldn’t load your ledger</h1><p class="hero-sub">${esc(e.message)}</p></div>`;
});
