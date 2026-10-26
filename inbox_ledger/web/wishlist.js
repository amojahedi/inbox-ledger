// Ledger — Wishlist. Things you want, and when your real saving pace says you can have them.
// Loaded after app.js and uses its helpers ($, $$, esc, api, money, nf0, state, toast, showTip, hideTip,
// niceMax, catName, color, openCategory). app.js calls window.loadWishlist() when the tab opens.
"use strict";

(() => {
  const wl = { plan: null, editing: null, from: null, dragging: null };
  const view = () => $("#view-wishlist");
  const DAY = 864e5, MONTH_DAYS = 365.25 / 12;

  const WICONS = {
    grip: `<circle cx="9" cy="6.5" r="1.3"/><circle cx="15" cy="6.5" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="17.5" r="1.3"/><circle cx="15" cy="17.5" r="1.3"/>`,
    up: `<path d="m6.5 14.5 5.5-5.5 5.5 5.5"/>`,
    down: `<path d="m6.5 9.5 5.5 5.5 5.5-5.5"/>`,
    link: `<path d="M9.5 6.5h-3a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-3M13 4.5h6.5V11M19 5l-8 8"/>`,
    check: `<path d="m6.5 12.5 3.6 3.6 7.4-8.2"/>`,
    gift: `<rect x="4" y="9" width="16" height="11" rx="2"/><path d="M3.5 9h17M12 9v11M12 9c-1.6-3.6-5.6-4.2-5.6-1.6C6.4 9 12 9 12 9Zm0 0c1.6-3.6 5.6-4.2 5.6-1.6C17.6 9 12 9 12 9Z"/>`,
    bulb: `<path d="M9.2 17.5h5.6M10 20.5h4M12 3.5a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2v1.2h5.2v-1.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3.5Z"/>`,
    target: `<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4.2"/><circle cx="12" cy="12" r="1" fill="currentColor"/>`,
  };
  const wicon = (n, cls = "") => `<svg class="ic ${cls}" viewBox="0 0 24 24" aria-hidden="true">${WICONS[n]}</svg>`;

  // ---------- formatting ----------
  const ymd = (iso) => new Date(`${iso}T00:00`);
  const monthYear = (iso) => ymd(iso).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const longDate = (iso) => ymd(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const sameMonth = (a, b) => a.slice(0, 7) === b.slice(0, 7);
  const round10 = (v) => Math.round(v / 10) * 10;
  const amt = (v) => money(Math.round(v));
  function span(days) {
    days = Math.max(1, Math.round(days));
    if (days < 14) return `${days} day${days === 1 ? "" : "s"}`;
    if (days < 63) return `${Math.round(days / 7)} weeks`;
    const m = Math.round(days / MONTH_DAYS);
    return m < 24 ? `${m} months` : `${+(m / 12).toFixed(1)} years`;
  }
  // "the MacBook Air", but "a weekend in Georgia" (not "the A weekend…").
  const theName = (n) => (/^(a|an|the|my|our|some)\s/i.test(n) ? n[0].toLowerCase() + n.slice(1) : `the ${n}`);
  const monthList = (ms) => {
    const names = ms.map((m) => monthName(m.month).split(" ")[0]);
    return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0] || "";
  };
  const parseAmount = (s) => { const v = parseFloat(String(s).replace(/[^\d.-]/g, "")); return isNaN(v) ? null : v; };

  // ---------- data ----------
  async function load() {
    try {
      wl.plan = await api("/api/wishlist");
      render();
    } catch (e) {
      view().innerHTML = `<div class="hero small"><h1 class="hero-title">Wishlist</h1><p class="hero-sub">${esc(e.message)}</p></div>`;
    }
  }
  window.loadWishlist = load;

  async function call(path, method, body, done) {
    try {
      wl.plan = await api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
      render();
      if (done) done();
      return true;
    } catch (e) { toast(e.message); return false; }
  }

  // ---------- render ----------
  function render() {
    const p = wl.plan;
    if (!p) return;
    const focusKey = document.activeElement?.closest("#view-wishlist") ? document.activeElement.dataset.focus : null;
    view().innerHTML = `
      <div class="hero small wl-hero">
        <h1 class="hero-title">Wishlist</h1>
        <p class="hero-sub">Things you want, and when you can afford them.</p>
      </div>
      ${paceCard(p)}
      ${tipCard(p)}
      <div class="card wl-list-card">
        <div class="card-head">
          <h2>Your wishes</h2>
          ${p.wishes.length ? `<button class="btn primary small" data-act="add" data-focus="add">Add a wish</button>` : ""}
        </div>
        ${p.wishes.length ? `<ol class="wl-list" id="wl-list" aria-label="Wishes, in priority order">${p.wishes.map(item).join("")}</ol>
          <p class="wl-foot">Savings go to your wishes in this order, top first. Drag to reorder, or use the arrows.</p>`
        : emptyList()}
      </div>
      ${timelineCard(p)}
      ${boughtCard(p)}`;
    wire();
    if (p.wishes.length && hasPace(p)) drawTimeline();
    if (focusKey) $(`[data-focus="${CSS.escape(focusKey)}"]`, view())?.focus({ preventScroll: true });
  }

  const hasPace = (p) => p.pace.amount != null && p.pace.amount > 0;

  function paceCard(p) {
    const pace = p.pace, auto = pace.auto;
    const last = p.wishes[p.wishes.length - 1];
    let main;
    if (pace.source === "none") {
      main = `
        <p class="eyebrow">Your saving pace</p>
        <div class="wl-big muted-big">Not known yet</div>
        <p class="wl-explain">Ledger works out how much you save from the money that comes in and goes out. It hasn’t seen any income yet, so it can’t tell. Once your salary alerts arrive, this fills in by itself. Until then, tell it yourself:</p>
        ${paceForm(pace.manual)}`;
    } else if (wl.editPace) {
      main = `
        <p class="eyebrow">Your saving pace</p>
        ${paceForm(pace.manual ?? (auto.amount != null ? Math.round(auto.amount) : null))}`;
    } else if (pace.source === "manual") {
      main = `
        <p class="eyebrow">You said you can save</p>
        <div class="wl-big ${pace.amount <= 0 ? "neg" : ""}">${amt(pace.amount)}<span> a month</span></div>
        <p class="wl-explain">Your own number.${auto.amount != null ? ` From your bank alerts, Ledger estimates <b>${amt(auto.amount)}</b> a month.` : ""}</p>
        <div class="wl-links">
          <button class="link" data-act="edit-pace" data-focus="edit-pace">Change</button>
          ${auto.amount != null ? `<button class="link" data-act="use-auto" data-focus="use-auto">Use Ledger’s estimate</button>` : ""}
        </div>`;
    } else {
      const months = auto.months;
      main = `
        <p class="eyebrow">You save about</p>
        <div class="wl-big ${pace.amount <= 0 ? "neg" : ""}">${pace.amount < 0 ? "−" : ""}${amt(Math.abs(pace.amount))}<span> a month</span></div>
        <p class="wl-sum">${amt(auto.avg_in)} came in − ${amt(auto.avg_out)} spent = <b>${pace.amount < 0 ? "−" : ""}${amt(Math.abs(pace.amount))}</b>,
          the average of ${esc(monthList(months))}.</p>
        <div class="wl-months" role="list">${months.map((m) => {
          const saved = Math.round(m.in) - Math.round(m.out);
          const i = nf0.format(Math.round(m.in)), o = nf0.format(Math.round(m.out));
          return `<div class="wl-m" role="listitem"><p><span class="wl-long">${esc(monthName(m.month))}</span><span class="wl-short" aria-hidden="true">${esc(monthName(m.month, "short"))}</span></p>
            <strong class="${saved < 0 ? "neg" : ""}">${saved < 0 ? "−" : ""}${nf0.format(Math.abs(saved))}</strong>
            <small><span class="wl-long">${i} in − ${o} out</span><span class="wl-short" aria-hidden="true">+${i}<br>−${o}</span></small></div>`;
        }).join("")}</div>
        ${months.length < 3 ? `<p class="wl-explain small">Only ${months.length === 1 ? "one complete month has" : `${months.length} complete months have`} income so far, so this will settle as more months come in.</p>` : ""}
        <div class="wl-links"><button class="link" data-act="edit-pace" data-focus="edit-pace">Use my own number</button></div>`;
    }
    const allBy = !p.wishes.length ? "—"
      : last.status === "ready" ? "Ready now"
      : last.status === "never" ? "Not at this pace"
      : monthYear(last.ready_date);
    return `
      <div class="card wl-pace">
        <div class="wl-pace-main">${main}</div>
        <div class="left-side wl-side">
          <div>
            <p>Already saved for your wishes</p>
            <div class="wl-saved">${wl.editSaved
              ? `<label class="visually-hidden" for="wl-saved-input">Already saved, in ${esc(state.meta.currency)}</label>
                 <input type="text" inputmode="decimal" id="wl-saved-input" class="wl-inline-input" value="${p.saved || ""}" placeholder="0">`
              : `<strong>${amt(p.saved)}</strong><button class="link" data-act="edit-saved" data-focus="edit-saved" aria-label="Change the amount already saved">Edit</button>`}</div>
            <small class="wl-side-note">Money already put aside. It goes to the top wish first.</small>
          </div>
          <div><p>Wishlist total</p><strong>${amt(p.total)}</strong><small>${plural(p.wishes.length, "wish", "wishes")}</small></div>
          ${p.wishes.length ? `<div><p>Everything on the list</p><strong class="wl-by">${esc(allBy)}</strong></div>` : ""}
        </div>
      </div>`;
  }

  function paceForm(value) {
    return `
      <form class="wl-pace-form" data-form="pace">
        <label for="wl-pace-input">I can save</label>
        <span class="wl-ccy-field"><span aria-hidden="true">${esc(state.meta.currency)}</span>
          <input type="text" inputmode="decimal" id="wl-pace-input" value="${value ?? ""}" placeholder="1,500" autocomplete="off"></span>
        <span>a month</span>
        <button class="btn primary small" type="submit">Save</button>
        ${wl.editPace ? `<button class="link" type="button" data-act="cancel-pace">Cancel</button>` : ""}
      </form>`;
  }

  function tipCard(p) {
    const t = p.tip;
    if (!t) return "";
    const cut = `${Math.round(t.share * 100)}% less on ${esc(catName(t.category))} (≈${money(round10(t.cut))} a month)`;
    let text;
    if (t.kind === "sooner") {
      text = t.days_sooner >= 1
        ? `Spend ${cut} and ${esc(theName(t.wish))} arrives <b>${span(t.days_sooner)} sooner</b>${t.fixes_target && !(p.wishes.find((w) => w.id === t.wish_id)?.target_check?.on_track) ? `, in time for ${longDate(p.wishes.find((w) => w.id === t.wish_id).target)}` : ""}.`
        : `Spend ${cut} and that’s ${money(round10(t.cut))} more toward your wishes every month.`;
    } else if (t.kind === "reachable") {
      text = `Spend ${cut} and you’d save about ${money(round10(t.new_pace))} a month: enough for ${esc(theName(t.wish))} by <b>${monthYear(t.ready_date)}</b>.`;
    } else {
      text = `Even ${cut} wouldn’t be enough to start saving. Trends shows where the rest goes.`;
    }
    return `
      <div class="callout wl-tip">
        <span class="wl-tip-icon" aria-hidden="true">${wicon("bulb")}</span>
        <span class="wl-tip-text">${text} <span class="wl-tip-why">${esc(catName(t.category))} averaged ${money(t.monthly)} a month over the same months.</span></span>
        <button class="link" data-act="${t.kind === "not_enough" ? "trends" : "category"}" data-cat="${esc(t.category)}">${t.kind === "not_enough" ? "Open Trends" : "See where it goes"}</button>
      </div>`;
  }

  function statusLine(w, p) {
    if (w.status === "ready") return `<span class="wl-when ready">${wicon("check", "inline")}Ready to buy</span>`;
    if (w.status === "never") return `<span class="wl-when never">${p.pace.amount == null ? "Set your saving pace to see when" : "Not at the current pace"}</span>`;
    const days = w.months * MONTH_DAYS;
    return `<span class="wl-when">${sameMonth(w.ready_date, p.today) ? "Ready later this month" : `Ready in ${monthYear(w.ready_date)}`}<span class="wl-approx"> · ≈${span(days)}</span></span>`;
  }

  function targetLine(w) {
    const t = w.target_check;
    if (!t) return "";
    const when = longDate(t.date);
    let cls = "ok", text;
    if (w.status === "ready") text = `Target ${when} · Ready now`;
    else if (t.on_track) text = `Target ${when} · On track${t.spare_per_month > 0 ? `, ${amt(t.spare_per_month)} a month to spare` : ""}`;
    else if (t.passed) { cls = "late"; text = `Target ${when} has passed`; }
    else {
      cls = "late";
      text = `Target ${when} · Needs ${amt(t.extra_per_month)} more a month`;
    }
    const fix = !t.on_track && !t.passed && t.top_fixes
      ? ` <button class="link small" data-act="top" data-id="${w.id}" data-focus="top-${w.id}">Move to top to make it</button>` : "";
    return `<p class="wl-target ${cls}">${wicon("target", "inline")}${esc(text)}${fix}</p>`;
  }

  function item(w, i, all) {
    const p = wl.plan, ready = w.status === "ready";
    const pct = Math.round(w.progress * 100);
    const covered = ready ? `${amt(w.price)} saved` : w.covered > 0 ? `${amt(w.covered)} of ${amt(w.price)} saved` : `${amt(w.price - w.covered)} to go`;
    let host = "";
    try { host = w.link ? new URL(w.link).hostname.replace(/^www\./, "") : ""; } catch { host = ""; }
    return `
      <li class="wl-item ${ready ? "is-ready" : ""}" data-id="${w.id}">
        <span class="wl-handle" title="Drag to reorder" aria-hidden="true">${wicon("grip")}</span>
        <div class="wl-main">
          <div class="wl-top">
            <span class="wl-name"><span class="wl-rank" aria-hidden="true">${i + 1}</span><span class="wl-title">${esc(w.name)}</span></span>
            <span class="wl-price">${amt(w.price)}</span>
          </div>
          ${w.note || host ? `<p class="wl-note">${esc(w.note)}${w.note && host ? " · " : ""}${host ? `<a href="${esc(w.link)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(host)} (opens in a new tab)">${esc(host)}${wicon("link", "inline")}</a>` : ""}</p>` : ""}
          <div class="wl-track" role="progressbar" aria-label="${esc(w.name)}: share already saved" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-valuetext="${pct}%, ${esc(covered)}">
            <div class="wl-fill" style="width:${Math.max(pct, w.covered > 0 ? 1.5 : 0)}%"></div></div>
          <div class="wl-status">${statusLine(w, p)}${ready
            ? `<button class="btn primary small wl-buy" data-act="buy" data-id="${w.id}" data-focus="buy-${w.id}" aria-label="Mark ${esc(w.name)} as bought">Mark as bought</button>`
            : `<span class="wl-cov">${covered}</span>`}</div>
          ${targetLine(w)}
        </div>
        <div class="wl-actions">
          <div class="wl-tools">
            <button class="wl-icon-btn" data-act="up" data-id="${w.id}" data-focus="up-${w.id}" aria-label="Move ${esc(w.name)} up" ${i === 0 ? "disabled" : ""}>${wicon("up")}</button>
            <button class="wl-icon-btn" data-act="down" data-id="${w.id}" data-focus="down-${w.id}" aria-label="Move ${esc(w.name)} down" ${i === all.length - 1 ? "disabled" : ""}>${wicon("down")}</button>
            <button class="link wl-edit" data-act="edit" data-id="${w.id}" data-focus="edit-${w.id}" aria-label="Edit ${esc(w.name)}">Edit</button>
          </div>
        </div>
      </li>`;
  }

  function emptyList() {
    return `
      <div class="wl-empty">
        <span class="wl-empty-art" aria-hidden="true">${wicon("gift")}</span>
        <strong>What are you saving for?</strong>
        <span>Add something you want. Ledger works out when you can buy it from what you really save each month.</span>
        <button class="btn primary" data-act="add" data-focus="add-empty">Add your first wish</button>
      </div>`;
  }

  function timelineCard(p) {
    if (!p.wishes.length) return "";
    if (!hasPace(p)) {
      return `<div class="card"><div class="card-head"><h2>Savings timeline</h2></div>
        <p class="wl-explain">${p.pace.amount == null ? "Once Ledger knows your saving pace, this shows when each wish comes within reach."
          : "At the moment more goes out than comes in, so savings aren’t growing. The timeline returns once they do."}</p></div>`;
    }
    return `
      <div class="card wl-timeline">
        <div class="card-head"><h2>Savings timeline</h2>
          <span class="legend-inline"><span class="key wl-line-key"></span>Your savings<span class="key wl-goal-key"></span>Wish reached</span></div>
        <div class="chart tall" id="wl-chart" data-label="Projected savings and when each wish is covered"></div>
        <p class="wl-foot">${amt(p.saved)} saved today, plus ${amt(p.pace.amount)} a month. Each line is the running total of your list in order.</p>
      </div>`;
  }

  function boughtCard(p) {
    if (!p.bought.length) return "";
    return `
      <h2 class="group-title wl-bought-title">Bought</h2>
      <div class="card flush wl-bought">
        <ul class="rule-list">${p.bought.map((w) => `
          <li class="rule">
            <span class="rule-name"><span class="wl-bought-check" aria-hidden="true">${wicon("check")}</span>${esc(w.name)}
              <small>Bought ${longDate(w.bought_at.slice(0, 10))}${w.paid_from_saved ? ` · ${amt(w.paid_from_saved)} from your savings` : ""}</small></span>
            <span class="pill wl-bought-price">${amt(w.price)}</span>
            <button class="link small" data-act="unbuy" data-id="${w.id}" data-focus="unbuy-${w.id}" aria-label="Put ${esc(w.name)} back on the list">Put back</button>
          </li>`).join("")}</ul>
      </div>
      <p class="group-foot">Marking a wish as bought doesn’t add a transaction. The purchase shows up from your bank alert as usual.</p>`;
  }

  // ---------- timeline chart ----------
  function drawTimeline() {
    const el = $("#wl-chart");
    if (!el || !el.clientWidth) return;
    const p = wl.plan, pace = p.pace.amount, saved = p.saved;
    const W = el.clientWidth, H = el.clientHeight;
    const pad = { t: 16, r: 14, b: 28, l: 44 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    const lastM = Math.max(0, ...p.wishes.map((w) => w.months || 0));
    const T = Math.min(120, Math.max(2, lastM * 1.12 + 0.4));  // months shown
    const max = niceMax(Math.max(p.total, saved + pace * T) * 1.04);
    const x = (m) => pad.l + (m / T) * iw, y = (v) => pad.t + ih - (Math.min(v, max) / max) * ih;
    const ticks = [0, max / 2, max];
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(el.dataset.label)}: ${esc(p.wishes.map((w) => `${w.name} ${w.status === "ready" ? "ready now" : `in ${monthYear(w.ready_date)}`}`).join(", "))}">
      <defs><linearGradient id="wl-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".16"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs><g class="grid">`;
    for (const t of ticks) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/>`;
    svg += `</g><g class="axis">`;
    for (const t of ticks) svg += `<text x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${t >= 1000 ? +(t / 1000).toFixed(1) + "k" : nf0.format(t)}</text>`;
    // Month labels on the first of each month.
    const today = ymd(p.today), starts = [];
    for (let i = 1; i <= Math.ceil(T) + 1; i++) {
      const d = new Date(today.getFullYear(), today.getMonth() + i, 1);
      const m = (d - today) / DAY / MONTH_DAYS;
      if (m <= T) starts.push({ m, d });
    }
    const every = Math.max(1, Math.ceil(starts.length / Math.max(2, Math.floor(iw / 64))));
    starts.forEach((s, i) => {
      if (i % every || x(s.m) - pad.l < 56) return;  // leave room for "Today"
      const label = s.d.toLocaleDateString("en-US", { month: "short" }) + (s.d.getMonth() === 0 ? ` ’${String(s.d.getFullYear()).slice(2)}` : "");
      svg += `<text x="${x(s.m)}" y="${H - 6}" text-anchor="middle">${esc(label)}</text>`;
    });
    svg += `<text x="${pad.l}" y="${H - 6}" text-anchor="start">Today</text></g>`;
    // Savings: today's pot plus the monthly pace.
    const x0 = x(0), y0 = y(saved), x1 = x(T), y1 = y(saved + pace * T);
    svg += `<path class="wl-area" d="M${x0},${y0}L${x1},${y1}L${x1},${pad.t + ih}L${x0},${pad.t + ih}Z" fill="url(#wl-area)"/>`;
    svg += `<path class="wl-proj" d="M${x0},${y0}L${x1},${y1}"/>`;
    // One threshold per wish: the running total, met where the savings line crosses it.
    const labels = [];
    const bottom = pad.t + ih;
    p.wishes.forEach((w, i) => {
      const yy = y(w.cumulative), xx = x(w.status === "ready" ? 0 : w.months);
      svg += `<line class="wl-goal ${w.status}" x1="${pad.l}" x2="${xx}" y1="${yy}" y2="${yy}"/>`;
      // Above its line on the left, where the savings line hasn't reached yet; a wish that is already
      // covered sits under the savings line, so its label goes just below its own line instead.
      const text = `${i + 1}. ${w.name}`, width = text.length * 6.2;
      let lx = pad.l + 6, ly = yy - 6, anchor = "start";
      if (w.status === "ready") { lx = pad.l + 10; ly = Math.min(yy + 14, bottom - 4); }
      else if (lx + width > xx - 10) {
        // The savings line crosses before the label ends: put it past the dot, under the line.
        ly = Math.min(yy + 14, bottom + 7);
        if (xx + 10 + width <= W - pad.r) lx = xx + 10; else { lx = W - pad.r; anchor = "end"; }
      }
      labels.push({ x: lx, y: ly, anchor, text, w });
    });
    // Keep labels apart, from the top down.
    labels.sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 14) labels[i].y = labels[i - 1].y + 14;
    for (const l of labels) svg += `<text class="wl-goal-label ${l.w.status}" x="${l.x}" y="${Math.max(pad.t + 2, l.y)}" text-anchor="${l.anchor}">${esc(l.text)}</text>`;
    svg += `<circle class="wl-start" cx="${x0}" cy="${y0}" r="4"/>`;
    p.wishes.forEach((w) => {
      const cx = x(w.status === "ready" ? 0 : w.months), cy = y(w.cumulative);
      svg += `<circle class="wl-dot ${w.status}" cx="${cx}" cy="${cy}" r="5"/><circle class="hit wl-hit" data-id="${w.id}" cx="${cx}" cy="${cy}" r="14"/>`;
    });
    el.innerHTML = svg + `</svg>`;
    $$(".wl-hit", el).forEach((h) => {
      const w = p.wishes.find((x) => x.id === +h.dataset.id);
      h.addEventListener("mouseenter", (e) => showTip(e, `<b>${esc(w.name)}</b>${w.status === "ready" ? "Ready now" : `Ready in ${monthYear(w.ready_date)}`}<div class="tip-row"><span>Running total</span><span>${amt(w.cumulative)}</span></div>`));
      h.addEventListener("mouseleave", hideTip);
    });
  }

  // ---------- add / edit sheet ----------
  function sheetEls() {
    let s = $("#wl-sheet");
    if (s) return s;
    document.body.insertAdjacentHTML("beforeend", `
      <div class="scrim" id="wl-scrim" hidden></div>
      <div class="sheet wl-sheet" id="wl-sheet" role="dialog" aria-modal="true" aria-labelledby="wl-sheet-title" hidden>
        <div class="sheet-grabber" aria-hidden="true"></div>
        <form id="wl-form" novalidate>
          <h3 id="wl-sheet-title">Add a wish</h3>
          <div class="wl-fields">
            <label class="wl-field"><span>What is it?</span>
              <input type="text" id="wl-f-name" maxlength="80" placeholder="AirPods Pro" autocomplete="off" required></label>
            <label class="wl-field"><span>Price</span>
              <span class="wl-ccy-field"><span aria-hidden="true" id="wl-f-ccy"></span>
                <input type="text" id="wl-f-price" inputmode="decimal" placeholder="999" autocomplete="off" required></span></label>
            <label class="wl-field"><span>Link <small>optional</small></span>
              <input type="url" id="wl-f-link" placeholder="apple.com/airpods-pro" autocomplete="off" spellcheck="false"></label>
            <label class="wl-field"><span>Note <small>optional</small></span>
              <input type="text" id="wl-f-note" maxlength="280" placeholder="For the gym" autocomplete="off"></label>
            <div class="wl-field"><label for="wl-f-target">Want it by <small>optional</small></label>
              <span class="wl-date-row"><input type="date" id="wl-f-target">
                <button class="link small" type="button" id="wl-f-clear">Clear</button></span></div>
          </div>
          <p class="error" id="wl-f-error" role="alert" hidden></p>
          <div class="wl-sheet-extra" id="wl-f-extra">
            <button class="link" type="button" id="wl-f-bought">Mark as bought</button>
            <button class="btn-del" type="button" id="wl-f-delete">Delete</button>
          </div>
          <div class="sheet-actions">
            <button class="btn secondary" type="button" id="wl-f-cancel">Cancel</button>
            <button class="btn primary" type="submit" id="wl-f-save">Add</button>
          </div>
        </form>
      </div>`);
    s = $("#wl-sheet");
    $("#wl-form").addEventListener("submit", (e) => { e.preventDefault(); saveSheet(); });
    $("#wl-f-cancel").addEventListener("click", closeSheet);
    $("#wl-scrim").addEventListener("click", closeSheet);
    $("#wl-f-clear").addEventListener("click", () => { $("#wl-f-target").value = ""; $("#wl-f-target").focus(); });
    // Delete asks twice, in place: the first press turns the button into a confirmation.
    $("#wl-f-delete").addEventListener("click", async (e) => {
      const w = wl.editing, btn = e.currentTarget;
      if (!w) return;
      if (!btn.dataset.armed) { btn.dataset.armed = "1"; btn.textContent = `Delete “${w.name}”?`; return; }
      if (await call(`/api/wishlist/wishes/${w.id}`, "DELETE")) { closeSheet(true); toast(`Deleted ${w.name}`); $('[data-focus="add"]', view())?.focus(); }
    });
    $("#wl-f-bought").addEventListener("click", () => { const w = wl.editing; closeSheet(true); markBought(w.id); });
    s.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.stopPropagation(); return closeSheet(); }
      if (e.key !== "Tab") return;
      const f = $$("button, input, a[href]", s).filter((x) => !x.closest("[hidden]") && !x.disabled);
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    });
    return s;
  }

  function openSheet(w = null) {
    const s = sheetEls();
    wl.editing = w; wl.from = document.activeElement;
    $("#wl-sheet-title").textContent = w ? "Edit wish" : "Add a wish";
    $("#wl-f-save").textContent = w ? "Save" : "Add";
    $("#wl-f-ccy").textContent = state.meta.currency;
    $("#wl-f-name").value = w?.name || "";
    $("#wl-f-price").value = w ? String(w.price) : "";
    $("#wl-f-link").value = w?.link || "";
    $("#wl-f-note").value = w?.note || "";
    $("#wl-f-target").value = w?.target || "";
    $("#wl-f-target").min = wl.plan.today;
    $("#wl-f-error").hidden = true;
    $("#wl-f-extra").hidden = !w;
    delete $("#wl-f-delete").dataset.armed;
    $("#wl-f-delete").textContent = "Delete";
    $("#wl-f-bought").textContent = w?.status === "ready" ? "Mark as bought" : "I bought it already";
    $$("#wl-form input").forEach((i) => i.removeAttribute("aria-invalid"));
    $("#wl-scrim").hidden = s.hidden = false;
    document.body.classList.add("locked");
    $("#wl-f-name").focus();
  }

  function closeSheet(keepFocus = false) {
    const s = $("#wl-sheet");
    if (!s || s.hidden) return;
    $("#wl-scrim").hidden = s.hidden = true;
    document.body.classList.remove("locked");
    const from = wl.from;
    wl.editing = null; wl.from = null;
    if (!keepFocus && from?.isConnected) from.focus({ preventScroll: true });
  }

  function formError(msg, input) {
    const e = $("#wl-f-error");
    e.textContent = msg; e.hidden = false;
    if (input) { input.setAttribute("aria-invalid", "true"); input.focus(); }
  }

  async function saveSheet() {
    $$("#wl-form input").forEach((i) => i.removeAttribute("aria-invalid"));
    const name = $("#wl-f-name").value.trim();
    const price = parseAmount($("#wl-f-price").value);
    if (!name) return formError("Give your wish a name.", $("#wl-f-name"));
    if (price == null || price <= 0) return formError("Enter a price, like 999.", $("#wl-f-price"));
    const body = { name, price, link: $("#wl-f-link").value.trim(), note: $("#wl-f-note").value.trim(), target: $("#wl-f-target").value || null };
    const w = wl.editing, save = $("#wl-f-save");
    if (save.disabled) return;  // already saving: one press, one wish
    save.disabled = true;
    try {
      wl.plan = await api(w ? `/api/wishlist/wishes/${w.id}` : "/api/wishlist/wishes", { method: w ? "PATCH" : "POST", body: JSON.stringify(body) });
    } catch (e) {
      const m = e.message || "";
      return formError(/link/i.test(m) ? "That link doesn’t look like a web address." : /target/i.test(m) ? "Pick a valid date." : m,
        /link/i.test(m) ? $("#wl-f-link") : /target/i.test(m) ? $("#wl-f-target") : null);
    } finally { save.disabled = false; }
    closeSheet(true);
    render();
    toast(w ? "Saved" : `Added ${name}`);
    const id = w ? w.id : wl.plan.wishes[wl.plan.wishes.length - 1]?.id;
    $(`[data-focus="edit-${id}"]`, view())?.focus({ preventScroll: !w ? false : true });
  }

  // ---------- actions ----------
  async function move(id, delta) {
    const ids = wl.plan.wishes.map((w) => w.id), i = ids.indexOf(id), j = i + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    const name = wl.plan.wishes[i].name;
    await call("/api/wishlist/order", "PUT", { ids }, () => {
      const btn = $(`[data-focus="${delta < 0 ? "up" : "down"}-${id}"]`, view());
      (btn && !btn.disabled ? btn : $(`[data-focus="${delta < 0 ? "down" : "up"}-${id}"]`, view()))?.focus({ preventScroll: true });
      toast(`${name} is now number ${j + 1}`);
    });
  }

  async function toTop(id) {
    const ids = [id, ...wl.plan.wishes.map((w) => w.id).filter((x) => x !== id)];
    const name = wl.plan.wishes.find((w) => w.id === id)?.name;
    await call("/api/wishlist/order", "PUT", { ids }, () => toast(`${name} is now first in line`));
  }

  async function markBought(id) {
    const w = wl.plan.wishes.find((x) => x.id === id);
    await call(`/api/wishlist/wishes/${id}/bought`, "POST", { bought: true }, () => {
      const b = wl.plan.bought.find((x) => x.id === id);
      toast(b?.paid_from_saved ? `Enjoy it. ${amt(b.paid_from_saved)} came off your savings for wishes.` : `Enjoy your ${w?.name || "purchase"}.`);
      $(`[data-focus="unbuy-${id}"]`, view())?.focus({ preventScroll: true });
    });
  }

  function editInline(inputSel, commit) {
    const input = $(inputSel, view());
    input.focus(); input.select();
    let done = false;
    const finish = async (save) => {
      if (done) return; done = true;
      if (save) await commit(input.value); else render();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  }

  function wire() {
    const root = view();
    root.onclick = (e) => {
      const b = e.target.closest("[data-act]");
      if (!b) return;
      const id = +b.dataset.id, act = b.dataset.act;
      if (act === "add") openSheet();
      else if (act === "edit") openSheet(wl.plan.wishes.find((w) => w.id === id));
      else if (act === "up") move(id, -1);
      else if (act === "down") move(id, 1);
      else if (act === "top") toTop(id);
      else if (act === "buy") markBought(id);
      else if (act === "unbuy") call(`/api/wishlist/wishes/${id}/bought`, "POST", { bought: false }, () => toast("Back on your list"));
      else if (act === "category") openCategory(b.dataset.cat);
      else if (act === "trends") go("trends");
      else if (act === "edit-saved") {
        wl.editSaved = true; render();
        editInline("#wl-saved-input", async (v) => {
          wl.editSaved = false;
          const n = parseAmount(v);
          if (n == null || n < 0) return render();
          await call("/api/wishlist", "PATCH", { saved: n }, () => $('[data-focus="edit-saved"]', view())?.focus({ preventScroll: true }));
        });
      } else if (act === "edit-pace") { wl.editPace = true; render(); $("#wl-pace-input", root)?.focus(); }
      else if (act === "cancel-pace") { wl.editPace = false; render(); $('[data-focus="edit-pace"]', root)?.focus(); }
      else if (act === "use-auto") call("/api/wishlist", "PATCH", { use_manual: false }, () => toast("Using Ledger’s estimate"));
    };
    root.onsubmit = (e) => {
      if (e.target.dataset.form !== "pace") return;
      e.preventDefault();
      const n = parseAmount($("#wl-pace-input", root).value);
      if (n == null) { $("#wl-pace-input", root).setAttribute("aria-invalid", "true"); return $("#wl-pace-input", root).focus(); }
      wl.editPace = false;
      call("/api/wishlist", "PATCH", { manual_pace: n, use_manual: true }, () => toast(`Got it: ${amt(n)} a month`));
    };
    wireDrag();
  }

  // Drag a wish by its handle to change the order (the arrow buttons do the same from the keyboard).
  function wireDrag() {
    const list = $("#wl-list", view());
    if (!list) return;
    $$(".wl-item", list).forEach((li) => {
      const handle = $(".wl-handle", li);
      handle.addEventListener("pointerdown", () => { li.draggable = true; });
      li.addEventListener("dragstart", (e) => {
        wl.dragging = li; li.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", li.dataset.id);
      });
      li.addEventListener("dragend", () => {
        li.draggable = false; li.classList.remove("dragging");
        const ids = $$(".wl-item", list).map((x) => +x.dataset.id);
        wl.dragging = null;
        if (ids.join() !== wl.plan.wishes.map((w) => w.id).join()) call("/api/wishlist/order", "PUT", { ids }, () => toast("New order saved"));
      });
    });
    list.addEventListener("pointerup", () => $$(".wl-item", list).forEach((li) => { if (li !== wl.dragging) li.draggable = false; }));
    list.addEventListener("dragover", (e) => {
      if (!wl.dragging) return;
      e.preventDefault();
      const over = e.target.closest(".wl-item");
      if (!over || over === wl.dragging) return;
      const r = over.getBoundingClientRect();
      list.insertBefore(wl.dragging, e.clientY < r.top + r.height / 2 ? over : over.nextSibling);
    });
    list.addEventListener("drop", (e) => e.preventDefault());
  }

  // ---------- page integration ----------
  // The month switcher means nothing here: a wish is about today and the months ahead.
  new MutationObserver(() => document.body.classList.toggle("wl-on", !view().hidden))
    .observe(view(), { attributes: true, attributeFilter: ["hidden"] });
  let rTimer;
  addEventListener("resize", () => {
    clearTimeout(rTimer);
    rTimer = setTimeout(() => { if (!view().hidden && wl.plan) drawTimeline(); }, 120);
  });
})();
