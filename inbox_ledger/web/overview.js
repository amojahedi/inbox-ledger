// Overview, category detail. Loaded after shared.js.
"use strict";

// ---------- fixed vs everyday ----------
// Rent, bills and subscriptions land once a month; everything else is everyday spending.
// The server says which categories are fixed; until it does, these three are.
const DEFAULT_FIXED = ["housing", "bills", "subscriptions"];
function fixedKeys() {
  const flagged = state.meta.categories.filter((c) => c.fixed === true).map((c) => c.key);
  if (flagged.length || state.meta.categories.some((c) => "fixed" in c)) return flagged;
  return state.insights?.fixed_keys || DEFAULT_FIXED;
}
const isFixed = (key) => fixedKeys().includes(key);

// The insights answer for the month on screen, or null while it loads.
function insightsFor(month) { return state.insights?.month === month ? state.insights : null; }

// Fetch /api/insights once per month and redraw what depends on it. Everything renders first from
// the summary alone, so a slow or missing answer only means the finer numbers arrive a beat later.
function ensureInsights(s) {
  if (!state.meta.months.length || insightsFor(s.month) || state.insightsLoading === s.month) return;
  state.insightsLoading = s.month;
  api(`/api/insights?month=${s.month}`).then((d) => {
    if (state.insightsLoading === s.month) state.insightsLoading = null;
    if (d.month !== state.month || state.summary?.month !== d.month) return;
    state.insights = d;
    renderHero(state.summary); renderStats(state.summary); renderLeft(state.summary);
    if (state.view === "overview") renderCharts();
  }).catch(() => {
    if (state.insightsLoading === s.month) state.insightsLoading = null;
    state.insightsFailed = s.month;
    if (state.summary?.month === s.month) renderInsights(s);
  });
}

// Fixed and everyday as whole amounts that add up to the whole-amount total on screen.
function splitOf(s) {
  const ins = insightsFor(s.month);
  const fixed = typeof s.fixed === "number" ? s.fixed
    : ins ? ins.fixed : s.by_category.filter((c) => isFixed(c.category)).reduce((a, c) => a + c.total, 0);
  const fx = Math.round(fixed), spent = Math.round(s.spent);
  return { fixed: fx, everyday: spent - fx, fixedExact: fixed, everydayExact: s.spent - fixed };
}

// Is the month still running? Example data always shows a finished example month.
function inProgress(month) {
  if (state.meta?.source?.demo) return false;
  if (state.summary?.month === month && typeof state.summary.in_progress === "boolean") return state.summary.in_progress;
  const ins = insightsFor(month);
  if (ins) return ins.in_progress;
  const [y, m] = month.split("-").map(Number), today = new Date();
  return today.getFullYear() === y && today.getMonth() + 1 === m;
}

