// Settings, sync/import, onboarding.
"use strict";

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
  // Banks: only what the user chose. With nothing chosen, Ledger tries every profile it has.
  const seen = (state.meta.pay_later || []).filter((p) => (s.pay_later || []).includes(p));
  $("#banks-status").textContent = s.banks.length
    ? `${s.banks.join(", ")}${seen.length ? ` · plus ${seen.join(", ")} for pay later` : ""}`
    : "Not chosen yet · Ledger tries every bank profile";
  $("#banks-btn").textContent = s.banks.length ? "Change" : "Choose";
  const demoDir = s.demo_dir && !s.demo;
  $("#demo-title").textContent = s.demo ? "You’re exploring the demo" : demoDir ? "Example data" : "Try the demo";
  $("#demo-sub").textContent = s.demo ? "Example numbers, kept apart from your own ledger." :
    demoDir ? "Everything here is made up, so you can look around. Your own bank alerts aren’t in it yet." :
    "Six months of made-up spending to explore. Your own data isn’t touched.";
  $("#demo-btn").textContent = s.demo ? "Leave demo" : demoDir ? "Start your own ledger" : "Open demo";
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

// While a dialog is open, the page behind it is inert: no focus, no clicks, not read by screen readers.
function setBackgroundInert(on) {
  for (const el of [$("main"), $("header.nav")]) if (el) el.inert = on;
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
  setBackgroundInert(true);
  renderOnboarding();
  api("/api/settings").then((s) => { state.settings = s; if (ob.step === 2) renderOnboarding(); }).catch(() => {});
}

async function closeOnboarding(markDone = true) {
  $("#onboarding").hidden = true;
  ob.only = false;
  document.body.classList.remove("locked");
  setBackgroundInert(false);
  (state.view === "settings" ? $("#settings-btn") : $("[role=tab][aria-selected=true]"))?.focus({ preventScroll: true });
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
      <p class="ob-lead" id="ob-lead">Your bank already emails you about every payment. Ledger turns those emails into a clear monthly budget.</p>
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
      <p class="ob-lead" id="ob-lead">Ledger reads the alert emails your bank sends. Choose every bank you get alerts from.</p>
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
      <p class="ob-lead" id="ob-lead">Choose how Ledger gets your bank alerts. You can add more later in Settings.</p>
      <div class="group options">
        <button class="row option ${ob.gmail ? "open" : ""}" data-ob="gmail" aria-expanded="${ob.gmail}" aria-label="Connect Gmail, read-only">
          <span class="row-icon" style="--tint:var(--c-red)">${icon("mail")}</span>
          <span class="row-main"><span class="row-title">Connect Gmail</span><span class="row-sub">Read-only. Ledger only searches for your bank’s alerts.</span></span>
          ${icon("chevron", "chev")}
        </button>
        ${gmailPanel}
        <button class="row option" data-ob="import" aria-label="Import a file">
          <span class="row-icon" style="--tint:var(--c-blue)">${icon("tray")}</span>
          <span class="row-main"><span class="row-title">Import a file</span><span class="row-sub">A .mbox from Google Takeout, or a .jsonl of emails.</span></span>
          ${icon("chevron", "chev")}
        </button>
        <button class="row option" data-ob="demo" aria-label="Try the demo">
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
      <p class="ob-lead" id="ob-lead">${esc(facts)}</p>
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

