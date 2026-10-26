// Trends tab. Loaded after shared.js.
"use strict";


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
  const moved = t.moved || t.months.map(() => 0);
  const saved = sum(moved), left = sum(t.received) - sum(t.spent) - saved;
  $("#flow-stats").innerHTML = [
    ["Average spent", money(avgOut)],
    ["Average came in", avgIn ? money(avgIn) : "—"],
    ["Saved in total", `${money(saved)}${sum(t.received) ? ` <small class="muted">${Math.round((saved / sum(t.received)) * 100)}% of income</small>` : ""}`],
  ].map(([p, v]) => `<div><p>${p}</p><strong>${v}</strong></div>`).join("");
  lineChart($("#flow-chart"), labels,
    sum(t.received) ? [{ name: "Came in", values: t.received, cls: "income", dots: true }] : [],
    { bars: { name: "Spent", values: t.spent.map((v) => Math.max(0, v)) }, tipTitle: (i) => { const l = t.received[i] - t.spent[i] - moved[i];
      return `${full(i)} · saved ${money(moved[i])} · ${l >= 0 ? `${money(l)} left` : `${money(-l)} over`}`; } });

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
