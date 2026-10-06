// Custom controls: segmented control, slider, vertical fader, gain dial, pan knob, meters.
import { h, ico, inlineEdit, reduceMotion } from "./ui.js";
import {
  clamp, dbToPos, posToDb, fmtDb, fmtPan, parseDb, meterPos, meterDb, levelZone,
  MAX_DB, UNITY_POS, ZONE_AMBER, ZONE_RED,
} from "./dsp.js";
import * as meters from "./meters.js";
import { newGesture } from "./bridge.js";

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};

// ---------------------------------------------------------------- spring for external changes
class Spring {
  constructor(apply) { this.apply = apply; this.v = 0; this.target = 0; this.vel = 0; this.raf = 0; }
  set(target, animate) {
    this.target = target;
    if (!animate || reduceMotion() || !isFinite(this.v)) {
      cancelAnimationFrame(this.raf);
      this.raf = 0; this.v = target; this.vel = 0; this.apply(target);
      return;
    }
    if (!this.raf) { this.last = performance.now(); this.raf = requestAnimationFrame((t) => this.step(t)); }
  }
  step(now) {
    const dt = Math.min(0.032, (now - this.last) / 1000);
    this.last = now;
    const k = 260, c = 2 * Math.sqrt(k);     // critically damped, settles in ~0.3 s
    this.vel += (-k * (this.v - this.target) - c * this.vel) * dt;
    this.v += this.vel * dt;
    if (Math.abs(this.v - this.target) < 0.0004 && Math.abs(this.vel) < 0.004) {
      this.v = this.target; this.vel = 0; this.raf = 0; this.apply(this.v);
      return;
    }
    this.apply(this.v);
    this.raf = requestAnimationFrame((t) => this.step(t));
  }
}

// Keyboard and wheel edits come in bursts; group each burst into one undo step.
class Burst {
  constructor(onEnd) { this.onEnd = onEnd; this.g = null; this.timer = 0; }
  id() {
    if (!this.g) this.g = newGesture();
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { const g = this.g; this.g = null; this.onEnd && this.onEnd(g); }, 700);
    return this.g;
  }
}

function drag(el, { start, move, end }) {
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const ctx = start(e);
    if (!ctx) return;
    e.preventDefault();
    try { el.setPointerCapture(e.pointerId); } catch (_) { /* synthetic or already-released pointer */ }
    el.classList.add("dragging");
    const x0 = e.clientX, y0 = e.clientY;
    const onMove = (ev) => move(ev, ctx, ev.clientX - x0, ev.clientY - y0);
    const onUp = (ev) => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.classList.remove("dragging");
      end && end(ev, ctx);
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.focus({ preventScroll: true });
  });
}

const INSET = 11;   // slider track inset, keeps the thumb inside the card at both ends
const wheelDelta = (e) => (e.deltaMode === 1 ? -e.deltaY * 0.5 : -e.deltaY * 0.035);

// ---------------------------------------------------------------- segmented control
export class Segmented {
  constructor({ items, value, onChange, size = "", label }) {
    this.items = items;
    this.onChange = onChange;
    this.thumb = h("div", { class: "seg-thumb" });
    this.buttons = items.map((it) => h("button", {
      role: "radio", "aria-checked": "false", title: it.title, "data-value": it.value,
      onclick: () => this.pick(it.value),
    }, it.icon ? ico(it.icon) : null, it.label ? h("span", {}, it.label) : null));
    this.el = h("div", { class: `seg ${size}`, role: "radiogroup", "aria-label": label }, this.thumb, ...this.buttons);
    this.el.addEventListener("keydown", (e) => {
      const i = this.items.findIndex((it) => it.value === this.value);
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const n = (Math.max(0, i) + (e.key === "ArrowRight" ? 1 : this.items.length - 1)) % this.items.length;
        this.pick(this.items[n].value);
        this.buttons[n].focus();
      }
    });
    new ResizeObserver(() => this.place(false)).observe(this.el);
    this.set(value, false);
  }
  pick(v) {
    if (v === this.value) return;
    this.set(v, true);
    this.onChange && this.onChange(v);
  }
  set(v, animate = true) {
    this.value = v;
    this.buttons.forEach((b, i) => {
      const on = this.items[i].value === v;
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.tabIndex = on || (v == null && i === 0) ? 0 : -1;
    });
    this.place(animate);
  }
  place(animate) {
    const i = this.items.findIndex((it) => it.value === this.value);
    const b = this.buttons[i];
    if (!b || !b.offsetWidth) { this.thumb.style.opacity = i < 0 ? "0" : this.thumb.style.opacity; return; }
    if (!animate) this.thumb.style.transition = "none";
    this.thumb.style.opacity = "1";
    this.thumb.style.width = b.offsetWidth + "px";
    this.thumb.style.transform = `translateX(${b.offsetLeft}px)`;
    if (!animate) requestAnimationFrame(() => { this.thumb.style.transition = ""; });
  }
}