function elapsedDays(s) {
  const [y, m] = s.month.split("-").map(Number), days = new Date(y, m, 0).getDate();
  if (!inProgress(s.month)) return days;
  if (typeof s.elapsed_days === "number") return s.elapsed_days;
  const ins = insightsFor(s.month);
  if (ins) return ins.elapsed_days;
  const lastDataDay = s.by_day.length ? +s.by_day[s.by_day.length - 1].day.slice(8) : 0;
  return Math.min(days, Math.max(new Date().getDate(), lastDataDay));
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
  const prevName = monthName(prevMonth(state.month), "short");
  $("#cat-eyebrow").innerHTML = `<span class="dot" style="background:${color(key)}"></span>${esc(catName(key))} · ${esc(monthName(state.month))}`;
  $("#cat-total").innerHTML = money(d.total);
  const change = d.previous ? Math.round(((d.total - d.previous) / d.previous) * 100) : null;
  $("#cat-sub").innerHTML = [
    change === null ? "" : `<span class="${change > 0 ? "delta-up" : "delta-down"}">${change > 0 ? "▲" : "▼"} ${Math.abs(change)}%</span> vs ${esc(prevName)}`,
    `${plural(d.count, "purchase")} at ${plural(d.places.length, "place")}`,
  ].filter(Boolean).join(" · ");
  $("#cat-places-title").textContent = key === "dining" ? "Restaurants compared" : "Places compared";
  $("#cat-places-note").textContent = d.places.length ? "Bar = share of this month" : "";
  const top = Math.max(1, ...d.places.map((p) => p.total));  // a place that only refunded has a negative total
  // Shares come from the server; otherwise whole percentages that add up to 100.
  const shares = d.places.every((p) => typeof p.share === "number") ? d.places.map((p) => p.share) : percents(d.places.map((p) => p.total));
  $("#cat-places").innerHTML = d.places.map((p, i) => {
    const diff = p.previous ? Math.round(((p.total - p.previous) / p.previous) * 100) : null;
    return `<li>
      <span class="rank">${i + 1}</span>${avatar(p.merchant, p.brand, color(key), "sm")}
      <span class="p-main"><div class="p-name">${esc(p.merchant)}</div>
        <div class="p-sub">${plural(p.visits, "visit")} · ${money(p.average)} each${diff === null ? " · new" : diff === 0 ? ` · same as ${esc(prevName)}` : ` · <span class="${diff > 0 ? "up" : "down"}">${diff > 0 ? "▲" : "▼"} ${Math.abs(diff)}%</span> vs ${esc(prevName)}`}</div>
        <div class="p-track"><div class="p-fill" style="width:${Math.max(0, p.total / top) * 100}%;background:${color(key)}"></div></div></span>
      <span class="p-amt">${money(p.total)}<small>${d.total > 0 && p.total > 0 ? `${shares[i]}%` : ""}</small></span></li>`;
  }).join("") || `<li class="muted">Nothing in ${esc(catName(key).toLowerCase())} this month.</li>`;
  barChart($("#cat-trend"), d.trend.map((m) => ({
    label: monthName(m.month, "short"), value: Math.max(0, m.total), hi: m.month === state.month, tip: `<b>${money(m.total)}</b>${monthName(m.month)}`,
  })));
}

// ---------- overview ----------
function renderHero(s) {
  ensureInsights(s);
  const parts = nf2.formatToParts(s.spent);
  const at = parts.findIndex((p) => p.type === "decimal");
  const int = parts.slice(0, at).map((p) => p.value).join("");
  const dec = parts.slice(at).map((p) => p.value).join("");
  const ccy = `<span class="ccy ${ccyMode()}">${esc(s.currency)}</span>`;
  $("#hero-eyebrow").textContent = `Spent in ${monthName(s.month).split(" ")[0]}`;
  $("#hero-number").innerHTML = `${ccyMode() === "code" ? ccy : ""}${int}<span class="dec">${dec}</span>${ccyMode() === "after" ? ccy : ""}`;
  const out = [];
  const prev = monthName(prevMonth(s.month)).split(" ")[0];
  const ins = insightsFor(s.month);
  const running = inProgress(s.month);
  // While the month runs, compare like with like: the same days of last month.
  const toDate = running ? (typeof s.previous_spent_to_date === "number" ? s.previous_spent_to_date : ins?.previous_spent_to_date) : null;
  const delta = (now, base, same, label) => {
    const pct = Math.round(((now - base) / base) * 100);
    return pct === 0 ? `Same as ${same}` :
      `<span class="nowrap"><span class="${pct > 0 ? "delta-up" : "delta-down"}"><span aria-hidden="true">${pct > 0 ? "▲" : "▼"}</span> ${Math.abs(pct)}%</span> ${label(pct)}</span>`;
  };
  if (running && toDate > 0) {
    const range = `${monthName(prevMonth(s.month), "short")} 1–${elapsedDays(s)}`;
    out.push(delta(s.spent, toDate, range, () => `vs ${range}`));
  } else if (!running && s.previous_spent > 0) {
    out.push(delta(s.spent, s.previous_spent, prev, (pct) => `${pct > 0 ? "more" : "less"} than ${prev}`));
  }
  if (s.received > 0) {
    out.push(`<span class="nowrap">${money(s.received)} came in</span>`);
    // Saved = what you moved into your own savings; left = came in − spent − saved.
    if (s.moved > 0) out.push(`<span class="nowrap delta-down">${money(s.moved)} saved</span>`);
    const left = typeof s.left === "number" ? s.left : s.received - s.spent - (s.moved || 0);
    out.push(`<span class="nowrap ${left < 0 ? "delta-up" : ""}">${left < 0 ? `${money(-left)} over` : `${money(left)} left`}</span>`);
  }
  $("#hero-sub").innerHTML = out.join(" · ") || "&nbsp;";
  const split = splitOf(s);
  $("#hero-split").innerHTML = s.spent > 0 && split.fixed > 0
    ? `<span class="nowrap">${money(split.fixed)} fixed</span> · <span class="nowrap">${money(split.everyday)} everyday</span>` : "";
}

