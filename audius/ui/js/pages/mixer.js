// Mixer: one output at a time. Every source gets a fader, pan, mute and meter.
import { h, ico, clear, renameable } from "../ui.js";
import { state, subscribe, output, sendOf } from "../store.js";
import { send, frameSender } from "../bridge.js";
import { Segmented, VFader, Pan, MeterV, faderScale, toggleSwitch } from "../controls.js";
import { fmtDb, fmtPan, clamp } from "../dsp.js";
import * as meters from "../meters.js";
import { undoGroup, scenesButton } from "../common.js";

const SUBTITLE = {
  PH3: "Each fader sets how loud a source is in your headphones.",
  AN1: "Each fader sets how loud a source is in your speakers.",
};
const DETAIL = {
  AN1: "XLR 1", AN2: "XLR 2", IN3: "Input 3", IN4: "Input 4",
};

let root, seg, sub, area, strips = [], master = null;
let current = "PH3";
let fh = 300;

export function mount(el) {
  root = h("div", { class: "page-inner mixer" });
  el.append(root);
  seg = new Segmented({ items: outItems(), value: current, label: "Mixing for", onChange: (v) => { current = v; build(); } });
  sub = h("div", { class: "page-sub" });
  root.append(h("div", { class: "toolbar" },
    h("span", { class: "toolbar-label" }, "Mixing for"), seg.el, h("div", { class: "spacer" }), undoGroup(), scenesButton()), sub);
  area = h("div", { class: "mixer-area" });
  root.append(area);
  let pending = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => {      // outside the observer callback: no resize loop
      const avail = el.clientHeight - 300;
      const next = clamp(Math.round(avail / 20) * 20, 180, 440);
      if (next !== fh && el.clientHeight > 0) { fh = next; build(); }
    });
  }).observe(el);
  subscribe(["strips", "prefs"], () => { refreshItems(); build(); });
  subscribe(["outputs"], () => { refreshItems(); if (master) master.sync(); });
  subscribe(["sends"], () => strips.forEach((s) => s.sync()));
  subscribe(["meters"], () => strips.forEach((s) => s.meters()));
  build();
}

function outItems() {
  return state.outputs.filter((o) => o.visible).map((o) => ({ value: o.id, label: o.name }));
}

function refreshItems() {
  const items = outItems();
  if (!items.some((i) => i.value === current)) current = "PH3";
  const old = seg.el;
  seg = new Segmented({ items, value: current, label: "Mixing for", onChange: (v) => { current = v; build(); } });
  old.replaceWith(seg.el);
}

function build() {
  strips = [];
  clear(area);
  const out = output(current);
  sub.textContent = SUBTITLE[current] || `Each fader sets how loud a source is in ${out ? out.name : "this output"}.`;
  const visible = state.strips.filter((s) => s.visible);
  const groups = [["Inputs", visible.filter((s) => s.kind === "in")], ["Computer", visible.filter((s) => s.kind === "pb")]];
  const scroller = h("div", { class: "strip-scroller" });
  for (const [label, list] of groups) {
    if (!list.length) continue;
    const g = h("div", { class: "strip-group" }, h("div", { class: "group-label" }, label));
    const row = h("div", { class: "strip-row" });
    for (const s of list) {
      const st = channelStrip(s);
      strips.push(st);
      row.append(st.el);
    }
    g.append(row);
    scroller.append(g);
  }
  master = masterStrip(current);
  area.append(scroller, master.el);
}