// ---------------------------------------------------------------- pill & switch
export function pill({ label, pressed = false, cls = "", title, onToggle }) {
  const el = h("button", { class: `pill ${cls}`, "aria-pressed": String(pressed), title },
    h("span", { class: "led" }), h("span", {}, label));
  el.addEventListener("click", () => onToggle(el.getAttribute("aria-pressed") !== "true", el));
  el.setPressed = (v) => el.setAttribute("aria-pressed", String(!!v));
  return el;
}

export function toggleSwitch({ checked = false, label, onToggle }) {
  const el = h("button", { class: "switch", role: "switch", "aria-checked": String(checked), "aria-label": label });
  el.addEventListener("click", () => {
    const v = el.getAttribute("aria-checked") !== "true";
    el.setAttribute("aria-checked", String(v));
    onToggle(v);
  });
  el.setChecked = (v) => el.setAttribute("aria-checked", String(!!v));
  return el;
}

// ---------------------------------------------------------------- level slider (horizontal)
// Values are dB (null = -inf) on the fader taper. Clicking the track pages by `page` dB toward
// the pointer rather than jumping there, so a stray click can't make anything much louder.
export class Slider {
  constructor({ db = null, label, page = 6, step = 0.5, max = MAX_DB, unity = true, cmeter = null,
                onInput, onEnd, onEdit, format = (v) => fmtDb(v) }) {
    this.db = db; this.page = page; this.step = step; this.max = max; this.label = label;
    this.onInput = onInput; this.onEnd = onEnd; this.format = format;
    this.fill = h("div", { class: "fill" });
    this.thumb = h("div", { class: "thumb" });
    this.el = h("div", {
      class: "slider", role: "slider", tabindex: "0", "aria-label": label,
      "aria-valuemin": "0", "aria-valuemax": "1", "aria-orientation": "horizontal",
    }, h("div", { class: "track" }, this.fill), unity ? h("div", { class: "detent", vars: { "--unity": UNITY_POS } }) : null, this.thumb);
    if (cmeter) this.attachMeter(cmeter);
    this.spring = new Spring((p) => this.el.style.setProperty("--pos", p));
    this.burst = new Burst((g) => this.onEnd && this.onEnd(g));
    new ResizeObserver(() => this.el.style.setProperty("--w", this.el.clientWidth - 2 * INSET + "px")).observe(this.el);
    this.dragging = false;

    drag(this.el, {
      start: (e) => {
        const b = this.el.getBoundingClientRect();
        const r = { left: b.left + INSET, width: Math.max(1, b.width - 2 * INSET) };
        const pos = dbToPos(this.db);
        const thumbX = r.left + pos * r.width;
        const g = newGesture();
        if (e.altKey || e.ctrlKey) {        // reset to unity
          this.commit(0, g);
          this.onEnd && this.onEnd(g);
          return null;
        }
        let startPos = pos;
        if (Math.abs(e.clientX - thumbX) > 14) {
          const dir = e.clientX > thumbX ? 1 : -1;
          const cur = this.db === null ? -70 : this.db;
          const target = dir > 0 ? Math.min(this.max, cur + this.page) : cur - this.page < -64 ? null : cur - this.page;
          this.commit(target, g, true);
          startPos = dbToPos(target);
        }
        this.dragging = true;
        return { g, w: r.width, startPos };
      },
      move: (e, ctx, dx) => {
        const fine = e.shiftKey ? 0.25 : 1;
        const p = clamp(ctx.startPos + (dx * fine) / ctx.w, 0, dbToPos(this.max));
        const db = posToDb(p);
        this.commit(db === null ? null : Math.round(db * 10) / 10, ctx.g);
      },
      end: (e, ctx) => {
        this.dragging = false;
        this.onEnd && this.onEnd(ctx.g);
      },
    });
    this.el.addEventListener("keydown", (e) => {
      const small = e.shiftKey ? 0.1 : this.step;
      const cur = this.db;
      let v;
      if (e.key === "ArrowRight" || e.key === "ArrowUp") v = cur === null ? -60 : Math.min(this.max, cur + small);
      else if (e.key === "ArrowLeft" || e.key === "ArrowDown") v = cur === null ? null : cur - small < -80 ? null : cur - small;
      else if (e.key === "PageUp") v = cur === null ? -40 : Math.min(this.max, cur + this.page);
      else if (e.key === "PageDown") v = cur === null ? null : cur - this.page < -64 ? null : cur - this.page;
      else if (e.key === "Home") v = null;
      else if (e.key === "End") v = Math.min(0, this.max);
      else if (e.key === "Enter") { this.edit(); e.preventDefault(); return; }
      else return;
      e.preventDefault();
      this.commit(v === null ? null : Math.round(v * 10) / 10, this.burst.id(), true);
    });
    this.el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const d = wheelDelta(e);
      const cur = this.db === null ? (d > 0 ? -64 : null) : this.db;
      if (cur === null) return;
      const v = cur + d < -70 ? null : Math.min(this.max, cur + d);
      this.commit(v === null ? null : Math.round(v * 10) / 10, this.burst.id(), true);
    }, { passive: false });
    this.thumb.addEventListener("dblclick", () => this.edit());
    this.set(db, false);
  }
  edit() {
    inlineEdit(this.thumb, {
      value: this.db === null ? "-inf" : this.db.toFixed(1),
      onCommit: (t) => {
        const v = parseDb(t);
        if (v === undefined) return;
        const g = newGesture();
        this.commit(v === null ? null : clamp(v, -80, this.max), g, true);
        this.onEnd && this.onEnd(g);
      },
    });
  }
  commit(db, g, animate = false) {
    this.db = db;
    this.spring.set(dbToPos(db), animate);
    this.aria();
    this.onInput && this.onInput(db, g);
  }
  set(db, animate = true) {
    if (this.dragging) return;
    this.db = db;
    this.spring.set(dbToPos(db), animate);
    this.aria();
  }
  aria() {
    this.el.setAttribute("aria-valuenow", dbToPos(this.db).toFixed(3));
    this.el.setAttribute("aria-valuetext", this.format(this.db));
  }
  setMax(max) { this.max = max; }
  attachMeter({ channels, offset }) {
    this.cover = h("div", { class: "cover" });
    this.el.append(h("div", { class: "cmeter", "aria-hidden": "true" }, this.cover));
    const b = new meters.Ballistics();
    meters.register({
      el: this.el,
      tick: (dt, now) => {
        let lvl = null;
        for (const c of channels()) {
          const v = meters.level(c);
          if (v !== null && (lvl === null || v > lvl)) lvl = v;
        }
        const off = offset();
        const target = lvl === null || off === null ? null : lvl + off;
        b.step(target, dt, now);
        this.cover.style.transform = `scaleX(${(1 - meterPos(b.disp)).toFixed(4)})`;
        return !b.idle;
      },
    });
  }
}