function renderSource() {
  const src = state.meta.source, el = $("#source");
  el.classList.toggle("demo", src.demo);
  el.textContent = src.demo ? "Example numbers · not real data"
    : src.emails ? `From your email · ${plural(src.emails, "bank alert")} · ${shortDate(src.first)} – ${shortDate(src.last)}` : "No emails yet";
  $("#leave-demo").hidden = state.meta.mode !== "demo";
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

// The merchant you went to most this month: from the summary, else the insights answer, else the
// best guess from the top merchants list.
function mostVisited(s) {
  if (s.most_visited?.merchant) return s.most_visited;
  const ins = insightsFor(s.month);
  if (ins?.most_visited) return ins.most_visited;
  return [...s.top_merchants].sort((a, b) => b.count - a.count || b.total - a.total)[0] || null;
}

function biggestEveryday(s) {
  if (s.biggest_everyday?.merchant) return s.biggest_everyday;
  const ins = insightsFor(s.month);
  if (ins) return ins.biggest_everyday;
  return s.biggest && !isFixed(s.biggest.category) ? { merchant: s.biggest.merchant, amount: s.biggest.amount_base, category: s.biggest.category } : null;
}

function renderStats(s) {
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const elapsed = elapsedDays(s);
  const split = splitOf(s);
  const perDay = split.everydayExact / Math.max(1, elapsed);
  // Fixed costs land once a month; only everyday spending carries on at the current pace.
  const likely = split.fixedExact + perDay * days;
  const projecting = inProgress(s.month) && elapsed < days;
  const everydayCats = s.by_category.filter((c) => !isFixed(c.category) && c.total > 0);
  const topCat = everydayCats[0];
  const topShare = topCat ? percents(everydayCats.map((c) => c.total))[0] : 0;
  const big = biggestEveryday(s);
  const regular = mostVisited(s);
  const tiles = [
    ["Everyday per day", money(perDay), projecting ? `Likely ${money(likely)} this month` : `Over ${elapsed} days · fixed costs aside`],
    ["Most visited", regular ? esc(regular.merchant) : "—", regular ? `${plural(regular.count, "time")} · ${money(regular.total)}` : ""],
    ["Biggest everyday purchase", big ? money(big.amount) : "—", big ? esc(big.merchant) : ""],
    ["Top everyday category", topCat ? esc(catName(topCat.category)) : "—", topCat ? `${money(topCat.total)} · ${topShare}% of everyday` : ""],
  ];
  $("#stat-tiles").innerHTML = tiles.map(([p, v, sm]) => `<div class="stat"><p>${p}</p><strong>${v}</strong><small>${sm}</small></div>`).join("");
  renderInsights(s);

  const cb = $("#callout");
  cb.hidden = !s.uncategorized;
  if (s.uncategorized) $("#callout-text").textContent =
    `${plural(s.uncategorized, "transaction")} ${s.uncategorized === 1 ? "needs" : "need"} a category. Teach Ledger once and it remembers.`;
}

// "{0}" and "{1}" are amounts in the reader's currency style; "{category}" is the category's name.
function insightText(line) {
  return esc(line.text)
    .replace(/\{category\}/g, line.category ? esc(catName(line.category)) : "")
    .replace(/\{(\d+)\}/g, (_, i) => money(line.amounts?.[+i] || 0));
}

// Ranked lines about the month; each one opens the category or the matching activity list.
function renderInsights(s) {
  const ins = insightsFor(s.month);
  const list = $("#insight-list");
  const lines = ins ? ins.lines || [] : null;
  $("#insight-note").textContent = monthName(s.month).split(" ")[0];
  if (!lines) {
    list.innerHTML = `<li class="muted">${state.insightsFailed === s.month ? "Not available right now." : "Looking at the month…"}</li>`;
    return;
  }
  list.innerHTML = lines.map((l, i) => `
    <li><button class="insight" data-i="${i}" aria-label="${insightText(l).replace(/<[^>]+>/g, "")}. Show details">
      <span class="dot" style="background:${l.category ? color(l.category) : "var(--text-3)"}"></span>
      <span class="insight-text">${insightText(l)}</span>${icon("chevron", "insight-chev")}</button></li>`).join("")
    || `<li class="muted">Nothing stands out this month.</li>`;
  $$("#insight-list .insight").forEach((b) => b.addEventListener("click", () => {
    const l = lines[+b.dataset.i];
    if (l.to === "category" && l.category) return openCategory(l.category);
    state.cat = l.via ? `${VIA}${l.via}` : l.category || null;
    state.q = l.q || "";
    const search = $("#search"); if (search) search.value = state.q;
    go("activity");
  }));
}

// Everyday spend by day and hour, from the summary when it carries it, else from insights.
function everydaySeries(s, which) {
  const ins = insightsFor(s.month);
  const rows = ins ? ins[which] : null;
  const key = which === "by_day" ? "day" : "hour";
  if (rows) return Object.fromEntries(rows.map((r) => [r[key], r.everyday]));
  // No answer yet: draw the totals; the chart redraws once the split lands.
  return Object.fromEntries(s[which].map((r) => [r[key], r.total]));
}

function wireFixedToggles() {
  if (wireFixedToggles.done) return;
  wireFixedToggles.done = true;
  $$("[data-fixed]").forEach((b) => b.addEventListener("click", () => {
    state.includeFixed = !state.includeFixed;
    renderCharts();
  }));
}

function syncFixedToggles(show) {
  $$("[data-fixed]").forEach((b) => {
    b.hidden = !show;
    b.setAttribute("aria-pressed", String(!!state.includeFixed));
    b.textContent = state.includeFixed ? "Fixed included" : "Include fixed";
  });
}

function renderDaily(s) {
  wireFixedToggles();
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const split = splitOf(s);
  const includeFixed = !!state.includeFixed || split.fixedExact <= 0;
  syncFixedToggles(split.fixedExact > 0);
  const map = includeFixed ? Object.fromEntries(s.by_day.map((d) => [d.day, d.total])) : everydaySeries(s, "by_day");
  const elapsed = elapsedDays(s);
  const data = Array.from({ length: days }, (_, i) => {
    const day = `${s.month}-${String(i + 1).padStart(2, "0")}`;
    const v = map[day] || 0;
    return { label: String(i + 1), value: Math.max(0, v), tip: `<b>${money(v)}</b>${dayName(day)}${includeFixed ? "" : " · everyday"}` };
  });
  const active = data.filter((d) => d.value > 0).length;
  $("#daily-note").textContent = `${plural(active, "active day")}`;
  const total = includeFixed ? s.spent : split.everydayExact;
  barChart($("#daily-chart"), data, { avg: total / Math.max(1, elapsed), labelEvery: days > 20 ? 5 : 1 });
}

// Lighten the bar for a month that is still running.
function markOpenBar(el, index) {
  if (index < 0) return;
  const bar = $$(".bar", el)[index];
  if (bar) bar.classList.add("open");
}

function renderTrend(s) {
  const all = state.meta.months;
  const idx = all.findIndex((x) => x.month === s.month);
  const slice = all.slice(Math.max(0, idx - 5), idx + 1);
  const data = slice.map((x) => ({
    label: monthName(x.month, "short"), value: Math.max(0, x.spent), hi: x.month === s.month, month: x.month,
    tip: `<b>${money(x.spent)}</b>${monthName(x.month)}${inProgress(x.month) && x.month === s.month ? ` · to ${monthName(x.month, "short")} ${elapsedDays(s)}` : ""}`,
  }));
  barChart($("#trend-chart"), data, { onClick: (d) => setMonth(d.month) });
  const running = inProgress(s.month);
  if (running) markOpenBar($("#trend-chart"), data.findIndex((d) => d.month === s.month));
  $("#trend-note").textContent = running ? `${monthName(s.month, "short")} so far` : "";
}

function renderHours(s) {
  const split = splitOf(s);
  const includeFixed = !!state.includeFixed || split.fixedExact <= 0;
  const map = includeFixed ? Object.fromEntries(s.by_hour.map((h) => [h.hour, h.total])) : everydaySeries(s, "by_hour");
  const label = (h) => (h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`);
  const data = Array.from({ length: 24 }, (_, h) => ({
    label: label(h), value: Math.max(0, map[h] || 0), tip: `<b>${money(map[h] || 0)}</b>${label(h)}–${label((h + 1) % 24)}${includeFixed ? "" : " · everyday"}`,
  }));
  barChart($("#hour-chart"), data, { labelEvery: 3 });
}

// How much is left for the rest of the month: from what came in, and from the budgets set.
// A finished month reads as that month in review.
function renderLeft(s) {
  const el = $("#left-card");
  const [y, m] = s.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const current = inProgress(s.month);
  const daysLeft = current ? Math.max(0, days - elapsedDays(s)) : 0;
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
  const name = monthName(s.month).split(" ")[0];
  const review = !current ? insightsFor(s.month)?.review || [] : [];
  const title = current ? "Left for the rest of the month"
    : review.length ? `${name} in review` : left >= 0 ? `Left over in ${name}` : `Over in ${name}`;
  const perDay = current && daysLeft > 0 && left > 0 ? `About <b>${money(left / daysLeft)}</b> a day for the next ${plural(daysLeft, "day")}` :
    current && daysLeft === 0 ? "Last day of the month" : left < 0 ? "You spent more than came in" : review.length ? `${left >= 0 ? "Left over" : "Over"} · ${money(Math.abs(left))}` : "";
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
      ${review.length ? `<ul class="review" aria-label="${esc(name)} in review">${review.map((l, i) => `<li><button class="insight" data-i="${i}"><span class="insight-text">${insightText(l)}</span></button></li>`).join("")}</ul>` : ""}
    </div>
    <div class="left-side">
      ${income ? `<div><p>Came in</p><strong>${money(income)}</strong></div>` : ""}
      ${budgetTotal ? (budgetUsed > budgetTotal
        ? `<div><p>Budgets</p><strong class="delta-up">Over by ${money(budgetUsed - budgetTotal)}</strong><small>of ${money(budgetTotal)}</small></div>`
        : `<div><p>Budgets left</p><strong>${money(budgetTotal - budgetUsed)}</strong><small>of ${money(budgetTotal)}</small></div>`) : ""}
      ${income ? `<div><p>Saved this month</p><strong>${money(aside)}</strong><small>${aside ? "moved to your savings" : "nothing put aside yet"}</small></div>` : ""}
    </div>`;
  $$(".review .insight", el).forEach((b) => b.addEventListener("click", () => {
    const l = review[+b.dataset.i];
    if (l.to === "category" && l.category) return openCategory(l.category);
    state.cat = null; state.q = "";
    const search = $("#search"); if (search) search.value = "";
    go("activity");
  }));
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