function channelStrip(s) {
  const sender = frameSender((a) => send("send", a));
  const st0 = sendOf(s.id, current);
  const name = h("div", { class: "strip-name", title: s.name }, s.name);
  renameable(name, { get: () => s.name, set: (v) => send("rename", { id: s.id, name: v }) });
  const detail = s.kind === "in"
    ? (s.stereo ? "Stereo" : DETAIL[s.channels[0]] || s.channels[0].replace("ADAT", "Opt ").replace("AS", "Opt "))
    : (s.stereo ? `Ch ${chNum(s.channels[0])}/${chNum(s.channels[1])}` : `Ch ${chNum(s.channels[0])}`);
  const value = h("div", { class: "strip-value num" });
  const fader = new VFader({
    db: st0.db, height: fh, label: `${s.name} level`,
    onInput: (db, g) => { value.textContent = fmtDb(db, { unit: false }); sender({ strip: s.id, out: current, db, gesture: g }); },
    onEnd: () => { sender.flush(); send("end_gesture"); },
  });
  const panVal = h("div", { class: "pan-value num" });
  const pan = new Pan({
    value: st0.pan, label: `${s.name} ${s.stereo ? "balance" : "pan"}`,
    onInput: (p, g) => { panVal.textContent = fmtPan(p); sender({ strip: s.id, out: current, pan: p, keep_db: true, gesture: g }); },
    onEnd: () => { sender.flush(); send("end_gesture"); },
  });
  const mts = s.meters.map((ch) => new MeterV({ height: fh, channel: ch }));
  const mute = h("button", { class: "strip-btn mute", "aria-label": `Mute ${s.name}`, title: "Mute in this output" }, "M");
  mute.addEventListener("click", () => send("send_mute", { strip: s.id, out: current, muted: mute.getAttribute("aria-pressed") !== "true" }));
  const link = h("button", {
    class: "strip-btn link", "aria-label": s.stereo ? "Split into two mono channels" : "Link as a stereo pair",
    title: s.stereo ? "Stereo pair · click to split" : "Link with its neighbour as a stereo pair",
    "aria-pressed": String(s.stereo),
  }, ico(s.stereo ? "link" : "unlink"));
  link.addEventListener("click", () => send("link", { pair: s.pair, linked: !s.stereo }));
  const el = h("div", { class: "strip" + (s.stereo ? " stereo" : ""), "data-id": s.id },
    h("div", { class: "strip-head" }, name, h("div", { class: "strip-sub" }, detail)),
    h("div", { class: "strip-pan" }, pan.el, panVal),
    h("div", { class: "strip-body" }, faderScale(fh), fader.el, h("div", { class: "meters" }, ...mts.map((m) => m.el))),
    value,
    h("div", { class: "strip-foot" }, mute, link));
  const sync = () => {
    const st = sendOf(s.id, current);
    fader.set(st.db);
    pan.set(st.pan);
    if (!fader.dragging) value.textContent = fmtDb(st.db, { unit: false });
    if (!pan.dragging) panVal.textContent = fmtPan(st.pan);
    mute.setAttribute("aria-pressed", String(st.muted));
    el.classList.toggle("is-muted", st.muted);
    fader.el.classList.toggle("muted", st.muted);
  };
  const metersSync = () => mts.forEach((m, i) => m.setAvailable(meters.available(s.meters[i])));
  sync();
  metersSync();
  return { el, sync, meters: metersSync };
}

const chNum = (ch) => ({ AN1: 1, AN2: 2, PH3: 3, PH4: 4, AS1: 5, AS2: 6, ADAT3: 7, ADAT4: 8, ADAT5: 9, ADAT6: 10, ADAT7: 11, ADAT8: 12 }[ch]);

function masterStrip(outId) {
  const o0 = output(outId);
  const sender = frameSender((a) => send("volume", a));
  const value = h("div", { class: "strip-value num" });
  const fader = new VFader({
    db: o0.volume_db, height: fh, max: o0.limit_db, label: `${o0.name} volume`,
    onInput: (db, g) => { value.textContent = fmtDb(db, { unit: false }); fader.el.classList.remove("ghost"); sender({ out: outId, db, gesture: g }); },
    onEnd: () => sender.flush(),
  });
  const knob = h("div", {
    class: "master-knob", title: "The knob on your Babyface also changes this volume, and Audius can’t see it. Your next change here fades in from quiet.",
  }, ico("dial"), h("span", {}, "Knob"));
  const power = toggleSwitch({ checked: o0.on, label: `${o0.name} on`, onToggle: (v) => send("output_on", { out: outId, on: v }) });
  const el = h("div", { class: "strip master" },
    h("div", { class: "strip-head" }, h("div", { class: "strip-name" }, o0.name), h("div", { class: "strip-sub" }, "Volume")),
    h("div", { class: "strip-pan" }, power),
    h("div", { class: "strip-body" }, faderScale(fh), fader.el),
    value,
    h("div", { class: "strip-foot" }, knob));
  const sync = () => {
    const o = output(outId);
    if (!o) return;
    const unknown = o.knob && !o.volume_fresh && (o.volume_db === null || o.volume_db <= -80);
    fader.max = o.limit_db;
    fader.set(o.volume_db);
    fader.el.classList.toggle("ghost", unknown && !fader.dragging);
    if (!fader.dragging) value.textContent = unknown ? "Knob" : fmtDb(o.volume_db, { unit: false });
    knob.classList.toggle("on", !o.volume_fresh);
    power.setChecked(o.on);
    el.classList.toggle("is-off", !o.on);
  };
  sync();
  return { el, sync };
}