// ---------------------------------------------------------------- vertical fader
export class VFader {
  constructor({ db = null, height = 260, label, page = 6, max = MAX_DB, onInput, onEnd }) {
    this.db = db; this.h = height; this.page = page; this.max = max; this.onInput = onInput; this.onEnd = onEnd;
    this.cap = h("div", { class: "cap" });
    const ticks = [MAX_DB, 0, -12, -24, -40, -60].map((d) =>
      h("div", { class: "tick" + (d === 0 ? " unity" : ""), style: { top: (1 - dbToPos(d)) * height + "px" } }));
    this.el = h("div", {
      class: "vfader", role: "slider", tabindex: "0", "aria-label": label, "aria-orientation": "vertical",
      "aria-valuemin": "0", "aria-valuemax": "1", vars: { "--h": height + "px" },
    }, ...ticks, h("div", { class: "groove" }, h("div", { class: "vfill" })), this.cap);
    this.spring = new Spring((p) => this.el.style.setProperty("--pos", p));
    this.burst = new Burst((g) => this.onEnd && this.onEnd(g));
    this.dragging = false;
    drag(this.el, {
      start: (e) => {
        const r = this.el.getBoundingClientRect();
        const pos = dbToPos(this.db);
        const capY = r.top + (1 - pos) * height;
        const g = newGesture();
        if (e.altKey || e.ctrlKey) { this.commit(0, g, true); this.onEnd && this.onEnd(g); return null; }
        let startPos = pos;
        if (Math.abs(e.clientY - capY) > 16) {
          const dir = e.clientY < capY ? 1 : -1;
          const cur = this.db === null ? -70 : this.db;
          const t = dir > 0 ? Math.min(this.max, cur + this.page) : cur - this.page < -64 ? null : cur - this.page;
          this.commit(t, g, true);
          startPos = dbToPos(t);
        }
        this.dragging = true;
        return { g, startPos };
      },
      move: (e, ctx, dx, dy) => {
        const fine = e.shiftKey ? 0.25 : 1;
        const p = clamp(ctx.startPos - (dy * fine) / height, 0, dbToPos(this.max));
        const v = posToDb(p);
        this.commit(v === null ? null : Math.round(v * 10) / 10, ctx.g);
      },
      end: (e, ctx) => { this.dragging = false; this.onEnd && this.onEnd(ctx.g); },
    });
    this.el.addEventListener("keydown", (e) => {
      const small = e.shiftKey ? 0.1 : 0.5;
      const cur = this.db;
      let v;
      if (e.key === "ArrowUp" || e.key === "ArrowRight") v = cur === null ? -60 : Math.min(this.max, cur + small);
      else if (e.key === "ArrowDown" || e.key === "ArrowLeft") v = cur === null ? null : cur - small < -80 ? null : cur - small;
      else if (e.key === "PageUp") v = cur === null ? -40 : Math.min(this.max, cur + this.page);
      else if (e.key === "PageDown") v = cur === null ? null : cur - this.page < -64 ? null : cur - this.page;
      else if (e.key === "Home") v = null;
      else if (e.key === "End") v = 0;
      else return;
      e.preventDefault();
      this.commit(v === null ? null : Math.round(v * 10) / 10, this.burst.id(), true);
    });
    this.el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const d = wheelDelta(e);
      const cur = this.db === null ? (d > 0 ? -64 : null) : this.db;
      if (cur === null) return;
      const v = cur + d < -70 ? null : Math.min(this.max, cur + d);
      this.commit(v === null ? null : Math.round(v * 10) / 10, this.burst.id(), true);
    }, { passive: false });
    this.set(db, false);
  }
  commit(db, g, animate = false) {
    this.db = db;
    this.spring.set(dbToPos(db), animate);
    this.aria();
    this.onInput && this.onInput(db, g);
  }
  set(db, animate = true) {
    if (this.dragging) return;
    this.db = db;
    this.spring.set(dbToPos(db), animate);
    this.aria();
  }
  aria() {
    this.el.setAttribute("aria-valuenow", dbToPos(this.db).toFixed(3));
    this.el.setAttribute("aria-valuetext", fmtDb(this.db));
  }
}

