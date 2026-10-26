// Activity list, transaction sheet, custom categories, rules.
"use strict";

// ---------- activity ----------
function renderChips() {
  const chips = [{ key: null, name: "All" }, { key: "other", name: "Needs review", color: "gray" },
    ...(state.meta.pay_later || []).map((p) => ({ key: `${VIA}${p}`, name: `Paid with ${p}`, color: "gray" })),
    ...state.meta.categories.filter((c) => c.key !== "other").map((c) => ({ ...c, name: c.key === "people" ? "Sent to people" : catName(c.key) })),
    { key: INTERNAL, name: "Between my accounts", color: "gray" },
    { key: SETTLED, name: "Settled (cancelled out)", color: "gray" }, { key: HIDDEN, name: "Hidden (didn’t happen)", color: "gray" }];
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
    const moved = list.reduce((a, t) => a + (t.direction === "internal" && !t.hidden && !t.extra?.settled ? t.amount_base : 0), 0);
    const parts = [net ? `${net < 0 ? "−" : ""}${money(Math.abs(net))}` : "", moved ? `${money(moved)} saved` : ""].filter(Boolean);
    html += `<li class="tx-day"><span>${dayName(day)}</span><span${moved ? ` title="Day total leaves out moves between your accounts"` : ""}>${parts.join(" · ")}</span></li>`;
    for (const t of list) {
      const refund = t.extra?.refund, settled = !!t.extra?.settled, gone = !!t.hidden, move = t.direction === "internal";
      const sign = t.direction === "in" ? "+" : move ? "" : "−";
      const fx = t.currency !== state.meta.currency ? `<small>${esc(t.currency)} ${nf2.format(t.amount)}</small>` : "";
      const tag = t.category_source === "learned" ? ` · <span class="learned">Learned</span>` : t.category_source === "manual" ? ` · <span class="learned">Edited</span>` : "";
      const status = gone ? "Didn’t happen" : settled ? "Settled" : refund ? "Refund" : t.extra?.refunded_by ? "Refunded" : t.extra?.payback ? "Paid back" : "";
      const sub = (move ? "Between my accounts" : catName(t.category)) + (t.extra?.via ? ` · via ${t.extra.via}` : "");
      const fallback = move ? "var(--c-gray)" : color(t.category);
      const verb = sign === "−" ? "spent" : refund ? "refunded" : sign === "+" ? "received" : "moved";
      const label = `${t.merchant}, ${verb} ${money(t.amount_base, true)}, ${status ? `${status}, ` : ""}${sub}, ${timeOf(t.occurred_at)}. Open to edit`;
      html += `<li class="tx ${gone ? "gone" : settled ? "settled" : move ? "move" : ""}" data-id="${t.id}" tabindex="0" role="button" aria-label="${esc(label)}">
        ${avatar(t.merchant, t.brand, fallback)}
        <span class="tx-main"><span class="tx-name">${esc(t.merchant)}${status ? ` <span class="tx-badge ${refund || t.extra?.refunded_by ? "refund" : ""}">${status}</span>` : ""}</span><span class="tx-sub">${esc(sub)} · ${timeOf(t.occurred_at)}${tag}${t.note ? ` · ${esc(t.note)}` : ""}</span></span>
        <span class="tx-amt ${t.direction}">${sign}${nf2.format(t.amount_base)}${fx}</span>
        <span class="tx-chev" aria-hidden="true">${icon("chevron")}</span>
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
  renderReviewBar();
}

// ---------- needs-review flow: one transaction at a time ----------
// state.review = { i, auto }: the row being reviewed, and whether to open its sheet on the next render.
function startReview() {
  state.cat = "other"; state.q = ""; $("#search").value = "";
  state.review = { i: 0, auto: true };
  go("activity");
}

function renderReviewBar() {
  const bar = $("#review-bar");
  const on = state.cat === "other" && !state.q && state.txs.length > 0;
  if (!on) {
    if (state.review?.saved && state.cat === "other" && !state.q) toast("All caught up. Ledger will remember these merchants.");
    state.review = null; bar.hidden = true;
    return;
  }
  if (!state.review) state.review = { i: 0, auto: false };
  const r = state.review, n = state.txs.length;
  r.saved = false;
  r.i = Math.max(0, Math.min(r.i, n - 1));
  bar.hidden = false;
  bar.innerHTML = `
    <span class="review-text"><strong>${r.i + 1} of ${n}</strong> to review${defHelp("needs_review")}</span>
    <span class="review-nav">
      <button class="icon-btn" id="review-prev" aria-label="Previous transaction" ${r.i === 0 ? "disabled" : ""}>‹</button>
      <button class="icon-btn" id="review-next" aria-label="Next transaction" ${r.i >= n - 1 ? "disabled" : ""}>›</button>
      <button class="btn primary small" id="review-open">Review</button>
    </span>`;
  const rows = $$("#tx-list .tx");
  rows.forEach((li, i) => li.classList.toggle("current", i === r.i));
  const step = (d) => { r.i += d; r.auto = true; renderReviewBar(); };
  $("#review-prev").addEventListener("click", () => step(-1));
  $("#review-next").addEventListener("click", () => step(1));
  $("#review-open").addEventListener("click", () => { r.auto = true; renderReviewBar(); });
  if (r.auto) {
    r.auto = false;
    const li = rows[r.i];
    li?.scrollIntoView({ block: "center" });
    if (li) openSheet(state.txs[r.i], li);
  }
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
  if (state.review) { state.review.auto = true; state.review.saved = true; }
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
  const empty = $("#rule-empty");
  empty.hidden = rules.length > 0;
  const waiting = state.summary?.uncategorized || 0;
  empty.innerHTML = waiting
    ? `<strong>Nothing learned yet</strong><span>${plural(waiting, "transaction")} in ${esc(monthName(state.month).split(" ")[0])} ${waiting === 1 ? "is" : "are"} waiting for a category. Pick one and Ledger remembers the merchant.</span><button class="btn primary" id="rule-review">Review now</button>`
    : `<strong>No rules yet</strong><span>Open any transaction in Activity and pick a category. Ledger remembers it for that merchant.</span>`;
  $("#rule-review")?.addEventListener("click", startReview);
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

