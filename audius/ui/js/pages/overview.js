// Overview: the daily screen. Where you listen, your mic, and what you hear.
import { h, ico, clear, menu, confirmPop, renameable } from "../ui.js";
import { state, subscribe, strip, output, input, sendOf } from "../store.js";
import { send, frameSender } from "../bridge.js";
import { Segmented, Slider, Dial, pill } from "../controls.js";
import { fmtDb, fmtGain } from "../dsp.js";
import * as meters from "../meters.js";
import { undoGroup, scenesButton } from "../common.js";

const MIX_TITLES = { PH3: "In your headphones", AN1: "From your speakers" };
const stripIcon = (s) => (s.kind === "pb" ? "computer" : s.channels[0].startsWith("AN") ? "mic"
  : s.channels[0].startsWith("IN") ? "instrument" : "optical");

let root, listen, grid, more, moreGrid, moreBtn;
const cards = [];

export function mount(el) {
  root = h("div", { class: "page-inner overview" });
  el.append(root);
  listen = new Segmented({
    size: "lg", label: "Listen on", value: state.listen === "none" ? null : state.listen,
    items: [
      { value: "headphones", label: "Headphones", icon: "headphones" },
      { value: "speakers", label: "Speakers", icon: "speaker" },
      { value: "both", label: "Both", icon: "both" },
    ],
    onChange: (v) => send("listen", { mode: v }),
  });
  root.append(h("div", { class: "toolbar" },
    h("span", { class: "toolbar-label" }, "Listen on"), listen.el,
    h("div", { class: "spacer" }), undoGroup(), scenesButton()));
  grid = h("div", { class: "ov-grid" });
  moreGrid = h("div", { class: "more-grid" });
  moreBtn = h("button", { class: "disclosure", "aria-expanded": "false" }, ico("chevronRight"), h("span", {}, "Other inputs"),
    h("span", { class: "more-summary" }));
  moreBtn.addEventListener("click", () => {
    state.ui_more = !state.ui_more;
    syncMore();
  });
  more = h("section", { class: "more" }, moreBtn, moreGrid);
  root.append(grid, more);
  build();
  subscribe(["strips", "overview_sources", "prefs"], build);
  subscribe(["inputs"], () => cards.forEach((c) => c.inputs && c.inputs()));
  subscribe(["outputs", "listen"], () => {
    listen.set(state.listen === "none" ? null : state.listen);
    cards.forEach((c) => c.outputs && c.outputs());
  });
  subscribe(["sends"], () => cards.forEach((c) => c.sends && c.sends()));
  subscribe(["meters"], () => cards.forEach((c) => c.meters && c.meters()));
}

function syncMore() {
  moreBtn.setAttribute("aria-expanded", String(!!state.ui_more));
  moreGrid.hidden = !state.ui_more;
}

function build() {
  cards.length = 0;
  clear(grid);
  clear(moreGrid);
  const hero = inputCard("AN1", true);
  const outs = [outputCard("PH3"), outputCard("AN1")];
  const others = ["AN2", "IN3", "IN4"].map((ch) => inputCard(ch, false));
  cards.push(hero, ...outs, ...others);       // every card gets live updates
  grid.append(hero.el, ...outs.map((c) => c.el));
  moreGrid.append(...others.map((c) => c.el));
  cards.forEach((c) => c.meters && c.meters());
  more.querySelector(".more-summary").textContent = others.map((c) => c.name()).join(" · ");
  syncMore();
}

