// Level maths shared by every control.
export const MINUS = "−";
export const UNITY = 32768;
export const MAX_RAW = 65536;
export const MAX_DB = 20 * Math.log10(MAX_RAW / UNITY);   // +6.02

export const rawToDb = (r) => (r <= 0 ? null : 20 * Math.log10(r / UNITY));
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

// Fader taper: position 0..1 <-> dB (null = -inf). Unity sits at 80% of travel.
const ANCHORS = [[0.015, -80], [0.05, -60], [0.25, -40], [0.45, -24], [0.62, -12], [0.8, 0], [1.0, MAX_DB]];
export const UNITY_POS = 0.8;
export const FADER_TICKS = [MAX_DB, 0, -6, -12, -24, -40, -60, null];

export function posToDb(p) {
  if (p < ANCHORS[0][0]) return null;
  for (let i = 1; i < ANCHORS.length; i++) {
    const [p1, d1] = ANCHORS[i];
    if (p <= p1) {
      const [p0, d0] = ANCHORS[i - 1];
      return d0 + ((p - p0) / (p1 - p0)) * (d1 - d0);
    }
  }
  return MAX_DB;
}

export function dbToPos(db) {
  if (db === null || db === undefined || !isFinite(db)) return 0;
  if (db <= ANCHORS[0][1]) return ANCHORS[0][0];
  for (let i = 1; i < ANCHORS.length; i++) {
    const [p1, d1] = ANCHORS[i];
    if (db <= d1) {
      const [p0, d0] = ANCHORS[i - 1];
      return p0 + ((db - d0) / (d1 - d0)) * (p1 - p0);
    }
  }
  return 1;
}

// Meter deflection (IEC 60268-18): more room near the top, where levels matter.
export function meterPos(db) {
  if (db === null || db === undefined || db < -70) return 0;
  if (db < -60) return (db + 70) * 0.0025;
  if (db < -50) return (db + 60) * 0.005 + 0.025;
  if (db < -40) return (db + 50) * 0.0075 + 0.075;
  if (db < -30) return (db + 40) * 0.015 + 0.15;
  if (db < -20) return (db + 30) * 0.02 + 0.3;
  if (db < 0) return (db + 20) * 0.025 + 0.5;
  return 1;
}
export function meterDb(pos) {   // inverse of meterPos
  if (pos <= 0) return -70;
  if (pos < 0.025) return pos / 0.0025 - 70;
  if (pos < 0.075) return (pos - 0.025) / 0.005 - 60;
  if (pos < 0.15) return (pos - 0.075) / 0.0075 - 50;
  if (pos < 0.3) return (pos - 0.15) / 0.015 - 40;
  if (pos < 0.5) return (pos - 0.3) / 0.02 - 30;
  return (pos - 0.5) / 0.025 - 20;
}
export const ZONE_AMBER = -12;   // RME: let the loudest peaks reach about -3 dBFS
export const ZONE_RED = -3;
export const levelZone = (db) => (db >= ZONE_RED ? "r" : db >= ZONE_AMBER ? "a" : "g");

export function fmtDb(db, { digits = 1, unit = true, plus = true } = {}) {
  if (db === null || db === undefined || !isFinite(db)) return "−∞" + (unit ? " dB" : "");
  const v = Math.abs(db) < 0.5 * 10 ** -digits ? 0 : db;
  const sign = v > 0 ? (plus ? "+" : "") : v < 0 ? MINUS : "";
  return sign + Math.abs(v).toFixed(digits) + (unit ? " dB" : "");
}

export function fmtGain(db, step) {
  return fmtDb(db, { digits: step < 1 ? 1 : 0 });
}

export function fmtPan(p) {
  if (Math.abs(p) < 0.005) return "C";
  return (p < 0 ? "L" : "R") + Math.round(Math.abs(p) * 100);
}

export function parseDb(text) {
  const t = String(text).trim().replace(/−/g, "-").replace(/\s*db\s*$/i, "").trim();
  if (/^(-?inf|-?∞|off|mute)$/i.test(t)) return null;
  const v = parseFloat(t);
  return Number.isFinite(v) ? v : undefined;
}

export function fmtRate(hz) {
  if (!hz) return null;
  const k = hz / 1000;
  return (Number.isInteger(k) ? k.toFixed(0) : k.toFixed(1)) + " kHz";
}
