// Navigation and start-up. Loaded after the section files.
"use strict";

// ---------- navigation ----------
const prevMonth = (m) => { const [y, mo] = m.split("-").map(Number); return mo === 1 ? `${y - 1}-12` : `${y}-${String(mo - 1).padStart(2, "0")}`; };

function setMonth(m) { state.month = m; syncHash(); loadMonth(); if (state.view === "activity") loadActivity(); if (state.view === "trends") loadTrends(); if (state.view === "category") loadCategory(); }

function go(view, { push = true } = {}) {
  state.view = view;
  $$(".segmented[role=tablist] button").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === view));
  $("#settings-btn").classList.toggle("on", view === "settings");
  $("#settings-btn").setAttribute("aria-pressed", view === "settings");
  $("#month-switch").classList.toggle("off", view === "settings" || view === "rules" || !state.meta.months.length);
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  syncHash(push);
  if (view === "activity") loadActivity();
  if (view === "rules") loadRules();
  if (view === "settings") loadSettings();
  if (view === "trends") loadTrends();
  if (view === "wishlist") window.loadWishlist?.();
  if (view === "category") loadCategory();
  if (view === "plan") window.loadPlan?.();
  if (view === "overview" && state.summary) renderCharts();
  scrollTo({ top: 0 });
}

// ---------- deep links: #view/month[/key] ----------
// Keys: #category/2026-10/dining, #activity/2026-10/needs-review, #activity/2026-10/q=faris.
const HASH_KEYS = { other: "needs-review", [INTERNAL]: "between-accounts", [SETTLED]: "settled", [HIDDEN]: "hidden" };
function hashKey() {
  if (state.view === "category") return state.detailCat ? `/${encodeURIComponent(state.detailCat)}` : "";
  if (state.view !== "activity") return "";
  const c = state.cat;
  const key = !c ? "" : HASH_KEYS[c] || (c.startsWith(VIA) ? `paid-with:${encodeURIComponent(c.slice(VIA.length))}` : encodeURIComponent(c));
  return (key ? `/${key}` : "") + (state.q ? `/q=${encodeURIComponent(state.q)}` : "");
}
function parseHash() {
  const [view, month, ...rest] = location.hash.slice(1).split("/");
  const out = { view, month, cat: null, q: "", detailCat: null };
  for (const part of rest) {
    if (!part) continue;
    if (part.startsWith("q=")) { out.q = decodeURIComponent(part.slice(2)); continue; }
    const back = Object.entries(HASH_KEYS).find(([, v]) => v === part);
    out.cat = back ? back[0] : part.startsWith("paid-with:") ? VIA + decodeURIComponent(part.slice(10)) : decodeURIComponent(part);
    if (out.cat && !HASH_KEYS[out.cat] && !out.cat.startsWith(VIA) && !state.meta.categories.some((c) => c.key === out.cat)) out.cat = null;
    out.detailCat = out.cat;
  }
  return out;
}
// A view change makes a history entry (so Back works); month and filter changes replace the current one.
function syncHash(push = false) {
  const h = `#${state.view}/${state.month}${hashKey()}`;
  if (location.hash === h) return;
  history[push ? "pushState" : "replaceState"](null, "", `${location.search}${h}`);
}
// Back/forward or a pasted link: restore month, view and filter from the hash.
function restoreHash() {
  const h = parseHash();
  const months = state.meta.months.map((m) => m.month);
  if (!VIEWS.includes(h.view)) return;
  if (h.view === "activity") { state.cat = h.cat; state.q = h.q; $("#search").value = h.q; state.review = null; }
  if (h.view === "category") { if (!h.detailCat) return; state.detailCat = h.detailCat; }
  if (h.month && h.month !== state.month && months.includes(h.month)) { state.month = h.month; loadMonth(); }
  go(h.view, { push: false });
}

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
  renderCategories(s); renderLeft(s); renderStats(s); renderBudgets(s); renderMerchants(s);
  window.renderComingUp?.(s);
  if (state.view === "overview") renderCharts();
}