export function faderScale(height) {
  const marks = [[MAX_DB, "+6"], [0, "0"], [-12, "12"], [-24, "24"], [-40, "40"], [-60, "60"], [null, "∞"]];
  return h("div", { class: "vscale", vars: { "--h": height + "px" }, "aria-hidden": "true" },
    ...marks.map(([d, t]) => h("span", { style: { top: (1 - dbToPos(d)) * height + "px" } }, t)));
}

// ---------------------------------------------------------------- vertical meter
export class MeterV {
  constructor({ height = 260, channel, offset = () => 0 }) {
    this.cover = h("div", { class: "cover" });
    this.hold = h("div", { class: "hold" });
    this.el = h("div", { class: "meter-v", vars: { "--h": height + "px" }, "aria-hidden": "true" }, this.cover, this.hold);
    this.channel = channel;
    const b = new meters.Ballistics();
    meters.register({
      el: this.el,
      tick: (dt, now) => {
        const lvl = meters.level(this.channel);
        const off = offset();
        b.step(lvl === null || off === null ? null : lvl + off, dt, now);
        const p = meterPos(b.disp);
        this.cover.style.transform = `scaleY(${(1 - p).toFixed(4)})`;
        const hp = meterPos(b.hold);
        this.hold.style.opacity = hp > 0.02 ? "0.9" : "0";
        this.hold.style.transform = `translateY(${(-hp * height).toFixed(1)}px)`;
        return !b.idle;
      },
    });
  }
  setAvailable(ok) { this.el.classList.toggle("na", !ok); }
}

