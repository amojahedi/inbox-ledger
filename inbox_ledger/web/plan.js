// Plan: the days ahead of the month in progress. Loaded after app.js and uses its helpers
// (state, api, money, esc, avatar, color, catName, showTip, hideTip, niceMax, nf0, toast, go, setMonth).
"use strict";

(() => {
  let P = null;          // the plan for P.month, as the server sent it, plus local edits
  let seq = 0;           // only the newest response is drawn
  const saveTimers = {};
  const R = Math.round;  // whole currency units everywhere, so every sum on screen adds up
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const signed = (v) => `${v < 0 ? "−" : ""}${money(Math.abs(v))}`;
  const D = (iso) => new Date(`${iso}T00:00`);
  const fmt = (iso, o) => D(iso).toLocaleDateString("en-US", o);
  const dayShort = (iso) => fmt(iso, { month: "short", day: "numeric" });
  const monthOnly = (iso) => fmt(iso, { month: "long" });
  const addDays = (iso, n) => { const d = D(iso); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const dayLabel = (iso, long = true) => {
    if (iso === P.today) return "Today";
    if (iso === addDays(P.today, 1)) return "Tomorrow";
    return fmt(iso, long ? { weekday: "long", month: "long", day: "numeric" } : { weekday: "short", month: "short", day: "numeric" });
  };
  const view = () => document.getElementById("view-plan");

  let inflight = null;  // Overview and the Plan tab often ask for the same month at once: share one request
  // Example data shows its latest month as finished (like the Overview), so the plan looks at the next one.
  function planTarget(month) {
    if (!(state.meta?.source?.demo && month === state.meta.current)) return { month, asOf: "" };
    const [y, m] = month.split("-").map(Number);
    const next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
    return { month: next, asOf: `&today=${next}-01` };
  }

  async function fetchPlan(shown, fresh = false) {
    const { month, asOf } = planTarget(shown);
    const n = ++seq;
    if (fresh || !inflight || inflight.month !== month) {
      const req = { month, p: api(`/api/plan?month=${month}${asOf}`) };
      inflight = req;
      req.p.finally(() => { if (inflight === req) inflight = null; }).catch(() => {});
    }
    const p = await inflight.p;
    if (n !== seq) return null;
    P = p;
    if (P.status !== "past") recompute();
    return P;
  }

  // ---------- arithmetic (mirrors plan.py, so edits show instantly) ----------
  function recompute() {
    const t = P.totals, counted = P.items.filter((x) => x.counts);
    t.expected_in = sum(counted.filter((x) => x.direction === "in").map((x) => R(x.amount)));
    t.expected = sum(counted.filter((x) => x.direction === "out" && x.kind !== "planned").map((x) => R(x.amount)));
    t.planned = sum(counted.filter((x) => x.kind === "planned").map((x) => R(x.amount)));
    t.allowances = sum(P.allowances.map((a) => a.amount));
    t.goal = P.goal.amount;
    t.buffer = t.money_in + t.expected_in - t.spent - t.expected - t.planned - t.allowances - t.goal;
    const perDay = t.allowances / P.days_left;
    let level = t.money_in - t.spent - t.goal;
    for (const d of P.daily) {
      d.allowance = perDay;
      if (d.actual !== undefined && d.projected === undefined) continue;
      const today = counted.filter((x) => x.date === d.day);
      d.items = today.map((x) => ({ name: x.name, amount: R(x.amount), direction: x.direction }));
      level += sum(d.items.map((x) => (x.direction === "in" ? x.amount : -x.amount))) - perDay;
      d.projected = level;
    }
    const last = P.daily[P.daily.length - 1];
    if (last && last.projected !== undefined) last.projected = t.buffer;
    P.allowances.forEach((a) => (a.per_day = a.amount / P.days_left));
  }

  // ---------- Overview: Coming up ----------
  function upcoming() {
    return P.items.filter((x) => x.included && !x.passed && x.status !== "missed" && x.date >= P.as_of)
      .sort((a, b) => a.date.localeCompare(b.date));
  }

  function renderCard() {
    const el = document.getElementById("coming-up");
    if (!el) return;
    const list = P && P.status !== "past" && P.month === state.month ? upcoming() : [];
    el.hidden = !list.length;
    if (!list.length) return;
    const t = P.totals, end = dayShort(P.end);
    el.innerHTML = `
      <div class="card-head"><h2>Coming up</h2><button class="link" data-plan-open>Open plan</button></div>
      <p class="cu-verdict ${t.buffer < 0 ? "short" : ""}">${t.buffer < 0 ? `Short by <b>${money(-t.buffer)}</b> by ${esc(end)}` : `<b>${money(t.buffer)}</b> to spare by ${esc(end)}`}</p>
      <ol class="cu-list">${list.slice(0, 5).map((x) => `
        <li>${avatar(x.name, x.brand, x.direction === "in" ? "var(--good)" : color(x.category), "sm")}
          <span class="cu-main"><span class="cu-name">${esc(x.name)}</span><small>${esc(dayLabel(x.date, false))} · ${esc(x.kind === "planned" ? "Planned" : x.kind === "paylater" ? x.provider || "Pay later" : catName(x.category))}</small></span>
          <span class="cu-amt ${x.direction}">${x.direction === "in" ? "+" : ""}${money(x.amount)}</span></li>`).join("")}</ol>
      ${list.length > 5 ? `<p class="cu-more">${plural(list.length - 5, "more item")} through ${esc(dayShort(P.horizon))}</p>` : ""}`;
    el.querySelector("[data-plan-open]").addEventListener("click", () => go("plan"));
  }

  window.renderComingUp = async (s) => {
    try { if (!(await fetchPlan(s.month))) return; } catch { const el = document.getElementById("coming-up"); if (el) el.hidden = true; return; }
    renderCard();
    if (state.view === "plan") renderPlan();
  };

  window.loadPlan = async (fresh = false) => {
    if (!state.meta.months.length) return renderEmpty("Nothing to plan yet", "Bring in your bank’s alert emails and Ledger will look ahead for you.");
    try { if (!(await fetchPlan(state.month, fresh))) return; } catch (e) { return renderEmpty("Couldn’t load the plan", e.message); }
    renderPlan(); renderCard();
  };

  // ---------- Plan view ----------
  function renderEmpty(title, text, action = "") {
    view().innerHTML = `<div class="empty-state plan-empty"><div class="empty-art" aria-hidden="true">${calendarArt()}</div>
      <h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div>`;
    view().querySelector("[data-latest]")?.addEventListener("click", () => setMonth(state.meta.current));
  }

  function calendarArt() {
    return `<svg viewBox="0 0 64 64" width="64" height="64"><rect x="10" y="14" width="44" height="40" rx="9" fill="var(--fill-strong)"/><rect x="10" y="14" width="44" height="12" rx="6" fill="var(--c-red)"/><rect x="10" y="20" width="44" height="6" fill="var(--c-red)"/><circle cx="24" cy="38" r="3.2" fill="var(--text-3)"/><circle cx="34" cy="38" r="3.2" fill="var(--accent)"/><circle cx="44" cy="38" r="3.2" fill="var(--text-3)"/><circle cx="24" cy="47" r="3.2" fill="var(--text-3)"/></svg>`;
  }

  function renderPlan() {
    if (!P || P.month !== state.month) return;
    if (P.status === "past") {
      const latest = state.meta.current, name = monthName(P.month).split(" ")[0];
      return latest !== P.month
        ? renderEmpty(`${name} is over`, `A plan looks at the days ahead. Open ${monthName(latest)} to plan the rest of it.`,
          `<div class="empty-actions"><button class="btn primary" data-latest>Plan ${esc(monthName(latest).split(" ")[0])}</button></div>`)
        : renderEmpty(`${name} is over`, `Plans start once alerts for ${monthName(P.today.slice(0, 7))} arrive.`);
    }
    const name = monthName(P.month).split(" ")[0];
    view().innerHTML = `
      <div class="hero small plan-hero">
        <p class="eyebrow" id="plan-eyebrow"></p>
        <h1 class="hero-number plan-buffer" id="plan-buffer"></h1>
        <p class="plan-verdict" id="plan-verdict" aria-live="polite"></p>
        <p class="plan-when">${esc(dayShort(P.as_of))}${P.days_left > 1 ? `–${+P.end.slice(8)}` : ""} · after allowances and your savings goal</p>
      </div>
      <div class="grid-2 plan-top">
        <div class="card plan-sum-card">
          <div class="card-head"><h2>How it adds up</h2><span class="muted">${esc(name)}</span></div>
          <dl class="plan-sum" id="plan-sum"></dl>
        </div>
        <div class="card">
          <div class="card-head"><h2>Day by day</h2>
            <span class="legend-inline"><span class="key plan-key-actual"></span>So far<span class="key plan-key-plan"></span>Plan</span></div>
          <div class="chart plan-chart" id="plan-chart" data-label="Money left after savings, day by day to the end of ${esc(name)}"></div>
          <p class="plan-chart-note">Money left after your savings goal, at the end of each day.</p>
        </div>
      </div>
      <div class="plan-cols">
        <div class="card flush plan-timeline-card">
          <div class="card-head padded"><h2>Days ahead</h2><button class="btn secondary small" id="plan-add">＋ Add a one-off</button></div>
          <ul class="plan-timeline" id="plan-timeline"></ul>
          <div id="plan-paid"></div>
        </div>
        <div class="plan-side">
          <div class="card" id="plan-allow-card"></div>
          <div class="card" id="plan-goal-card"></div>
          <p class="plan-reset"><button class="link small" id="plan-reset">Reset ${esc(name)}’s plan</button></p>
        </div>
      </div>`;
    view().querySelector("#plan-add").addEventListener("click", (e) => openSheet(null, e.currentTarget));
    view().querySelector("#plan-reset").addEventListener("click", resetPlan);
    renderNumbers(); renderTimeline(); renderAllowances(); renderGoal();
  }

  // Everything that changes while a slider moves.
  function renderNumbers() {
    const t = P.totals, end = dayShort(P.end), short = t.buffer < 0;
    const $v = (id) => document.getElementById(id);
    if (!$v("plan-buffer")) return;
    $v("plan-eyebrow").textContent = `Rest of ${monthName(P.month).split(" ")[0]} · ${plural(P.days_left, "day")} left`;
    $v("plan-buffer").innerHTML = `<span class="ccy">${esc(P.currency)}</span>${nf0.format(Math.abs(t.buffer))}`;
    $v("plan-buffer").classList.toggle("short", short);
    $v("plan-verdict").className = `plan-verdict ${short ? "short" : "good"}`;
    $v("plan-verdict").innerHTML = short
      ? `Short by ${money(-t.buffer)} — lower an allowance or the goal`
      : `On track: ${money(t.buffer)} to spare`;
    const n = (k) => P.items.filter((x) => x.counts && k(x)).length;
    const nExp = n((x) => x.direction === "out" && x.kind !== "planned"), nPlan = n((x) => x.kind === "planned");
    const nAllow = P.allowances.filter((a) => a.amount > 0).length;
    const rows = [
      ["Came in this month", "", t.money_in, ""],
      t.expected_in ? ["Still to come in", "+", t.expected_in, plural(n((x) => x.direction === "in"), "payment")] : null,
      ["Spent so far", "−", t.spent, `${dayShort(P.start)} – today`],
      ["Expected charges", "−", t.expected, nExp ? plural(nExp, "bill") : `None left in ${monthName(P.month).split(" ")[0]}`],
      ["Planned one-offs", "−", t.planned, nPlan ? plural(nPlan, "item") : "None yet"],
      ["Allowances", "−", t.allowances, nAllow ? `${plural(nAllow, "category", "categories")} · ${money(t.allowances / P.days_left)} a day` : "None"],
      ["Savings goal", "−", t.goal, t.goal > P.goal.moved ? `${money(P.goal.moved)} moved, ${money(t.goal - P.goal.moved)} to go` : P.goal.moved ? `${money(P.goal.moved)} already moved` : ""],
    ].filter(Boolean);
    $v("plan-sum").innerHTML = rows.map(([label, op, v, sub]) => `
      <div class="ps-row"><dt>${esc(label)}${sub ? `<small>${esc(sub)}</small>` : ""}</dt>
        <dd><span class="ps-op" aria-hidden="true">${op}</span><span class="visually-hidden">${op === "−" ? "minus" : op === "+" ? "plus" : ""}</span>${money(v)}</dd></div>`).join("") + `
      <div class="ps-row ps-total ${short ? "short" : "good"}"><dt>${short ? "Short by" : "To spare"}</dt>
        <dd><span class="ps-op" aria-hidden="true">=</span>${short ? "−" : ""}${money(Math.abs(t.buffer))}</dd></div>`;
    chart();
    renderCard();
  }

  // ---------- chart: money left, day by day ----------
  function chart() {
    const el = document.getElementById("plan-chart");
    if (!el || !el.clientWidth) return;
    const W = el.clientWidth, H = el.clientHeight, pad = { t: 14, r: 10, b: 22, l: 48 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b, d = P.daily, n = d.length;
    const val = (p) => (p.actual !== undefined && p.projected === undefined ? p.actual : p.projected);
    const vals = d.map(val);
    const hi0 = Math.max(0, ...vals), lo0 = Math.min(0, ...vals);
    const hi = niceMax(hi0 || 1), lo = lo0 < 0 ? -niceMax(-lo0) : 0;
    const step = iw / n, x = (i) => pad.l + step * i + step / 2, y = (v) => pad.t + ih - ((v - lo) / (hi - lo)) * ih;
    // Keep the labels apart: a small dip below zero gets the zero line but no label of its own.
    const ticks = lo < 0 ? (y(lo) - y(0) > 16 ? [lo, 0, hi] : [0, hi]) : [0, hi / 2, hi];
    const k = (t) => (Math.abs(t) >= 1000 ? `${t < 0 ? "−" : ""}${+(Math.abs(t) / 1000).toFixed(1)}k` : nf0.format(t));
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(el.dataset.label)}. Ends at ${esc(signed(P.totals.buffer))}."><g class="grid">`;
    for (const t of ticks) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}" ${t === 0 && lo < 0 ? 'class="zero"' : ""}/>`;
    svg += `</g><g class="axis">`;
    for (const t of ticks) svg += `<text x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${k(t)}</text>`;
    const every = n > 20 ? (W < 520 ? 10 : 5) : 1;
    d.forEach((p, i) => { const day = i + 1; if (day === 1 || day % every === 0) svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${day}</text>`; });
    svg += `</g>`;
    const ti = d.findIndex((p) => p.day === P.as_of);
    if (lo < 0) svg += `<rect class="below" x="${pad.l}" y="${y(0)}" width="${iw}" height="${y(lo) - y(0)}"/>`;
    if (ti >= 0) svg += `<line class="today" x1="${x(ti) - step / 2}" x2="${x(ti) - step / 2}" y1="${pad.t}" y2="${pad.t + ih}"/><text class="today-label" x="${x(ti) - step / 2 + 4}" y="${pad.t + 9}">Today</text>`;
    const path = (idx) => idx.map((i, j) => `${j ? "L" : "M"}${x(i).toFixed(1)},${y(vals[i]).toFixed(1)}`).join("");
    const actual = d.map((p, i) => i).filter((i) => d[i].projected === undefined);
    const planned = d.map((p, i) => i).filter((i) => d[i].projected !== undefined);
    if (actual.length) svg += `<path class="pl-actual" d="${path(actual)}"/>`;
    if (planned.length) {
      const from = actual.length ? [actual[actual.length - 1]] : [];
      svg += `<path class="pl-plan ${P.totals.buffer < 0 ? "short" : ""}" d="${path([...from, ...planned])}"/>`;
      planned.filter((i) => d[i].items?.length).forEach((i) => { svg += `<circle class="pl-mark ${P.totals.buffer < 0 ? "short" : ""}" cx="${x(i)}" cy="${y(vals[i])}" r="3.5"/>`; });
      const li = planned[planned.length - 1];
      svg += `<circle class="pl-end ${P.totals.buffer < 0 ? "short" : ""}" cx="${x(li)}" cy="${y(vals[li])}" r="4.5"/>`;
    }
    svg += `<line class="cross" x1="0" x2="0" y1="${pad.t}" y2="${pad.t + ih}" visibility="hidden"/>`;
    d.forEach((_, i) => { svg += `<rect class="hit" data-i="${i}" x="${pad.l + step * i}" y="${pad.t}" width="${step}" height="${ih}"/>`; });
    el.innerHTML = svg + "</svg>";
    const cross = el.querySelector(".cross");
    el.querySelectorAll(".hit").forEach((h) => {
      const i = +h.dataset.i, p = d[i];
      h.addEventListener("mouseenter", (e) => {
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
        const head = `<b>${signed(vals[i])}</b>${esc(fmt(p.day, { weekday: "short", month: "short", day: "numeric" }))} · ${p.projected === undefined ? "left at day’s end" : "planned"}`;
        const rows = p.projected === undefined ? "" : [
          ...(p.items || []).map((it) => `<div class="tip-row"><span>${esc(it.name)}</span><span>${it.direction === "in" ? "+" : "−"}${money(it.amount)}</span></div>`),
          p.allowance ? `<div class="tip-row"><span>Allowances</span><span>−${money(p.allowance)}</span></div>` : "",
          p.day === P.as_of && P.totals.goal !== P.goal.moved ? `<div class="tip-row"><span>${P.totals.goal > P.goal.moved ? "Rest of savings goal" : "Back from savings"}</span><span>${P.totals.goal > P.goal.moved ? "−" : "+"}${money(Math.abs(P.totals.goal - P.goal.moved))}</span></div>` : "",
        ].join("");
        showTip(e, head + rows);
      });
      h.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    });
  }

  // ---------- timeline ----------
  function itemRow(x, extra = "") {
    const off = !x.included || x.status === "missed" || x.passed;
    const why = !x.included && x.status !== "missed" ? "Won’t happen this month"
      : x.status === "missed" ? `Usually ${dayShort(x.usual)} · not seen this month`
      : x.passed ? `Planned for ${dayShort(x.date)} · date passed`
      : x.status === "late" ? `Was due ${dayShort(x.usual)} · not seen yet`
      : shortNote(x);
    const sign = x.direction === "in" ? "+" : "";
    const label = `${x.name}, ${x.direction === "in" ? "receiving" : "paying"} ${money(x.amount)}, ${dayLabel(x.date)}. ${why}. Edit`;
    return `<li class="pt-row ${off ? "off" : ""} ${extra}" tabindex="0" role="button" data-key="${esc(x.key)}" aria-label="${esc(label)}">
      ${avatar(x.name, x.brand, x.direction === "in" ? "var(--good)" : color(x.category))}
      <span class="pt-main"><span class="pt-name">${esc(x.name)}${x.edited ? `<span class="pt-tag">Edited</span>` : ""}</span>
        <span class="pt-sub"><span class="dot" style="background:${x.direction === "in" ? "var(--good)" : color(x.category)}"></span>${esc(x.kind === "income" ? "Income" : catName(x.category))} · ${esc(why)}</span></span>
      <span class="pt-amt ${x.direction}">${sign}${money(x.amount)}${x.edited && x.suggested != null && R(x.suggested) !== R(x.amount) ? `<small>usually ${money(x.suggested)}</small>` : ""}</span>
    </li>`;
  }

  // "Usually on the 2nd · 4 of the last 4 months · USD 15.49" → "Monthly, usually the 2nd" (the sheet has the rest).
  function shortNote(x) {
    if (x.kind === "planned") return "Planned by you";
    const parts = x.note.split(" · ");
    if (x.kind === "paylater") return parts.filter((p) => !/^date estimated$/.test(p)).join(" · ").replace("instalment ", "") + (/estimated/.test(x.note) ? " · about" : "");
    return `Monthly, ${parts[0].replace("Usually on", "usually")}`;
  }

  function renderTimeline() {
    const el = document.getElementById("plan-timeline");
    const ahead = P.items.filter((x) => x.status !== "missed" && !x.passed && x.date >= P.as_of).sort((a, b) => a.date.localeCompare(b.date));
    const notCounted = P.items.filter((x) => x.status === "missed" || x.passed);
    let html = "", month = P.month;
    const groups = new Map();
    ahead.forEach((x) => { if (!groups.has(x.date)) groups.set(x.date, []); groups.get(x.date).push(x); });
    if (!ahead.some((x) => x.date <= P.end)) {
      html += `<li class="pt-none"><strong>Nothing else due in ${esc(monthName(P.month).split(" ")[0])}</strong><span>Every regular bill has been paid. Your allowances cover the rest.</span></li>`;
    }
    for (const [day, list] of groups) {
      if (day.slice(0, 7) !== month) {
        month = day.slice(0, 7);
        html += `<li class="pt-break"><span>${esc(monthOnly(day))}</span><small>Not in ${esc(monthName(P.month).split(" ")[0])}’s numbers</small></li>`;
      }
      const out = sum(list.filter((x) => x.included && x.direction === "out").map((x) => R(x.amount)));
      html += `<li class="tx-day pt-day"><span>${esc(dayLabel(day))}</span><span>${out ? money(out) : ""}</span></li>`;
      html += list.map((x) => itemRow(x)).join("");
    }
    if (notCounted.length) {
      html += `<li class="tx-day pt-day"><span>Not in the plan</span><span></span></li>` + notCounted.map((x) => itemRow(x)).join("");
    }
    el.innerHTML = html;
    el.querySelectorAll(".pt-row").forEach((li) => {
      const open = () => openSheet(P.items.find((x) => x.key === li.dataset.key), li);
      li.addEventListener("click", open);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
    const paid = P.paid.filter((x) => x.direction === "out");
    document.getElementById("plan-paid").innerHTML = paid.length ? `
      <details class="plan-paid">
        <summary><span>Already paid this month</span><span class="muted">${plural(paid.length, "regular bill")} · ${money(sum(paid.map((x) => x.amount)))}</span></summary>
        <ul>${paid.map((x) => `<li>${avatar(x.name, x.brand, color(x.category), "sm")}<span class="pp-name">${esc(x.name)}<small>${esc(dayShort(x.date))} · ${esc(catName(x.category))}</small></span><span class="pp-amt">${money(x.amount)}</span></li>`).join("")}</ul>
      </details>` : "";
  }

  // ---------- allowances ----------
  const stepFor = (a) => (Math.max(a.typical, a.amount) > 1500 ? 50 : Math.max(a.typical, a.amount) > 300 ? 10 : 5);
  const maxFor = (a) => niceMax(Math.max(a.suggested * 2, a.amount * 1.25, a.typical / 4, 50));

  function allowRow(a) {
    const max = maxFor(a), name = catName(a.category);
    const over = a.typical - a.spent - a.expected;
    const math = `Typical ${nf0.format(a.typical)} − spent ${nf0.format(a.spent)}${a.expected ? ` − expected ${nf0.format(a.expected)}` : ""} = ${over < 0 ? `0, over by ${nf0.format(-over)}` : nf0.format(a.suggested)}`;
    return `<li class="al-row" data-cat="${esc(a.category)}" style="--tint:${color(a.category)}">
      <div class="al-top">
        <span class="dot" style="background:${color(a.category)}"></span>
        <span class="al-name">${esc(name)}${a.edited ? `<button class="link al-undo" data-undo aria-label="Back to the suggested ${esc(name)} allowance, ${money(a.suggested)}">Suggested ${money(a.suggested)}</button>` : ""}</span>
        <span class="al-amt" data-amt>${money(a.amount)}</span>
      </div>
      <div class="al-sub"><span>${esc(math)}</span><span data-perday>${perDay(a)}</span></div>
      <div class="al-ctl">
        <input type="range" class="plan-range" min="0" max="${max}" step="${stepFor(a)}" value="${a.amount}" aria-label="${esc(name)} allowance" aria-valuetext="${esc(`${money(a.amount)}, ${perDay(a)}`)}" style="--p:${(a.amount / max) * 100}%">
        <span class="stepper" role="group" aria-label="${esc(name)} allowance">
          <button type="button" data-step="-1" aria-label="Lower ${esc(name)} by ${stepFor(a)}">−</button>
          <button type="button" data-step="1" aria-label="Raise ${esc(name)} by ${stepFor(a)}">+</button>
        </span>
      </div>
    </li>`;
  }
  const perDay = (a) => (a.amount ? `${money(a.amount / P.days_left)} a day` : "Nothing more");

  function renderAllowances() {
    const el = document.getElementById("plan-allow-card");
    const live = P.allowances.filter((a) => a.amount > 0 || a.suggested > 0 || a.edited);
    const spent = P.allowances.filter((a) => !live.includes(a));
    const months = P.typical_months.length ? `${monthName(P.typical_months[0], "short")}–${monthName(P.typical_months[P.typical_months.length - 1], "short")}` : "";
    el.innerHTML = `
      <div class="card-head"><h2>Allowances</h2><span class="muted">${money(P.totals.allowances)} · ${money(P.totals.allowances / P.days_left)} a day</span></div>
      <p class="plan-intro">What you can still spend on each category until ${esc(dayShort(P.end))}. Each starts from your typical month${months ? ` (${esc(months)} average)` : ""}, less what’s spent and what’s expected.</p>
      <ul class="al-list">${live.map(allowRow).join("") || `<li class="muted">No typical spending to go on yet.</li>`}</ul>
      ${spent.length ? `<details class="al-more"><summary>${plural(spent.length, "category", "categories")} already at a typical month</summary><ul class="al-list">${spent.map(allowRow).join("")}</ul></details>` : ""}`;
    el.querySelectorAll(".al-row").forEach(wireAllowance);
  }

  function wireAllowance(row) {
    const a = P.allowances.find((x) => x.category === row.dataset.cat);
    const range = row.querySelector("input");
    const update = (v, save = true) => {
      a.amount = Math.max(0, R(v));
      a.edited = a.amount !== a.suggested;
      if (a.amount > +range.max) range.max = niceMax(a.amount);
      range.value = a.amount;
      range.style.setProperty("--p", `${(a.amount / +range.max) * 100}%`);
      row.querySelector("[data-amt]").textContent = money(a.amount);
      row.querySelector("[data-perday]").textContent = perDay(a);
      range.setAttribute("aria-valuetext", `${money(a.amount)}, ${perDay(a)}`);
      recompute(); renderNumbers();
      const head = document.querySelector("#plan-allow-card .card-head .muted");
      if (head) head.textContent = `${money(P.totals.allowances)} · ${money(P.totals.allowances / P.days_left)} a day`;
      if (save) persist(`allow:${a.category}`, () => api(`/api/plan/allowances/${encodeURIComponent(a.category)}`,
        { method: "PUT", body: JSON.stringify({ month: P.month, amount: a.amount === a.suggested ? null : a.amount }) }));
    };
    range.addEventListener("input", () => update(+range.value));
    range.addEventListener("change", () => renderAllowancesKeepFocus(a.category, "input"));
    row.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
      update(a.amount + +b.dataset.step * +range.step);
      renderAllowancesKeepFocus(a.category, `[data-step="${b.dataset.step}"]`);
    }));
    row.querySelector("[data-undo]")?.addEventListener("click", () => { update(a.suggested); renderAllowancesKeepFocus(a.category, "input"); });
  }

  // Re-draw (to show or hide "Suggested") without losing the user's place.
  function renderAllowancesKeepFocus(cat, sel) {
    const open = document.querySelector("#plan-allow-card details")?.open;
    renderAllowances();
    const d = document.querySelector("#plan-allow-card details"); if (d && open) d.open = true;
    document.querySelector(`#plan-allow-card .al-row[data-cat="${CSS.escape(cat)}"] ${sel}`)?.focus({ preventScroll: true });
  }

  function persist(key, fn) {
    clearTimeout(saveTimers[key]);
    saveTimers[key] = setTimeout(() => fn().catch((e) => toast(e.message)), 350);
  }

  // ---------- savings goal ----------
  function renderGoal() {
    const el = document.getElementById("plan-goal-card"), g = P.goal;
    const max = niceMax(Math.max(P.totals.money_in + P.totals.expected_in, g.amount, g.moved, 1000));
    const note = g.amount > g.moved ? `${money(g.moved)} already moved to your own accounts · ${money(g.amount - g.moved)} still to move`
      : g.moved ? `${money(g.moved)} already moved to your own accounts this month${g.amount < g.moved ? `, ${money(g.moved - g.amount)} more than this goal` : ""}`
      : "Nothing moved to your own accounts yet this month";
    el.innerHTML = `
      <div class="card-head"><h2>Savings goal</h2>${g.edited ? `<button class="link small" data-undo>Use ${money(g.suggested)}</button>` : ""}</div>
      <div class="goal-top"><span class="goal-amt" data-amt>${money(g.amount)}</span>
        <span class="stepper" role="group" aria-label="Savings goal">
          <button type="button" data-step="-1" aria-label="Lower the goal by 100">−</button>
          <button type="button" data-step="1" aria-label="Raise the goal by 100">+</button>
        </span></div>
      <input type="range" class="plan-range" min="0" max="${max}" step="100" value="${g.amount}" aria-label="Savings goal for ${esc(monthName(P.month).split(" ")[0])}" aria-valuetext="${esc(money(g.amount))}" style="--p:${(g.amount / max) * 100}%;--tint:var(--good)">
      <p class="plan-intro" data-note>${esc(note)}</p>`;
    const range = el.querySelector("input");
    const update = (v) => {
      g.amount = Math.max(0, R(v)); g.edited = g.amount !== g.suggested;
      range.value = g.amount; range.style.setProperty("--p", `${(g.amount / +range.max) * 100}%`);
      range.setAttribute("aria-valuetext", money(g.amount));
      el.querySelector("[data-amt]").textContent = money(g.amount);
      recompute(); renderNumbers();
      persist("goal", () => api("/api/plan/goal", { method: "PUT", body: JSON.stringify({ month: P.month, amount: g.edited ? g.amount : null }) }));
    };
    range.addEventListener("input", () => update(+range.value));
    range.addEventListener("change", () => { renderGoal(); document.querySelector("#plan-goal-card input").focus({ preventScroll: true }); });
    el.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
      update(g.amount + +b.dataset.step * 100); renderGoal();
      document.querySelector(`#plan-goal-card [data-step="${b.dataset.step}"]`).focus({ preventScroll: true });
    }));
    el.querySelector("[data-undo]")?.addEventListener("click", () => { update(g.suggested); renderGoal(); });
  }

  async function resetPlan() {
    if (!confirm(`Reset ${monthName(P.month)}? Allowances, the savings goal and changes to expected charges go back to Ledger’s suggestions. Your one-offs stay.`)) return;
    await api(`/api/plan/reset?month=${P.month}`, { method: "POST" });
    toast("Plan reset");
    await window.loadPlan(true);
  }

  // ---------- sheet: add or edit an item ----------
  let sheet, scrim, editing = null;

  function ensureSheet() {
    if (sheet) return;
    scrim = Object.assign(document.createElement("div"), { className: "scrim", hidden: true });
    sheet = Object.assign(document.createElement("div"), { className: "sheet plan-sheet", hidden: true });
    sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-modal", "true"); sheet.setAttribute("aria-labelledby", "ps-title");
    document.body.append(scrim, sheet);
    scrim.addEventListener("click", closeSheet);
    sheet.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.stopPropagation(); return closeSheet(); }
      if (e.key !== "Tab") return;
      const f = [...sheet.querySelectorAll("button, input, select, [tabindex]")].filter((x) => !x.closest("[hidden]") && !x.disabled);
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    });
  }

  function openSheet(x, from) {
    ensureSheet();
    const planned = !x || x.kind === "planned", isNew = !x;
    editing = { x, from, planned, category: x?.category || "dining" };
    const detected = !planned;
    const happens = detected ? (x.status === "missed" ? x.state === "include" : x.state !== "skip") : true;
    const cats = state.meta.categories.filter((c) => c.key !== "income");
    sheet.innerHTML = `
      <div class="sheet-grabber" aria-hidden="true"></div>
      <div class="sheet-head">
        <div><p class="eyebrow">${isNew ? "New one-off" : detected ? esc(x.kind === "paylater" ? `${x.provider} instalment` : x.kind === "income" ? "Expected income" : "Expected charge") : "Planned by you"}</p>
          <h3 id="ps-title">${isNew ? "Plan a one-off" : esc(x.name)}</h3></div>
        ${detected ? avatar(x.name, x.brand, color(x.category)) : ""}
      </div>
      ${detected ? `<p class="ps-note">${esc(x.note)}${x.suggested != null ? ` · Ledger expects ${esc(money(x.suggested, true))}` : ""}</p>` : ""}
      <div class="group ps-form">
        ${planned ? `<label class="row"><span class="row-title">Name</span><input type="text" id="ps-name" maxlength="80" placeholder="Birthday dinner" value="${esc(x?.name || "")}" autocomplete="off"></label>` : ""}
        <label class="row"><span class="row-title">Amount</span><span class="ps-money"><span class="muted">${esc(P.currency)}</span><input type="text" inputmode="decimal" id="ps-amount" placeholder="0" value="${x ? +x.amount.toFixed(2) : ""}" autocomplete="off"></span></label>
        <label class="row"><span class="row-title">Date</span><input type="date" id="ps-date" value="${esc(x?.date || P.as_of)}" min="${esc(P.start)}" max="${esc(P.horizon)}"></label>
      </div>
      ${planned ? `<p class="label" id="ps-cat-label">Category</p>
        <div class="cat-grid" id="ps-cats" role="radiogroup" aria-labelledby="ps-cat-label">${cats.map((c) =>
          `<button type="button" role="radio" data-cat="${esc(c.key)}"><span class="dot" style="background:var(--c-${c.color})"></span>${esc(catName(c.key))}</button>`).join("")}</div>` : `
        <label class="toggle-row"><span><strong>${x.direction === "in" ? "Arrives" : "Happens"} ${x.usual.slice(0, 7) === P.month ? "this month" : `in ${esc(monthOnly(x.usual))}`}</strong><br><small class="muted">${x.status === "missed" ? "It didn’t come when it usually does. Turn on if it’s still coming." : "Turn off if it won’t happen, e.g. a paused subscription."}</small></span>
          <input type="checkbox" id="ps-happens" ${happens ? "checked" : ""}><span class="switch" aria-hidden="true"></span></label>`}
      <p class="error" id="ps-error" role="alert" hidden></p>
      <div class="sheet-actions">
        ${planned && !isNew ? `<button class="btn ps-delete" id="ps-delete" type="button">Delete</button>` : ""}
        ${detected && x.edited ? `<button class="btn ps-delete neutral" id="ps-restore" type="button">Undo changes</button>` : ""}
        <span class="ps-spacer"></span>
        <button class="btn secondary" id="ps-cancel" type="button">Cancel</button>
        <button class="btn primary" id="ps-save" type="button">${isNew ? "Add" : "Save"}</button>
      </div>`;
    const syncCats = () => sheet.querySelectorAll("#ps-cats button").forEach((b) => { const on = b.dataset.cat === editing.category; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
    syncCats();
    sheet.querySelector("#ps-cats")?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { editing.category = b.dataset.cat; syncCats(); } });
    sheet.querySelector("#ps-cancel").addEventListener("click", closeSheet);
    sheet.querySelector("#ps-save").addEventListener("click", () => saveSheet().catch((e) => sheetError(e.message)));
    sheet.querySelector("#ps-delete")?.addEventListener("click", () => removeItem().catch((e) => sheetError(e.message)));
    sheet.querySelector("#ps-restore")?.addEventListener("click", () => restoreItem().catch((e) => sheetError(e.message)));
    sheet.querySelectorAll("input[type=text]").forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveSheet().catch((er) => sheetError(er.message)); } }));
    scrim.hidden = sheet.hidden = false;
    document.body.classList.add("locked");
    (sheet.querySelector("#ps-name") || sheet.querySelector("#ps-amount")).focus({ preventScroll: true });
  }

  function sheetError(msg) { const e = sheet.querySelector("#ps-error"); e.textContent = msg; e.hidden = false; }

  function closeSheet() {
    if (!sheet || sheet.hidden) return;
    scrim.hidden = sheet.hidden = true;
    document.body.classList.remove("locked");
    const from = editing?.from; editing = null;
    if (from?.isConnected) from.focus({ preventScroll: true });
    else document.querySelector(from?.dataset?.key ? `.pt-row[data-key="${CSS.escape(from.dataset.key)}"]` : "#plan-add")?.focus({ preventScroll: true });
  }

  async function saveSheet() {
    const { x, planned } = editing;
    const amount = parseFloat(sheet.querySelector("#ps-amount").value.replace(/[^\d.]/g, ""));
    const day = sheet.querySelector("#ps-date").value;
    if (!(amount >= 0)) return sheetError("Enter an amount, like 400.");
    if (!day) return sheetError("Choose a date.");
    if (planned) {
      const name = sheet.querySelector("#ps-name").value.trim();
      if (!name) return sheetError("Give it a name, like “Birthday dinner”.");
      const body = JSON.stringify({ name, amount, date: day, category: editing.category });
      if (x) await api(`/api/plan/items/${x.id}`, { method: "PATCH", body });
      else await api("/api/plan/items", { method: "POST", body });
      toast(x ? "Saved" : `Added ${name} · ${dayShort(day)}`);
    } else {
      const on = sheet.querySelector("#ps-happens").checked;
      const state_ = x.status === "missed" ? (on ? "include" : null) : on ? null : "skip";
      const usualDay = x.status === "missed" || x.status === "late" ? P.as_of : x.usual;  // where Ledger puts it
      const body = { amount: Math.abs(amount - x.suggested) < 0.005 ? null : amount, date: day === usualDay ? null : day, state: state_ };
      await api(`/api/plan/expected/${encodeURIComponent(x.key).replace(/%3A/g, ":")}`, { method: "PUT", body: JSON.stringify(body) });
      toast(state_ === "skip" ? `${x.name} won’t count this month` : "Saved");
    }
    closeSheet();
    await window.loadPlan(true);
  }

  async function removeItem() {
    const { x } = editing;
    await api(`/api/plan/items/${x.id}`, { method: "DELETE" });
    toast(`Deleted ${x.name}`);
    closeSheet();
    await window.loadPlan(true);
  }

  async function restoreItem() {
    const { x } = editing;
    await api(`/api/plan/expected/${encodeURIComponent(x.key).replace(/%3A/g, ":")}`, { method: "PUT", body: JSON.stringify({}) });
    toast("Back to what Ledger expects");
    closeSheet();
    await window.loadPlan(true);
  }

  let rTimer;
  addEventListener("resize", () => { clearTimeout(rTimer); rTimer = setTimeout(() => { if (state.view === "plan" && P && P.status !== "past") chart(); }, 120); });
})();
