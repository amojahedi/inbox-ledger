// Overview, category detail. Loaded after shared.js.
"use strict";

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
    // Saved = what you moved into your own savings; left = came in − spent − saved.
    if (s.moved > 0) out.push(`<span class="nowrap delta-down">${money(s.moved)} saved</span>`);
    const left = s.received - s.spent - (s.moved || 0);
    out.push(`<span class="nowrap ${left < 0 ? "delta-up" : ""}">${left < 0 ? `${money(-left)} over` : `${money(left)} left`}</span>`);
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

// Is the month still running? Example data always shows a finished example month.
function inProgress(month) {
  if (state.meta?.source?.demo) return false;
  const [y, m] = month.split("-").map(Number), today = new Date();
  return today.getFullYear() === y && today.getMonth() + 1 === m;
}

// Whole-number percentages that add up to exactly 100 (largest remainder).
function percents(values) {
  const total = values.reduce((a, v) => a + Math.max(0, v), 0) || 1;
  const raw = values.map((v) => (Math.max(0, v) / total) * 100);
  const out = raw.map(Math.floor);
  let rest = 100 - out.reduce((a, v) => a + v, 0);
  raw.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (rest > 0) { out[i]++; rest--; } });
  return out;
}

function renderCategories(s) {
  // Refunds can leave a category below zero: it stays in the list but takes no share of the bar.
  const total = s.by_category.reduce((a, c) => a + Math.max(0, c.total), 0) || 1;
  $("#stackbar").innerHTML = s.by_category.filter((c) => c.total > 0).map((c) =>
    `<span style="flex-grow:${c.total};background:${color(c.category)}"></span>`).join("");
  $("#stackbar").setAttribute("aria-label", s.by_category.map((c) => `${catName(c.category)} ${money(c.total)}`).join(", ") || "No spending");
  const pct = percents(s.by_category.map((c) => c.total));
  $("#legend").innerHTML = s.by_category.map((c, i) => `
    <li><button class="lg" data-cat="${esc(c.category)}" aria-label="${esc(catName(c.category))}, ${money(c.total)}${c.total > 0 ? `, ${pct[i]}%` : ""}. Show transactions">
      <span class="dot" style="background:${color(c.category)}"></span>
      <span class="lg-name">${esc(catName(c.category))}</span>
      <span class="lg-val">${money(c.total)}<span class="lg-pct">${c.total > 0 ? `${pct[i]}%` : ""}</span></span>
    </button></li>`).join("") || `<li class="muted">Nothing spent this month.</li>`;
  $("#legend-total").innerHTML = s.by_category.length
    ? `<span>Total</span><span>${money(s.by_category.reduce((a, c) => a + c.total, 0))}</span>` : "";
  $$("#legend .lg").forEach((b) => b.addEventListener("click", () => openCategory(b.dataset.cat)));
}

function renderStats(s) {
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const today = new Date();
  const isCurrent = inProgress(s.month);
  const lastDataDay = s.by_day.length ? +s.by_day[s.by_day.length - 1].day.slice(8) : 0;
  const elapsed = isCurrent ? Math.max(today.getDate(), lastDataDay) : days;
  const projecting = isCurrent && elapsed < days;
  const perDay = s.spent / elapsed;
  const biggest = s.by_day.reduce((a, b) => (b.total > (a?.total || 0) ? b : a), null);
  // Fixed costs land once a month; only day-to-day spending carries on at the current pace.
  const FIXED = ["housing", "bills", "subscriptions"];
  const fixed = s.by_category.filter((c) => FIXED.includes(c.category)).reduce((a, c) => a + c.total, 0);
  const pace = s.spent + ((s.spent - fixed) / elapsed) * (days - elapsed);
  const topCat = s.by_category[0];
  const regular = [...s.top_merchants].sort((a, b) => b.count - a.count)[0];
  const tiles = [
    ["Daily average", money(perDay), `Over ${elapsed} days`],
    projecting
      ? ["On pace for", money(pace), "Fixed costs counted once"]
      : ["Biggest day", biggest ? money(biggest.total) : "—", biggest ? shortDate(biggest.day + "T00:00") : ""],
    ["Transactions", nf0.format(s.count), s.top_merchants.length ? `Most at ${esc(s.top_merchants[0].merchant)}` : ""],
    ["Biggest purchase", s.biggest ? money(s.biggest.amount_base) : "—", s.biggest ? esc(s.biggest.merchant) : ""],
    ["Top category", topCat ? esc(catName(topCat.category)) : "—", topCat ? `${money(topCat.total)} · ${percents(s.by_category.map((c) => c.total))[0]}% of spending` : ""],
    ["Most visited", regular ? esc(regular.merchant) : "—", regular ? `${plural(regular.count, "time")} · ${money(regular.total)}` : ""],
  ];
  $("#stats").innerHTML = tiles.map(([p, v, sm]) => `<div class="stat"><p>${p}</p><strong>${v}</strong><small>${sm}</small></div>`).join("");

  const cb = $("#callout");
  cb.hidden = !s.uncategorized;
  if (s.uncategorized) $("#callout-text").textContent =
    `${plural(s.uncategorized, "transaction")} ${s.uncategorized === 1 ? "needs" : "need"} a category. Teach Ledger once and it remembers.`;
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
  $("#daily-note").textContent = `${plural(active, "active day")}`;
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
  const current = inProgress(s.month);
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
        ? `${money(income)} came in − ${money(s.spent)} spent${aside ? ` − ${money(aside)} saved` : ""} = <b>${left < 0 ? "−" : ""}${money(Math.abs(left))} left</b>`
        : `${money(budgetTotal)} budgeted − ${money(budgetUsed)} used = <b>${money(left)} left</b>`}</p>
    </div>
    <div class="left-side">
      ${income ? `<div><p>Came in</p><strong>${money(income)}</strong></div>` : ""}
      ${budgetTotal ? (budgetUsed > budgetTotal
        ? `<div><p>Budgets</p><strong class="delta-up">Over by ${money(budgetUsed - budgetTotal)}</strong><small>of ${money(budgetTotal)}</small></div>`
        : `<div><p>Budgets left</p><strong>${money(budgetTotal - budgetUsed)}</strong><small>of ${money(budgetTotal)}</small></div>`) : ""}
      ${income ? `<div><p>Saved this month</p><strong>${money(aside)}</strong><small>${aside ? "moved to your savings" : "nothing put aside yet"}</small></div>` : ""}
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