// ---------------------------------------------------------------- input cards
function inputCard(ch, hero) {
  const inp = () => input(ch);
  const i0 = inp();
  const isMic = i0.kind === "mic";
  const channel = `in:${ch}`;
  const title = h("div", { class: "card-title" }, i0.name);
  renameable(title, { get: () => inp().name, set: (v) => send("rename", { id: channel, name: v }) });
  const sub = h("div", { class: "card-sub" }, isMic ? `XLR input ${ch.slice(-1)}` : `Instrument input ${ch.slice(-1)}`);
  const sender = frameSender((a) => send("gain", a));
  const value = h("div", { class: "dial-value num" }, fmtGain(i0.gain_db, i0.gain_step));
  const dial = new Dial({
    value: i0.gain_db, min: 0, max: i0.gain_max, step: i0.gain_step, size: hero ? 220 : 132, zone: hero,
    segments: hero ? 40 : 28, label: `${i0.name} gain`, channel,
    onInput: (v, g) => { value.textContent = fmtGain(v, i0.gain_step); sender({ ch, db: v, gesture: g }); },
    onEnd: () => { sender.flush(); send("end_gesture"); },
  });
  const peak = h("span", { class: "peak num" }, "");
  const clip = h("button", { class: "clip-badge", hidden: true, title: "Lower the gain, then click to clear" }, "Clipped");
  clip.addEventListener("click", () => { meters.clearClip(channel); clip.hidden = true; });
  meters.onClip(() => { clip.hidden = !meters.clipped(channel); });

  const b = new meters.Ballistics();
  let shown = null, lastT = 0;
  meters.register({
    el: peak,
    tick: (dt, now) => {
      b.step(meters.level(channel), dt, now);
      if (now - lastT > 140) {
        lastT = now;
        const v = b.hold > -99 ? Math.round(b.hold) : null;
        if (v !== shown) {
          shown = v;
          peak.textContent = v === null ? "" : `Peak ${fmtDb(v, { digits: 0, unit: false })} dBFS`;
        }
      }
      return !b.idle;
    },
  });

  const controls = h("div", { class: "input-controls" });
  let p48, pad, sens;
  if (isMic) {
    p48 = pill({
      label: "48V", cls: "phantom", pressed: i0.p48, title: "Phantom power for condenser mics",
      onToggle: async (on, el) => {
        if (on) {
          el.setPressed(false);
          const ok = await confirmPop(el, {
            title: "Turn on phantom power?",
            body: "48V powers condenser mics. It can harm ribbon mics, and switching it makes a pop, so turn your headphones down first.",
            ok: "Turn On 48V", okClass: "warn",
          });
          if (!ok) return;
          el.setPressed(true);
        } else {
          el.setPressed(false);
        }
        send("p48", { ch, on });
      },
    });
    pad = pill({
      label: "PAD", pressed: i0.pad, title: "Lowers the input by 11 dB for loud sources",
      onToggle: (on, el) => { el.setPressed(on); send("pad", { ch, on }); },
    });
    controls.append(p48, pad);
  } else {
    sens = new Segmented({
      size: "sm", label: "Reference level", value: i0.sens,
      items: [{ value: "-10dBV", label: "−10 dBV", title: "Consumer gear and instruments" },
              { value: "+4dBu", label: "+4 dBu", title: "Professional line level" }],
      onChange: (v) => send("sens", { ch, value: v }),
    });
    controls.append(sens.el);
  }

  const status = h("div", { class: "dial-status" }, peak, clip);
  const hint = hero ? h("div", { class: "dial-hint caption" }, "Aim the loudest peaks at the bracket") : null;
  const unavailable = h("div", { class: "dial-hint caption meter-na", hidden: true }, "Live level not available");
  const el = h("section", { class: `card input-card ${hero ? "hero" : "compact"}`, "aria-label": i0.name },
    h("div", { class: "card-head" },
      h("div", { class: "glyph-tile" }, ico(isMic ? "mic" : "instrument")),
      h("div", { class: "titles" }, title, sub)),
    h("div", { class: "dial-wrap" }, dial.el),
    h("div", { class: "dial-readout" }, value, status), hint, unavailable,
    controls);

  return {
    el,
    name: () => inp().name,
    inputs() {
      const i = inp();
      title.textContent = i.name;
      dial.set(i.gain_db);
      value.textContent = fmtGain(dial.value, i.gain_step);
      if (p48) p48.setPressed(i.p48);
      if (pad) pad.setPressed(i.pad);
      if (sens) sens.set(i.sens);
    },
    meters() {
      const ok = meters.available(channel);
      unavailable.hidden = ok || !state.meters.enabled;
      if (hint) hint.hidden = !ok;
      el.classList.toggle("no-meter", !ok);
    },
  };
}

