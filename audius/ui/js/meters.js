// Meter engine: levels arrive ~30x a second; displays animate every frame with
// instant attack, smooth release and a short peak hold, like a hardware PPM.
import { state } from "./store.js";

const RELEASE_DB_S = 26;
const HOLD_MS = 1200;
const HOLD_FALL_DB_S = 40;
const FLOOR = -100;
const CLIP_DB = -0.1;

const levels = {};          // channel -> {peak, rms, t}
const clips = new Set();    // latched channels
const targets = new Set();
const clipListeners = new Set();
let running = false;
let last = 0;

export function setLevels(obj) {
  const now = performance.now();
  let clipChanged = false;
  for (const [k, [peak, rms]] of Object.entries(obj)) {
    levels[k] = { peak, rms, t: now };
    if (peak >= CLIP_DB && !clips.has(k)) {
      clips.add(k);
      clipChanged = true;
    }
  }
  if (clipChanged) for (const fn of clipListeners) fn();
  start();
}

export function available(ch) {
  return (state.meters.channels || []).includes(ch);
}

// Current level of a channel in dBFS, or null when there is nothing to show.
export function level(ch) {
  const l = levels[ch];
  if (!l || performance.now() - l.t > 600) return null;
  return l.peak;
}

export const clipped = (ch) => clips.has(ch);
export function clearClip(...chs) {
  for (const c of chs) clips.delete(c);
  for (const fn of clipListeners) fn();
}
export function onClip(fn) {
  clipListeners.add(fn);
  return () => clipListeners.delete(fn);
}

export class Ballistics {
  constructor() { this.disp = FLOOR; this.hold = FLOOR; this.holdT = 0; }
  step(target, dt, now) {
    const t = target === null || target === undefined ? FLOOR : Math.max(FLOOR, target);
    if (t >= this.disp) this.disp = t;
    else this.disp = Math.max(t, this.disp - RELEASE_DB_S * dt);
    if (this.disp >= this.hold) { this.hold = this.disp; this.holdT = now; }
    else if (now - this.holdT > HOLD_MS) this.hold = Math.max(this.disp, this.hold - HOLD_FALL_DB_S * dt);
    return this;
  }
  get idle() { return this.disp <= FLOOR + 0.01 && this.hold <= FLOOR + 0.01; }
}

// target: { tick(dt, now) -> boolean still animating }
export function register(target) {
  targets.add(target);
  start();
  return () => targets.delete(target);
}

function start() {
  if (running) return;
  running = true;
  last = performance.now();
  requestAnimationFrame(frame);
}

function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  let busy = false;
  for (const t of targets) {
    if (!t.el || t.el.isConnected) {
      if (t.tick(dt, now)) busy = true;
    } else {
      targets.delete(t);
    }
  }
  const fresh = Object.values(levels).some((l) => now - l.t < 700);
  if (busy || fresh) requestAnimationFrame(frame);
  else running = false;
}