function renderCharts() { if (!state.meta.months.length) return; const s = state.summary; renderDaily(s); renderTrend(s); renderHours(s); }

async function loadActivity() {
  const p = new URLSearchParams({ month: state.month });
  if (!state.cat) p.set("internal", "show");  // the All list shows moves between your accounts, greyed
  else if (state.cat === INTERNAL) p.set("internal", "only");
  else if (state.cat === SETTLED || state.cat === HIDDEN) { p.set("show", state.cat === SETTLED ? "settled" : "hidden"); p.set("internal", "show"); }
  else if (state.cat?.startsWith(VIA)) p.set("via", state.cat.slice(VIA.length));
  else if (state.cat) p.set("category", state.cat);
  if (state.q) p.set("q", state.q);
  state.txs = await api(`/api/transactions?${p}`);
  if (state.view === "activity") syncHash();
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
  $("#callout-btn").addEventListener("click", startReview);
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
  // Keep keyboard focus inside an open dialog (the sheet and the welcome flow).
  const trapFocus = (dialog) => dialog.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = $$("button, input, select, a[href], [tabindex]", dialog)
      .filter((x) => !x.closest("[hidden]") && !x.disabled && x.tabIndex >= 0 && x.style.visibility !== "hidden");
    if (!f.length) return;
    if (e.shiftKey && (document.activeElement === f[0] || !f.includes(document.activeElement))) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  trapFocus($("#sheet")); trapFocus($("#onboarding"));

  // settings
  $("#theme-seg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) savePref({ theme: b.dataset.themeOpt }); });
  $("#currency-sel").addEventListener("change", (e) => savePref({ currency: e.target.value }));
  $("#number-sel").addEventListener("change", (e) => savePref({ number: e.target.value }));
  $("#logos-toggle").addEventListener("change", (e) => savePref({ [state.settings.logos_key]: e.target.checked }));
  $("#gmail-btn").addEventListener("click", () => settingsGmail());
  $("#import-btn").addEventListener("click", () => settingsImport());
  $("#banks-btn").addEventListener("click", () => openOnboarding(1, { only: true }));
  $("#setup-btn").addEventListener("click", () => openOnboarding(0));
  $("#demo-btn").addEventListener("click", () => {
    if (state.settings.demo) return leaveDemo().catch((e) => toast(e.message));
    if (state.settings.demo_dir) return openOnboarding(0);  // example data: start your own ledger
    enterDemo().then(() => go("overview")).catch((e) => toast(e.message));
  });
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
  addEventListener("hashchange", restoreHash);
  // The chips row fades at its right edge while there is more to scroll to.
  const chips = $("#chips"), wrap = $("#chips-wrap");
  const fade = () => wrap.classList.toggle("more", chips.scrollLeft + chips.clientWidth < chips.scrollWidth - 2);
  chips.addEventListener("scroll", fade, { passive: true });
  addEventListener("resize", fade);
  new MutationObserver(fade).observe(chips, { childList: true });
}

async function init() {
  wire();
  loadDefs();
  state.meta = await api("/api/meta");
  applyPrefs();
  const h = parseHash(), { view, month } = h;
  state.month = state.meta.months.some((m) => m.month === month) ? month : state.meta.current;
  if (view === "activity") { state.cat = h.cat; state.q = h.q; $("#search").value = h.q; }
  if (view === "category") state.detailCat = h.detailCat;
  await loadMonth();
  go(VIEWS.includes(view) && (view !== "category" || h.detailCat) ? view : "overview", { push: false });
  const firstRun = !state.meta.source.emails && !state.meta.settings.onboarded && !state.meta.source.demo;
  if (view === "welcome" || firstRun) {
    state.settings = await api("/api/settings");
    openOnboarding(view === "welcome" ? Math.min(+month || 0, OB_STEPS - 1) : 0);
  }
}

init().catch((e) => {
  document.querySelector("main").innerHTML = `<div class="hero"><h1 class="hero-title">Couldn’t load your ledger</h1><p class="hero-sub">${esc(e.message)}</p></div>`;
});
