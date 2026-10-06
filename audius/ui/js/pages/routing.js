// Routing: the whole matrix as a grid. Every square sends one source channel to one output channel.
import { h, ico, clear, inlineEdit } from "../ui.js";
import { state, subscribe } from "../store.js";
import { send, newGesture } from "../bridge.js";
import { toggleSwitch } from "../controls.js";
import { rawToDb, fmtDb, parseDb, clamp, MAX_DB, MINUS } from "../dsp.js";
import { undoGroup, scenesButton } from "../common.js";

const IN_NAMES = { AN1: "Mic 1", AN2: "Mic 2", IN3: "Instrument 3", IN4: "Instrument 4", AS1: "Optical 1", AS2: "Optical 2",
  ADAT3: "Optical 3", ADAT4: "Optical 4", ADAT5: "Optical 5", ADAT6: "Optical 6", ADAT7: "Optical 7", ADAT8: "Optical 8" };
const OUT_ORDER = ["AN1", "AN2", "PH3", "PH4", "AS1", "AS2", "ADAT3", "ADAT4", "ADAT5", "ADAT6", "ADAT7", "ADAT8"];
const remembered = {};   // last level per crosspoint, for click-to-reconnect

export function sendCtl(src, out) {
  const [kind, ch] = src.split(":");
  if (kind === "pb") return `PCM-${ch}-${out} Playback Volume`;
  return `${ch === "AN1" || ch === "AN2" ? "Mic" : "Line"}-${ch}-${out} Playback Volume`;
}

let root, gridBox, cells = new Map(), optSwitch, pbSwitch;

export function mount(el) {
  root = h("div", { class: "page-inner routing" });
  el.append(root);
  optSwitch = toggleSwitch({ checked: !!state.prefs.show_optical, label: "Show optical channels", onToggle: (v) => send("pref", { key: "show_optical", value: v }) });
  pbSwitch = toggleSwitch({ checked: !!state.prefs.show_all_playback, label: "Show computer channels 3 to 12", onToggle: (v) => send("pref", { key: "show_all_playback", value: v }) });
  root.append(
    h("div", { class: "toolbar" },
      h("label", { class: "inline-switch" }, optSwitch, "Optical"),
      h("label", { class: "inline-switch" }, pbSwitch, "Computer 3–12"),
      h("div", { class: "spacer" }), undoGroup(), scenesButton()),
    h("div", { class: "page-sub" }, "Click a square to connect or disconnect. Scroll to adjust, double-click to type a level."));
  gridBox = h("div", { class: "matrix-card card" });
  root.append(gridBox);
  build();
  subscribe(["strips", "prefs", "outputs"], () => {
    optSwitch.setChecked(!!state.prefs.show_optical);
    pbSwitch.setChecked(!!state.prefs.show_all_playback);
    build();
  });
  subscribe(["locked"], () => cells.forEach(paint));
  subscribe(["raw"], (changed, patch) => {
    for (const ctl of Object.keys(patch.raw || {})) {
      const c = cells.get(ctl);
      if (c) paint(c);
    }
  });
}

function visibleOutputs() {
  const pairs = state.outputs.filter((o) => o.visible);
  const cols = [];
  for (const o of pairs) {
    o.channels.forEach((ch, i) => cols.push({ ch, pair: o, side: i === 0 ? "L" : "R" }));
  }
  return cols;
}

function visibleSources() {
  const rows = [];
  const opt = !!state.prefs.show_optical, pb = !!state.prefs.show_all_playback;
  for (const ch of Object.keys(IN_NAMES)) {
    if (!opt && !["AN1", "AN2", "IN3", "IN4"].includes(ch)) continue;
    const custom = state.strips.find((s) => s.kind === "in" && !s.stereo && s.channels[0] === ch);
    rows.push({ src: `in:${ch}`, name: custom ? custom.name : IN_NAMES[ch], group: "Inputs" });
  }
  OUT_ORDER.forEach((ch, i) => {
    if (!pb && i > 1) return;
    rows.push({ src: `pb:${ch}`, name: `Computer ${i + 1}`, group: "Computer" });
  });
  return rows;
}

