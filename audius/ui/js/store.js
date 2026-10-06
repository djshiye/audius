// Application state, mirrored from the Python model by patches.
export const state = {
  platform: {}, device: { connected: false }, inputs: [], outputs: [], strips: [], sends: {}, raw: {},
  listen: "none", overview_sources: {}, scenes: [], prefs: {}, undo: {}, meters: { channels: [] }, page: "overview",
};

const listeners = new Set();

export function subscribe(keys, fn) {
  const entry = { keys: new Set(keys), fn };
  listeners.add(entry);
  return () => listeners.delete(entry);
}

export function apply(patch) {
  const changed = new Set();
  for (const [k, v] of Object.entries(patch)) {
    if (k === "sends") {
      for (const [sid, outs] of Object.entries(v)) state.sends[sid] = { ...(state.sends[sid] || {}), ...outs };
    } else if (k === "raw") {
      Object.assign(state.raw, v);
    } else if (k === "device") {
      state.device = { ...state.device, ...v };
    } else {
      state[k] = v;
    }
    changed.add(k);
  }
  for (const l of listeners) {
    for (const k of changed) {
      if (l.keys.has(k) || l.keys.has("*")) {
        l.fn(changed, patch);
        break;
      }
    }
  }
}

export const strip = (id) => state.strips.find((s) => s.id === id);
export const output = (id) => state.outputs.find((o) => o.id === id);
export const input = (ch) => state.inputs.find((i) => i.ch === ch);
export const sendOf = (sid, out) => (state.sends[sid] || {})[out] || { db: null, pan: 0, muted: false };
