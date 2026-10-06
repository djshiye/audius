// Device: what the hardware can do on its own, and the few settings that are rarely touched.
import { h, ico, clear, toast, confirmPop } from "../ui.js";
import { state, subscribe, output } from "../store.js";
import { call, send } from "../bridge.js";
import { Segmented, toggleSwitch } from "../controls.js";
import { fmtDb, fmtRate } from "../dsp.js";
import * as meters from "../meters.js";
import { Ballistics } from "../meters.js";
import { meterPos } from "../dsp.js";

const GUIDE = [
  { key: "OUT", title: "Switch the knob between speakers and headphones",
    text: "Press OUT to choose what the big knob controls: Outputs 1/2 (your speakers), then Phones, then Optical. Turn the knob to set that volume; hold SELECT while turning to change the balance." },
  { key: "IN", title: "Set gain on the device",
    text: "Press IN to pick an input pair (1/2, 3/4, optical), press SELECT for left, right or both, then turn the knob." },
  { key: "MIX", title: "Hear an input without the computer",
    text: "Press OUT to pick an output, IN to pick an input, then MIX. The input meters blink; turn the knob to set how loud that input is in the output." },
  { key: "DIM", title: "Dim and recall",
    text: "DIM lowers the selected output by 20 dB. Hold SET for two seconds to remember a volume, and hold DIM for two seconds to go back to it." },
  { key: "SELECT", title: "Class Compliant mode",
    text: "Audius needs Class Compliant mode. To switch, hold SELECT and DIM while plugging in USB; the meters show “CC”." },
];

let root;

export function mount(el) {
  root = h("div", { class: "page-inner device" });
  el.append(root);
  build();
  subscribe(["device", "prefs", "outputs"], build);
}

function build() {
  clear(root);
  const grid = h("div", { class: "device-grid" });
  grid.append(deviceCard(), h("div", { class: "settings-col" }, clockCard(), safetyCard(), opticalCard(), levelsCard(), syncCard(), aboutCard()));
  root.append(grid);
}