function build() {
  cells = new Map();
  clear(gridBox);
  const cols = visibleOutputs();
  const rows = visibleSources();
  const table = h("div", { class: "matrix", role: "grid", "aria-label": "Routing matrix", vars: { "--cols": cols.length } });
  // header rows: output pairs, then L/R
  table.append(h("div", { class: "mx-corner" }));
  let i = 0;
  while (i < cols.length) {
    const pair = cols[i].pair;
    const span = cols.filter((c) => c.pair === pair).length;
    table.append(h("div", { class: "mx-pair" + (pair.on ? "" : " off"), style: { gridColumn: `span ${span}` }, title: pair.on ? pair.detail : `${pair.name} is switched off` },
      h("span", {}, pair.name), pair.on ? null : h("span", { class: "mx-off" }, "Off")));
    i += span;
  }
  table.append(h("div", { class: "mx-corner sub" }));
  cols.forEach((c, ci) => table.append(h("div", { class: "mx-side", "data-col": ci }, c.side)));
  let lastGroup = null;
  rows.forEach((r, ri) => {
    if (r.group !== lastGroup) {
      lastGroup = r.group;
      table.append(h("div", { class: "mx-group", style: { gridColumn: `1 / span ${cols.length + 1}` } }, r.group));
    }
    table.append(h("div", { class: "mx-row-head", "data-row": ri }, r.name));
    cols.forEach((c, ci) => {
      const ctl = sendCtl(r.src, c.ch);
      const cell = h("button", {
        class: "mx-cell" + (c.pair.on ? "" : " col-off") + (c.side === "R" ? " r" : ""), role: "gridcell", tabindex: ri === 0 && ci === 0 ? "0" : "-1",
        "data-row": ri, "data-col": ci,
      });
      const entry = { el: cell, ctl, row: ri, col: ci, name: `${r.name} to ${c.pair.name} ${c.side === "L" ? "left" : "right"}` };
      cells.set(ctl, entry);
      wire(entry, table);
      paint(entry);
      table.append(cell);
    });
  });
  gridBox.append(table);
}

function dbOf(entry) {
  return rawToDb(state.raw[entry.ctl] || 0);
}

function short(db) {
  if (db === null) return "";
  const r = Math.round(db);
  const v = Math.abs(db - r) < 0.05 ? String(Math.abs(r)) : Math.abs(db).toFixed(1);
  return (db > 0.04 ? "+" : db < -0.04 ? MINUS : "") + v;
}

function paint(entry) {
  if ((state.locked || []).includes(entry.ctl)) {
    entry.el.classList.add("locked");
    entry.el.disabled = true;
    entry.el.textContent = "";
    entry.el.title = `${entry.name}: locked. Something set an odd level here, which the Linux driver mishandles, so Audius leaves it alone.`;
    return;
  }
  const db = dbOf(entry);
  const on = db !== null;
  entry.el.classList.toggle("on", on);
  entry.el.textContent = short(db);
  const strength = on ? clamp((db + 40) / 46, 0.12, 1) : 0;
  entry.el.style.setProperty("--k", strength.toFixed(3));
  entry.el.setAttribute("aria-label", `${entry.name}: ${on ? fmtDb(db) : "not connected"}`);
  entry.el.title = `${entry.name}: ${on ? fmtDb(db) : "not connected"}`;
}

function set(entry, db, g) {
  send("crosspoint", { ctl: entry.ctl, db, gesture: g });
}

function wire(entry, table) {
  const el = entry.el;
  el.addEventListener("click", () => {
    const db = dbOf(entry);
    const g = newGesture();
    if (db === null) set(entry, remembered[entry.ctl] ?? 0, g);
    else { remembered[entry.ctl] = db; set(entry, null, g); }
    send("end_gesture");
  });
  el.addEventListener("dblclick", (e) => {
    e.preventDefault();
    inlineEdit(el, {
      value: dbOf(entry) === null ? "0" : dbOf(entry).toFixed(1), width: 76,
      onCommit: (t) => {
        const v = parseDb(t);
        if (v === undefined) return;
        set(entry, v === null ? null : clamp(v, -80, MAX_DB), newGesture());
        send("end_gesture");
      },
    });
  });
  let g = null, timer = 0;
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    const d = e.deltaMode === 1 ? -e.deltaY : -e.deltaY / 30;
    const cur = dbOf(entry);
    if (cur === null && d < 0) return;
    let v = cur === null ? -40 : cur + (e.shiftKey ? d * 0.25 : d);
    v = v < -70 ? null : Math.min(MAX_DB, Math.round(v * 10) / 10);
    if (!g) g = newGesture();
    clearTimeout(timer);
    timer = setTimeout(() => { g = null; send("end_gesture"); }, 600);
    set(entry, v, g);
  }, { passive: false });
  el.addEventListener("keydown", (e) => {
    const move = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] }[e.key];
    if (move) {
      e.preventDefault();
      const next = table.querySelector(`.mx-cell[data-row="${entry.row + move[0]}"][data-col="${entry.col + move[1]}"]`);
      if (next) { el.tabIndex = -1; next.tabIndex = 0; next.focus(); }
    } else if (e.key === "+" || e.key === "=" || e.key === "-") {
      e.preventDefault();
      const cur = dbOf(entry);
      const v = cur === null ? (e.key === "-" ? null : -40) : cur + (e.key === "-" ? -1 : 1);
      set(entry, v === null || v < -70 ? null : Math.min(MAX_DB, v), newGesture());
      send("end_gesture");
    }
  });
  el.addEventListener("pointerenter", () => highlight(table, entry, true));
  el.addEventListener("pointerleave", () => highlight(table, entry, false));
  el.addEventListener("focus", () => highlight(table, entry, true));
  el.addEventListener("blur", () => highlight(table, entry, false));
}

function highlight(table, entry, on) {
  table.querySelector(`.mx-row-head[data-row="${entry.row}"]`)?.classList.toggle("hl", on);
  table.querySelector(`.mx-side[data-col="${entry.col}"]`)?.classList.toggle("hl", on);
}