// ---------------------------------------------------------------- output cards
function outputCard(outId) {
  const o0 = output(outId);
  const title = h("div", { class: "card-title" }, o0.name);
  renameable(title, { get: () => output(outId).name, set: (v) => send("rename", { id: outId, name: v }) });
  const offBtn = h("button", { class: "btn small", hidden: true, onclick: () => send("output_on", { out: outId, on: true }) },
    ico("power"), "Turn On");
  const head = h("div", { class: "card-head" },
    h("div", { class: "glyph-tile" }, ico(o0.kind === "speakers" ? "speaker" : o0.kind === "headphones" ? "headphones" : "optical")),
    h("div", { class: "titles" }, title, h("div", { class: "card-sub" }, o0.detail)), offBtn);

  // volume
  const volSender = frameSender((a) => send("volume", a));
  const volValue = h("div", { class: "row-value num" });
  const knobNote = h("span", {
    class: "knob-note", hidden: true,
    title: "The knob on your Babyface also changes this volume, and Audius can’t see it. Your next change here fades in from quiet.",
  }, ico("dial"));
  const vol = new Slider({
    db: o0.volume_db, label: `${o0.name} volume`, max: o0.limit_db, step: 1, page: 6,
    onInput: (db, g) => { volValue.textContent = fmtDb(db); vol.el.classList.remove("ghost"); volSender({ out: outId, db, gesture: g }); },
    onEnd: () => volSender.flush(),
  });
  const hintText = h("span", {});
  const startDb = () => state.prefs.speaker_start_db ?? -40;
  const startBtn = h("button", { class: "link-btn", onclick: () => send("volume", { out: outId, db: startDb() }) });
  const silentHint = h("div", { class: "inline-hint", hidden: true }, hintText, startBtn);
  const volRow = h("div", { class: "vol-row" },
    h("div", { class: "row-top" }, h("div", { class: "row-label" }, "Volume"), h("div", { class: "row-end" }, knobNote, volValue)),
    vol.el);

  // mix rows
  const rows = h("div", { class: "mix-rows" });
  const rowCtl = [];
  for (const sid of state.overview_sources[outId] || []) {
    const s = strip(sid);
    if (!s) continue;
    rowCtl.push(mixRow(s, outId, rows));
  }
  const addBtn = h("button", { class: "btn small plain add-source" }, ico("plus"), "Add source");
  addBtn.addEventListener("click", () => {
    const have = new Set(state.overview_sources[outId] || []);
    const options = state.strips.filter((s) => s.visible && !have.has(s.id));
    menu(addBtn, options.length ? [{ heading: "Show on this card" }, ...options.map((s) => ({
      label: s.name, icon: stripIcon(s),
      action: () => send("overview_sources", { out: outId, ids: [...have, s.id] }),
    }))] : [{ heading: "Every source is already here" }], { align: "start" });
  });

  const el = h("section", { class: "card out-card", "aria-label": o0.name },
    head, volRow, silentHint, h("div", { class: "section-title" }, MIX_TITLES[outId] || "In this output"), rows, addBtn);

  function outputs() {
    const o = output(outId);
    title.textContent = o.name;
    el.classList.toggle("is-off", !o.on);
    offBtn.hidden = o.on;
    vol.setMax(o.limit_db);
    const unknown = !o.volume_known;
    vol.el.classList.toggle("ghost", unknown && !vol.dragging);
    if (!vol.dragging) {
      vol.set(unknown ? null : o.volume_db);
      volValue.textContent = unknown ? (o.knob ? "On the knob" : "Not set") : fmtDb(o.volume_db);
    }
    volValue.classList.toggle("dimmer", unknown);
    volValue.title = unknown ? "Audius hasn’t set this volume yet, so it is wherever the Babyface has it. Your first change fades in from quiet." : "";
    knobNote.hidden = o.volume_fresh || unknown;
    const quiet = unknown || o.volume_db === null || o.volume_db <= -60;
    hintText.textContent = unknown ? "Speaker volume isn’t set yet." : "Speakers are silent.";
    startBtn.textContent = `Start at ${fmtDb(startDb(), { digits: 0 })}`;
    silentHint.hidden = !(o.kind === "speakers" && o.on && quiet);
  }
  outputs();
  return {
    el,
    outputs,
    sends: () => rowCtl.forEach((r) => r.sync()),
  };
}

function mixRow(s, outId, container) {
  const sender = frameSender((a) => send("send", a));
  const value = h("div", { class: "row-value num" });
  const st0 = sendOf(s.id, outId);
  const slider = new Slider({
    db: st0.db, label: `${s.name} in ${output(outId).name}`,
    cmeter: { channels: () => s.meters, offset: () => slider.db },
    onInput: (db, g) => { value.textContent = fmtDb(db); sender({ strip: s.id, out: outId, db, gesture: g }); },
    onEnd: () => { sender.flush(); send("end_gesture"); },
  });
  const mute = h("button", { class: "icon-btn mute", "aria-label": `Mute ${s.name}`, title: "Mute" }, ico("speakerSlash"));
  mute.addEventListener("click", () => send("send_mute", { strip: s.id, out: outId, muted: mute.getAttribute("aria-pressed") !== "true" }));
  const remove = h("button", { class: "icon-btn remove", "aria-label": `Remove ${s.name} from this card`, title: "Remove from card" }, ico("xmark"));
  remove.addEventListener("click", () => send("overview_sources", { out: outId, ids: (state.overview_sources[outId] || []).filter((x) => x !== s.id) }));
  const row = h("div", { class: "mix-row" },
    h("div", { class: "row-top" },
      h("div", { class: "row-label" }, h("span", { class: "src-ico" }, ico(stripIcon(s))), h("span", { class: "src-name" }, s.name)),
      h("div", { class: "row-end" }, value, remove, mute)),
    slider.el);
  container.append(row);
  const sync = () => {
    const st = sendOf(s.id, outId);
    slider.set(st.db);
    if (!slider.dragging) value.textContent = st.muted ? "Muted" : fmtDb(st.db);
    mute.setAttribute("aria-pressed", String(st.muted));
    slider.el.classList.toggle("muted", st.muted);
    row.classList.toggle("is-muted", st.muted);
  };
  sync();
  return { sync };
}
