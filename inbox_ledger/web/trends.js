// Trends tab. Loaded after shared.js and overview.js (fixedKeys, isFixed, inProgress, markOpenBar).
"use strict";


// ---------- trends ----------
async function loadTrends() {
  const months = state.trendMonths || 12;
  $$("#trend-range button").forEach((b) => b.classList.toggle("on", +b.dataset.months === months));
  const [t, extra] = await Promise.all([
    api(`/api/trends?month=${state.month}&months=${months}`),
    api(`/api/insights?month=${state.month}&months=${months}`).catch(() => null),  // everyday-only series
  ]);
  state.trends = t;
  state.trendsExtra = extra && extra.months?.join() === t.months.join() ? extra : null;
  // "12 months" only means twelve when there are that many.
  const have = state.meta.months.length;
  $$("#trend-range button").forEach((b) => {
    const n = +b.dataset.months;
    b.textContent = have < n ? `All · ${plural(have, "month")}` : `${n} months`;
  });
  renderTrends();
}

function renderTrends() {
  const t = state.trends, x = state.trendsExtra;
  if (!t || !t.months.length) return;
  const labels = t.months.map((m) => monthName(m, "short"));
  const full = (i) => monthName(t.months[i]);
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const moved = t.moved || t.months.map(() => 0);
  const last = t.months[t.months.length - 1];
  const open = inProgress(last) ? t.months.length - 1 : -1;  // the month still running
  const closed = t.months.map((_, i) => i).filter((i) => i !== open);
  const avgOut = sum(closed.map((i) => t.spent[i])) / Math.max(1, closed.length);
  const avgIn = sum(closed.map((i) => t.received[i])) / Math.max(1, closed.length);
  const saved = sum(moved), left = sum(t.received) - sum(t.spent) - saved;
  const n = plural(t.months.length, "month");
  $("#flow-stats").innerHTML = [
    ["Average spent", money(avgOut), open >= 0 ? `${plural(closed.length, "finished month")}` : `Over ${n}`],
    ["Average came in", avgIn ? money(avgIn) : "—", avgIn ? (open >= 0 ? `${plural(closed.length, "finished month")}` : `Over ${n}`) : ""],
    ["Saved", money(saved), sum(t.received) ? `${Math.round((saved / sum(t.received)) * 100)}% of income · moved to savings` : "Moved to savings"],
    [left >= 0 ? "Left" : "Over", money(Math.abs(left)), sum(t.received) ? "Came in − spent − saved" : ""],
  ].map(([p, v, sm]) => `<div><p>${p}</p><strong>${v}</strong>${sm ? `<small class="muted">${sm}</small>` : ""}</div>`).join("");
  lineChart($("#flow-chart"), labels,
    sum(t.received) ? [{ name: "Came in", values: t.received, cls: "income", dots: true }] : [],
    { bars: { name: "Spent", values: t.spent.map((v) => Math.max(0, v)) }, tipTitle: (i) => { const l = t.received[i] - t.spent[i] - moved[i];
      return `${full(i)}${i === open ? " so far" : ""} · saved ${money(moved[i])} · ${l >= 0 ? `${money(l)} left` : `${money(-l)} over`}`; } });
  markOpenBar($("#flow-chart"), open);

  // Fixed categories (rent, bills, subscriptions) start hidden: they flatten everything else.
  const keys = Object.keys(t.categories).sort((a, b) => sum(t.categories[b]) - sum(t.categories[a]));
  if (!state.trendOn) state.trendOn = new Set(keys.filter((k) => k !== "other" && !isFixed(k)).slice(0, 5));
  $("#trend-chips").innerHTML = keys.map((k) =>
    `<button class="chip ${state.trendOn.has(k) ? "" : "off"}" data-cat="${esc(k)}" aria-pressed="${state.trendOn.has(k)}"><span class="dot" style="background:${color(k)}"></span>${esc(catName(k))}</button>`).join("");
  $$("#trend-chips .chip").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.cat;
    state.trendOn.has(k) ? state.trendOn.delete(k) : state.trendOn.add(k);
    renderTrends();
  }));
  lineChart($("#cat-chart"), labels,
    keys.map((k) => ({ name: catName(k), values: t.categories[k].map((v) => Math.max(0, v)), color: color(k), off: !state.trendOn.has(k) })),
    { tipTitle: (i) => `${full(i)}${i === open ? " so far" : ""}` });

  // Weekdays: everyday spending, so one rent day doesn't crown a weekday.
  const everyday = x?.weekday_everyday;
  const weekday = everyday || t.weekday;
  $("#weekday-note").textContent = everyday ? "Everyday spending · average per day" : "Average per day";
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], top = Math.max(...weekday);
  barChart($("#weekday-chart"), weekday.map((v, i) => ({
    label: days[i], value: v, hi: v === top && v > 0, tip: `<b>${money(v)}</b>Average ${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i]}${everyday ? " · everyday" : ""}`,
  })));
}