// ---------------------------------------------------------------- gain dial (the signature control)
const ARC = 270;
const A0 = -135;
function polar(cx, cy, r, deg) {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arcPath(cx, cy, r, d0, d1) {
  const [x0, y0] = polar(cx, cy, r, d0);
  const [x1, y1] = polar(cx, cy, r, d1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${d1 - d0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
function sector(cx, cy, r0, r1, d0, d1) {
  const [a, b] = polar(cx, cy, r1, d0), [c, d] = polar(cx, cy, r1, d1);
  const [e, f] = polar(cx, cy, r0, d1), [g, k] = polar(cx, cy, r0, d0);
  return `M${a.toFixed(2)} ${b.toFixed(2)} A${r1} ${r1} 0 0 1 ${c.toFixed(2)} ${d.toFixed(2)} L${e.toFixed(2)} ${f.toFixed(2)} A${r0} ${r0} 0 0 0 ${g.toFixed(2)} ${k.toFixed(2)}Z`;
}

export class Dial {
  constructor({ value, min = 0, max = 65, step = 1, size = 210, label, channel = null, zone = true,
                segments = 40, onInput, onEnd, format }) {
    Object.assign(this, { value, min, max, step, size, label, channel, onInput, onEnd });
    this.format = format || ((v) => fmtDb(v, { digits: step < 1 ? 1 : 0 }));
    const s = svgEl("svg", { class: "ring", viewBox: "0 0 200 200", "aria-hidden": "true" });
    // gain track + arc (accent = the value you set)
    s.append(svgEl("path", { class: "gain-track", d: arcPath(100, 100, 77, A0, A0 + ARC), fill: "none", "stroke-width": "3", "stroke-linecap": "round" }));
    this.gainArc = svgEl("path", { class: "gain-arc", d: arcPath(100, 100, 77, A0, A0 + ARC), fill: "none", "stroke-width": "3", "stroke-linecap": "round", pathLength: "1000", "stroke-dasharray": "1000 1000" });
    s.append(this.gainArc);
    // LED ring (green/amber/red = signal only)
    this.leds = [];
    const per = ARC / segments;
    for (let i = 0; i < segments; i++) {
      const d0 = A0 + i * per + per * 0.14, d1 = A0 + (i + 1) * per - per * 0.14;
      const mid = (i + 0.5) / segments;
      const db = meterDb(mid);
      const p = svgEl("path", { d: sector(100, 100, 87, 95, d0, d1), class: "seg-led ring-off" });
      p.dataset.zone = levelZone(db);
      s.append(p);
      this.leds.push({ el: p, pos: (i + 1) / segments, zone: levelZone(db), state: "off" });
    }
    if (zone) {      // where RME suggests the loudest peaks should land
      const z0 = A0 + ARC * meterPos(ZONE_AMBER), z1 = A0 + ARC * meterPos(ZONE_RED);
      s.append(svgEl("path", { class: "zone", d: arcPath(100, 100, 100.5, z0, z1), fill: "none", "stroke-width": "1.4", "stroke-linecap": "round" }));
      for (const d of [z0, z1]) {
        const [x0, y0] = polar(100, 100, 98.2, d), [x1, y1] = polar(100, 100, 102.8, d);
        s.append(svgEl("path", { class: "zone", d: `M${x0} ${y0}L${x1} ${y1}`, "stroke-width": "1.4", "stroke-linecap": "round" }));
      }
    }
    this.pointer = h("div", { class: "pointer" });
    this.el = h("div", {
      class: "dial", role: "slider", tabindex: "0", "aria-label": label,
      "aria-valuemin": String(min), "aria-valuemax": String(max), vars: { "--size": size + "px" },
      title: zone ? "Drag up or down. Aim the loudest peaks inside the bracket (−12 to −3 dBFS)." : "Drag up or down",
    }, s, h("div", { class: "bezel" }), h("div", { class: "knob" }, this.pointer));
    this.spring = new Spring((v) => this.render(v));
    this.burst = new Burst((g) => this.onEnd && this.onEnd(g));
    this.dragging = false;

    drag(this.el, {
      start: () => { this.dragging = true; return { g: newGesture(), v0: this.value, acc: 0 }; },
      move: (e, ctx, dx, dy) => {
        const fine = e.shiftKey ? 0.25 : 1;
        const range = this.max - this.min;
        const raw = ctx.v0 + ((dx - dy) * fine * range) / 300;
        const v = clamp(Math.round(raw / this.step) * this.step, this.min, this.max);
        if (v !== this.value) this.commit(v, ctx.g, false);
      },
      end: (e, ctx) => { this.dragging = false; this.onEnd && this.onEnd(ctx.g); },
    });
    this.el.addEventListener("keydown", (e) => {
      let v = this.value;
      const big = this.step < 1 ? 3 : 6;
      if (e.key === "ArrowUp" || e.key === "ArrowRight") v += this.step;
      else if (e.key === "ArrowDown" || e.key === "ArrowLeft") v -= this.step;
      else if (e.key === "PageUp") v += big;
      else if (e.key === "PageDown") v -= big;
      else if (e.key === "Home") v = this.min;
      else if (e.key === "End") v = this.max;
      else if (e.key === "Enter") { e.preventDefault(); this.edit(); return; }
      else return;
      e.preventDefault();
      v = clamp(v, this.min, this.max);
      if (v !== this.value) this.commit(v, this.burst.id(), true);
    });
    this.el.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.wheelAcc = (this.wheelAcc || 0) + (e.deltaMode === 1 ? -e.deltaY : -e.deltaY / 40);
      const steps = Math.trunc(this.wheelAcc);
      if (!steps) return;
      this.wheelAcc -= steps;
      const v = clamp(this.value + steps * this.step, this.min, this.max);
      if (v !== this.value) this.commit(v, this.burst.id(), true);
    }, { passive: false });
    this.el.addEventListener("dblclick", () => this.edit());
    if (channel) this.attachMeter();
    this.set(value, false);
  }
  edit() {
    inlineEdit(this.el, {
      value: String(this.value),
      onCommit: (t) => {
        const v = parseDb(t);
        if (v === undefined || v === null) return;
        const q = clamp(Math.round(v / this.step) * this.step, this.min, this.max);
        const g = newGesture();
        this.commit(q, g, true);
        this.onEnd && this.onEnd(g);
      },
    });
  }
  frac(v) { return (v - this.min) / (this.max - this.min); }
  render(v) {
    const f = clamp(this.frac(v), 0, 1);
    this.el.style.setProperty("--angle", `${A0 + f * ARC}deg`);
    this.gainArc.setAttribute("stroke-dashoffset", String(1000 - f * 1000));
  }
  commit(v, g, animate) {
    this.value = v;
    this.spring.set(v, animate);
    this.aria();
    this.onInput && this.onInput(v, g);
  }
  set(v, animate = true) {
    if (this.dragging) return;
    this.value = v;
    this.spring.set(v, animate);
    this.aria();
  }
  aria() {
    this.el.setAttribute("aria-valuenow", String(this.value));
    this.el.setAttribute("aria-valuetext", "Gain " + this.format(this.value));
  }
  setChannel(ch) { this.channel = ch; }
  attachMeter() {
    const b = new meters.Ballistics();
    this.meterOk = true;
    meters.register({
      el: this.el,
      tick: (dt, now) => {
        const lvl = this.channel ? meters.level(this.channel) : null;
        b.step(lvl, dt, now);
        const p = meterPos(b.disp);
        const hp = meterPos(b.hold);
        for (const led of this.leds) {
          const lit = led.pos <= p + 1e-6 || (hp > 0.03 && Math.abs(led.pos - hp) < 0.5 / this.leds.length + 1e-6 && led.pos <= hp + 1e-6);
          const st = lit ? led.zone : "off";
          if (st !== led.state) {
            led.state = st;
            led.el.setAttribute("class", "seg-led ring-" + st);
          }
        }
        return !b.idle;
      },
    });
  }
}

// ---------------------------------------------------------------- pan knob
export class Pan {
  constructor({ value = 0, label, onInput, onEnd }) {
    Object.assign(this, { value, onInput, onEnd });
    const s = svgEl("svg", { viewBox: "0 0 34 34", "aria-hidden": "true" });
    s.append(svgEl("path", { class: "pan-track", d: arcPath(17, 17, 15, A0, A0 + ARC), fill: "none", "stroke-width": "2.4", "stroke-linecap": "round" }));
    this.arc = svgEl("path", { class: "pan-arc", fill: "none", "stroke-width": "2.4", "stroke-linecap": "round" });
    s.append(this.arc);
    s.append(svgEl("circle", { class: "pan-cap", cx: "17", cy: "17", r: "10.5" }));
    this.ptr = svgEl("path", { class: "pan-ptr", d: "M17 17V9.5", "stroke-width": "2", "stroke-linecap": "round" });
    s.append(this.ptr);
    this.el = h("div", {
      class: "pan", role: "slider", tabindex: "0", "aria-label": label, "aria-valuemin": "-1", "aria-valuemax": "1",
      title: "Pan · double-click to centre",
    }, s);
    this.burst = new Burst((g) => this.onEnd && this.onEnd(g));
    this.dragging = false;
    drag(this.el, {
      start: () => { this.dragging = true; return { g: newGesture(), v0: this.value }; },
      move: (e, ctx, dx, dy) => {
        const fine = e.shiftKey ? 0.25 : 1;
        let v = clamp(ctx.v0 + ((dx - dy) * fine) / 110, -1, 1);
        if (Math.abs(v) < 0.025) v = 0;           // gentle detent at centre
        this.commit(Math.round(v * 100) / 100, ctx.g);
      },
      end: (e, ctx) => { this.dragging = false; this.onEnd && this.onEnd(ctx.g); },
    });
    this.el.addEventListener("dblclick", () => { const g = newGesture(); this.commit(0, g); this.onEnd && this.onEnd(g); });
    this.el.addEventListener("keydown", (e) => {
      let v = this.value;
      if (e.key === "ArrowRight" || e.key === "ArrowUp") v += 0.05;
      else if (e.key === "ArrowLeft" || e.key === "ArrowDown") v -= 0.05;
      else if (e.key === "Home") v = 0;
      else return;
      e.preventDefault();
      this.commit(Math.round(clamp(v, -1, 1) * 100) / 100, this.burst.id());
    });
    this.el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const d = e.deltaMode === 1 ? -e.deltaY * 0.05 : -e.deltaY * 0.004;
      this.commit(Math.round(clamp(this.value + d, -1, 1) * 100) / 100, this.burst.id());
    }, { passive: false });
    this.render();
  }
  render() {
    const ang = this.value * 135;
    this.ptr.setAttribute("transform", `rotate(${ang} 17 17)`);
    if (Math.abs(this.value) < 0.005) this.arc.setAttribute("d", "");
    else this.arc.setAttribute("d", this.value > 0 ? arcPath(17, 17, 15, 0, ang) : arcPath(17, 17, 15, ang, 0));
    this.el.setAttribute("aria-valuenow", String(this.value));
    this.el.setAttribute("aria-valuetext", fmtPan(this.value));
  }
  commit(v, g) { this.value = v; this.render(); this.onInput && this.onInput(v, g); }
  set(v) { if (!this.dragging) { this.value = v; this.render(); } }
}