// ---------------------------------------------------------------- the unit
function deviceCard() {
  const d = state.device || {};
  const bars = ["in:AN1", "in:AN2", "pb:AN1", "pb:AN2"].map((ch) => {
    const cover = h("i", { class: "bar-cover" });
    const bar = h("div", { class: "unit-bar" }, cover);
    const b = new Ballistics();
    meters.register({
      el: bar,
      tick: (dt, now) => {
        b.step(meters.level(ch), dt, now);
        cover.style.transform = `scaleY(${(1 - meterPos(b.disp)).toFixed(4)})`;
        return !b.idle;
      },
    });
    return bar;
  });
  const keyEls = {};
  const guideEls = {};
  const key = (k) => {
    const el = h("button", { class: "unit-key", "data-key": k, "aria-label": `${k} key` }, h("span", {}, k));
    const on = (v) => { el.classList.toggle("hl", v); guideEls[k]?.classList.toggle("hl", v); };
    el.addEventListener("pointerenter", () => on(true));
    el.addEventListener("pointerleave", () => on(false));
    el.addEventListener("focus", () => on(true));
    el.addEventListener("blur", () => on(false));
    el.addEventListener("click", () => guideEls[k]?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    keyEls[k] = el;
    return el;
  };
  const unit = h("div", { class: "unit", "aria-hidden": "false" },
    h("div", { class: "unit-face" },
      h("div", { class: "unit-meters" },
        h("div", { class: "unit-meter-group" }, h("div", { class: "unit-cap" }, "INPUT"), h("div", { class: "unit-bars" }, bars[0], bars[1])),
        h("div", { class: "unit-meter-group" }, h("div", { class: "unit-cap" }, "OUTPUT"), h("div", { class: "unit-bars" }, bars[2], bars[3]))),
      h("div", { class: "unit-keys" }, key("IN"), key("OUT"), key("SET"), key("MIX"), key("SELECT"), key("DIM")),
      h("div", { class: "unit-knob" }, h("div", { class: "unit-knob-ptr" }))),
    h("div", { class: "unit-brand" }, "Babyface Pro FS"));

  const guide = h("div", { class: "guide" }, h("div", { class: "section-title" }, "Using the Babyface’s own controls"));
  for (const g of GUIDE) {
    const row = h("div", { class: "guide-row", "data-key": g.key },
      h("span", { class: "guide-key" }, g.key),
      h("div", {}, h("div", { class: "guide-title" }, g.title), h("div", { class: "guide-text" }, g.text)));
    const on = (v) => { row.classList.toggle("hl", v); keyEls[g.key]?.classList.toggle("hl", v); };
    row.addEventListener("pointerenter", () => on(true));
    row.addEventListener("pointerleave", () => on(false));
    guideEls[g.key] = row;
    guide.append(row);
  }
  guide.append(h("div", { class: "guide-note" }, ico("info"),
    h("span", {}, "Changes made on the device aren’t reported to the computer, so Audius keeps showing the last values it set. Volume changes made in Audius after you’ve used the knob fade in gently.")));

  const facts = h("dl", { class: "facts" },
    fact("Mode", d.demo ? "Demo (no hardware)" : "Class Compliant"),
    fact("Serial", d.serial || "—"),
    fact("Sample rate", fmtRate(d.rate) || "Idle"),
    fact("Clock", d.clock === "internal" ? "Internal" : "AutoSync"));
  return h("section", { class: "card device-card" },
    h("div", { class: "card-head" }, h("div", { class: "titles" }, h("div", { class: "card-title big" }, d.name || "Babyface Pro FS"),
      h("div", { class: "card-sub" }, "RME · USB 2.0"))),
    unit, facts, guide);
}

const fact = (k, v) => h("div", { class: "fact" }, h("dt", {}, k), h("dd", { class: "num" }, v));

// ---------------------------------------------------------------- settings
function settingsCard(title, rows, extraClass = "") {
  return h("section", { class: `card settings-card ${extraClass}` }, h("div", { class: "settings-title" }, title), ...rows);
}

function row(label, desc, control) {
  return h("div", { class: "setting" },
    h("div", { class: "setting-text" }, h("div", { class: "setting-label" }, label), desc ? h("div", { class: "setting-desc" }, desc) : null),
    h("div", { class: "setting-control" }, control));
}

function clockCard() {
  const d = state.device || {};
  const clock = new Segmented({
    size: "sm", label: "Clock source", value: d.clock || "autosync",
    items: [{ value: "autosync", label: "AutoSync" }, { value: "internal", label: "Internal" }],
    onChange: (v) => send("clock", { mode: v }),
  });
  return settingsCard("Clock", [
    row("Clock source", "AutoSync follows a digital input when one is connected. Internal makes the Babyface the master.", clock.el),
    row("Sample rate", "Chosen by the computer while audio is playing.", h("span", { class: "setting-value num" }, fmtRate(d.rate) || "Idle")),
  ]);
}

const CEILINGS = [-20, -12, -6, 0, 6];
function ceilingControl(outId) {
  const o = output(outId);
  const nearest = CEILINGS.reduce((a, b) => (Math.abs(b - o.limit_db) < Math.abs(a - o.limit_db) ? b : a));
  return new Segmented({
    size: "sm", label: `${o.name} ceiling`, value: nearest,
    items: CEILINGS.map((v) => ({ value: v, label: fmtDb(v, { digits: 0, unit: false }) })),
    onChange: (v) => send("limit", { out: outId, db: v }),
  }).el;
}

function safetyCard() {
  const p = state.prefs || {};
  const fade = toggleSwitch({ checked: p.takeover_fade !== false, label: "Fade in after the knob",
    onToggle: (v) => send("pref", { key: "takeover_fade", value: v }) });
  const start = new Segmented({
    size: "sm", label: "Speakers start at", value: p.speaker_start_db ?? -40,
    items: [-50, -40, -30, -20].map((v) => ({ value: v, label: fmtDb(v, { digits: 0, unit: false }) })),
    onChange: (v) => send("pref", { key: "speaker_start_db", value: v }),
  });
  return settingsCard("Volume safety", [
    row("Headphones ceiling", "The loudest Audius will set your headphones, in dB.", ceilingControl("PH3")),
    row("Speakers ceiling", "The loudest Audius will set your speakers, in dB.", ceilingControl("AN1")),
    row("Fade in after the knob", "Audius can’t see the knob, so after you use it the next volume change here starts quiet and fades in.", fade),
    row("Speakers start at", "Where the speakers begin when you switch to them from silence.", start.el),
  ]);
}

function opticalCard() {
  const d = state.device || {};
  const p = state.prefs || {};
  const fmt = new Segmented({
    size: "sm", label: "Optical output format", value: d.optical_out || "adat",
    items: [{ value: "adat", label: "ADAT" }, { value: "spdif", label: "S/PDIF" }],
    onChange: (v) => send("optical_out", { format: v }),
  });
  const show = toggleSwitch({ checked: !!p.show_optical, label: "Show optical channels", onToggle: (v) => send("pref", { key: "show_optical", value: v }) });
  const rows = [
    row("Show optical channels", "Adds the optical inputs and outputs to the Mixer and Routing.", show),
    row("Output format", "ADAT carries 8 channels; S/PDIF carries 2.", fmt.el),
  ];
  if (d.optical_out === "spdif") {
    rows.push(row("Professional format", "Sends AES/EBU-style channel status.",
      toggleSwitch({ checked: !!d.spdif_pro, label: "Professional format", onToggle: (v) => send("spdif_pro", { on: v }) })));
    rows.push(row("Emphasis", "Flags the signal as pre-emphasised.",
      toggleSwitch({ checked: !!d.spdif_emphasis, label: "Emphasis", onToggle: (v) => send("spdif_emphasis", { on: v }) })));
  }
  return settingsCard("Optical", rows);
}

function levelsCard() {
  const p = state.prefs || {};
  const m = toggleSwitch({ checked: p.meters !== false, label: "Live levels", onToggle: (v) => send("pref", { key: "meters", value: v }) });
  const pb = toggleSwitch({ checked: !!p.show_all_playback, label: "Show computer channels 3 to 12", onToggle: (v) => send("pref", { key: "show_all_playback", value: v }) });
  return settingsCard("Levels and channels", [
    row("Live levels", "Measures your inputs and the computer’s playback while Audius is open. GNOME shows its microphone indicator meanwhile, because the levels come from the Babyface’s inputs.", m),
    row("Computer channels 3–12", "Your system currently plays through channels 1/2 only.", pb),
  ]);
}

function syncCard() {
  let volumes = false;
  const vol = toggleSwitch({ checked: false, label: "Include output volumes", onToggle: (v) => { volumes = v; } });
  const btn = h("button", { class: "btn" }, ico("resend"), "Resend");
  btn.addEventListener("click", async () => {
    if (volumes) {
      const ok = await confirmPop(btn, {
        title: "Resend output volumes too?",
        body: "Your speakers and headphones will jump to the volumes Audius shows, which may differ from where the knob left them.",
        ok: "Resend All", okClass: "warn",
      });
      if (!ok) return;
    }
    const r = await call("resend", { volumes });
    if (r && r.count) toast(`Sent ${r.count} settings to the Babyface`);
  });
  return settingsCard("Resend to the Babyface", [
    row("Resend settings", "If the Babyface was power-cycled and sounds different from what Audius shows, send everything again. 48V is never resent.", btn),
    row("Include output volumes", "Off by default, so nothing gets suddenly louder.", vol),
  ]);
}

function aboutCard() {
  const v = (state.platform && state.platform.version) || "";
  return h("section", { class: "card settings-card about" },
    h("div", { class: "about-head" },
      h("img", { class: "about-icon", src: "app-icon.svg", alt: "" }),
      h("div", {}, h("div", { class: "card-title" }, "Audius"), h("div", { class: "card-sub" }, `Version ${v}`))),
    h("p", { class: "setting-desc" }, "A control panel for the RME Babyface Pro FS in Class Compliant mode, built on the Linux kernel’s Babyface Pro mixer driver. RME, Babyface and TotalMix are trademarks of RME Audio AG; Audius is not affiliated with RME."),
    h("div", { class: "kbd-list" },
      kbd("Ctrl", "1–4", "Switch pages"), kbd("Ctrl", "Z", "Undo"), kbd("Ctrl", "Shift", "Z", "Redo"),
      kbd("Ctrl", "Shift", "H / S / B", "Listen on headphones, speakers, both"), kbd("Shift", "drag", "Fine adjustment"),
      kbd("Alt", "click", "Fader to 0 dB"), kbd("Double-click", "Type a value")));
}

function kbd(...parts) {
  const label = parts.pop();
  return h("div", { class: "kbd-row" }, h("span", { class: "kbd-keys" }, ...parts.map((p) => h("span", { class: "kbd" }, p))), h("span", { class: "dim" }, label));
}
