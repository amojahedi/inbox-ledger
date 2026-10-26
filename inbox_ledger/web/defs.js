// One vocabulary for money words, defined in-product. Loaded after shared.js, before the section files.
//
//   DEFS            {key: {title, text}} — spent, came_in, saved, left, fixed, everyday, settled,
//                   hidden, needs_review. The built-in text mirrors defaults/definitions.yaml and is
//                   replaced by GET /api/definitions at start-up, so every screen uses one sentence.
//   defHelp(key)    → HTML for a small "?" icon button. Put it next to a heading or number; a click
//                   opens a popover with the definition. Esc, a click outside or the close button
//                   closes it and focus goes back to the button. Unknown keys return "".
//   defText(key)    → the plain definition text (for aria-labels and tooltips).
//   loadDefs()      → fetches /api/definitions once; quietly keeps the built-in text if it fails.
"use strict";

const DEFS = {
  spent: { title: "Spent", text: "Card purchases, debits and money you sent to people, with refunds taken off. Moves to your own savings, settled transfers and anything you marked as didn’t happen are not counted." },
  came_in: { title: "Came in", text: "Money that arrived in your accounts, like your salary. Refunds and money a friend paid back are not income, so they are left out." },
  saved: { title: "Saved", text: "Money you moved to your own savings this month. If some came back, it is taken off, so this is what actually stayed put." },
  left: { title: "Left", text: "What is still there after spending and saving. Came in − Spent − Saved." },
  fixed: { title: "Fixed", text: "The part of your spending that is much the same every month, like rent, bills and subscriptions." },
  everyday: { title: "Everyday", text: "Everything else you spent. Spent − Fixed. This is the part you can change from week to week." },
  settled: { title: "Settled", text: "Money you sent someone and got back from them within 45 days. It cancels out, so it is left out of every total." },
  hidden: { title: "Hidden", text: "A transaction you marked as didn’t happen. It stays in the list for reference but is left out of every total." },
  needs_review: { title: "Needs review", text: "Purchases Ledger could not place in a category. Pick one once and it remembers for next time." },
};

async function loadDefs() {
  try {
    const res = await fetch("/api/definitions");
    if (!res.ok) return;
    const d = await res.json();
    for (const [k, v] of Object.entries(d)) if (v && v.title && v.text) DEFS[k] = { title: String(v.title), text: String(v.text) };
  } catch { /* built-in text stays */ }
}

const defText = (key) => DEFS[key]?.text || "";

function defHelp(key) {
  const d = DEFS[key];
  if (!d) return "";
  return `<button type="button" class="def-help" data-def="${esc(key)}" aria-label="What “${esc(d.title)}” means" aria-haspopup="dialog" aria-expanded="false">?</button>`;
}

// ---------- popover (one for the page) ----------
const defPop = { el: null, from: null };

function defPopover() {
  if (defPop.el) return defPop.el;
  const el = document.createElement("div");
  el.className = "def-pop"; el.id = "def-pop"; el.hidden = true;
  el.setAttribute("role", "dialog"); el.setAttribute("aria-labelledby", "def-pop-title"); el.tabIndex = -1;
  el.innerHTML = `<div class="def-pop-head"><h3 id="def-pop-title"></h3><button type="button" class="def-pop-close" aria-label="Close">×</button></div><p id="def-pop-text"></p>`;
  document.body.appendChild(el);
  $(".def-pop-close", el).addEventListener("click", closeDef);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeDef(); }
    if (e.key === "Tab") { e.preventDefault(); $(".def-pop-close", el).focus(); }  // the only control inside
  });
  defPop.el = el;
  return el;
}

function openDef(btn) {
  const d = DEFS[btn.dataset.def];
  if (!d) return;
  if (defPop.from === btn && !defPop.el?.hidden) return closeDef();
  if (defPop.from) defPop.from.setAttribute("aria-expanded", "false");
  const el = defPopover();
  $("#def-pop-title", el).textContent = d.title;
  $("#def-pop-text", el).textContent = d.text;
  el.hidden = false;
  defPop.from = btn; btn.setAttribute("aria-expanded", "true");
  // Below the button, kept inside the window.
  const r = btn.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
  let left = Math.min(Math.max(12, r.left + r.width / 2 - w / 2), innerWidth - w - 12);
  let top = r.bottom + 8;
  if (top + h > innerHeight - 12) top = Math.max(12, r.top - h - 8);
  el.style.left = `${left}px`; el.style.top = `${top}px`;
  el.focus({ preventScroll: true });
}

function closeDef() {
  const el = defPop.el, from = defPop.from;
  if (!el || el.hidden) return;
  el.hidden = true; defPop.from = null;
  if (from) { from.setAttribute("aria-expanded", "false"); if (from.isConnected) from.focus({ preventScroll: true }); }
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".def-help");
  if (btn) { e.preventDefault(); e.stopPropagation(); return openDef(btn); }
  if (defPop.el && !defPop.el.hidden && !defPop.el.contains(e.target)) closeDef();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && defPop.el && !defPop.el.hidden) { e.stopPropagation(); closeDef(); } }, true);
addEventListener("resize", () => { if (defPop.el && !defPop.el.hidden) closeDef(); });
