// Boot: connect to the native side, theme the page, route between pages.
import { state, apply, subscribe } from "./store.js";
import { call, send } from "./bridge.js";
import * as meters from "./meters.js";
import { h, ico, clear, toast, closePopover } from "./ui.js";
import { fmtRate } from "./dsp.js";
import * as overview from "./pages/overview.js";
import * as mixer from "./pages/mixer.js";
import * as routing from "./pages/routing.js";
import * as device from "./pages/device.js";

const PAGES = { overview, mixer, routing, device };
const ORDER = ["overview", "mixer", "routing", "device"];
const mounted = {};
const pagesEl = document.getElementById("pages");
const titlebar = document.getElementById("titlebar");
let current = null;
let offline = null;

window.audiusState = state;   // handy in the inspector (--debug)
window.audius = {
  receive(patch) {
    if (patch.toast) { toast(patch.toast.text); delete patch.toast; }
    if (patch.page) { show(patch.page, false); delete patch.page; }
    apply(patch);
  },
  levels(obj) { meters.setLevels(obj); },
};

function applyPlatform() {
  const p = state.platform || {};
  const root = document.documentElement;
  root.dataset.theme = p.dark === false ? "light" : "dark";
  root.dataset.reduceMotion = String(!!p.reduce_motion);
  if (p.accent) root.style.setProperty("--accent", accentFor(p.accent));
  if (p.titlebar) root.style.setProperty("--titlebar", p.titlebar + "px");
}

// The accent marks values you set. GNOME accents that look like signal (green, amber),
// 48V (orange) or clipping (red) would blur those meanings, so they fall back to blue.
function accentFor(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
  if (d < 0.15) return hex;                       // greys and slates are fine
  let hue = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  hue = (hue * 60 + 360) % 360;
  const clash = hue < 70 || hue > 335 || (hue > 95 && hue < 165);
  return clash ? "#3584e4" : hex;
}

function renderTitlebar() {
  const d = state.device || {};
  clear(titlebar);
  const rate = fmtRate(d.rate);
  titlebar.append(h("div", { class: "device-chip", role: "status" },
    h("span", { class: "led" + (d.connected ? "" : " off") }),
    h("span", { class: "label" }, d.connected ? d.name || "Babyface Pro FS" : "Babyface not connected"),
    d.connected ? h("span", { class: "sep" }) : null,
    d.connected ? h("span", { class: "label" }, rate || "Idle") : null,
    d.demo ? h("span", { class: "sep" }) : null,
    d.demo ? h("span", { class: "demo" }, "Demo") : null));
}

export function show(name, notify = true) {
  if (!PAGES[name]) return;
  closePopover();
  if (!mounted[name]) {
    const el = h("section", { class: "page", id: `page-${name}`, hidden: true });
    pagesEl.append(el);
    PAGES[name].mount(el);
    mounted[name] = el;
  }
  if (current === name) return;
  for (const [k, el] of Object.entries(mounted)) {
    if (k === name) {
      el.hidden = false;
      el.classList.remove("entering");
      void el.offsetWidth;
      el.classList.add("entering");
    } else {
      el.hidden = true;
    }
  }
  current = name;
  state.page = name;
  if (PAGES[name].shown) PAGES[name].shown();
  if (notify) send("page", { page: name });
}

function renderOffline() {
  const connected = state.device && state.device.connected;
  if (connected) {
    if (offline) { offline.remove(); offline = null; }
    pagesEl.hidden = false;
    if (!current) show(ORDER.includes(state.page) ? state.page : "overview", false);   // first connect
    return;
  }
  pagesEl.hidden = true;
  if (offline) return;
  offline = h("div", { class: "offline" },
    h("div", { class: "offline-card" },
      h("div", { class: "offline-device", "aria-hidden": "true" },
        h("div", { class: "od-body" }, h("div", { class: "od-knob" }), h("div", { class: "od-bars" }, h("i"), h("i"), h("i"), h("i")))),
      h("h1", {}, "Connect your Babyface"),
      h("p", {}, "Plug the Babyface Pro FS in with USB. Audius uses Class Compliant mode: hold SELECT and DIM while you connect it, and the meters on the unit show “CC”."),
      h("div", { class: "searching" }, h("span", { class: "spinner" }), "Looking for your Babyface…")));
  document.getElementById("app").append(offline);
}

function keys(e) {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && !e.shiftKey && /^[1-4]$/.test(e.key)) {
    e.preventDefault();
    show(ORDER[Number(e.key) - 1]);
  } else if (mod && (e.key === "z" || e.key === "Z")) {
    if (document.activeElement && document.activeElement.tagName === "INPUT") return;
    e.preventDefault();
    send(e.shiftKey ? "redo" : "undo");
  } else if (mod && e.key === "y") {
    e.preventDefault();
    send("redo");
  } else if (mod && e.shiftKey && ["H", "S", "B"].includes(e.key.toUpperCase())) {
    e.preventDefault();
    send("listen", { mode: { H: "headphones", S: "speakers", B: "both" }[e.key.toUpperCase()] });
  } else if (mod && (e.key === "+" || e.key === "=" || e.key === "-" || e.key === "0")) {
    e.preventDefault();          // keep the layout at the system text size
  }
}

async function boot() {
  const s = await call("hello");
  if (s && !s.error) apply(s);
  applyPlatform();
  renderTitlebar();
  subscribe(["platform"], applyPlatform);
  subscribe(["device"], () => { renderTitlebar(); renderOffline(); });
  renderOffline();     // shows the current page once a Babyface is there
  document.addEventListener("keydown", keys);
  document.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
  document.addEventListener("contextmenu", (e) => e.preventDefault());
  await document.fonts.ready;
  setTimeout(() => send("ready_to_shoot"), 250);   // a timer, not rAF: rAF pauses while the view is hidden
}

boot();
