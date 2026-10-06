// node tests/test_dsp.mjs : checks the interface's level maths.
import assert from "node:assert/strict";
import { dbToPos, posToDb, meterPos, meterDb, fmtDb, parseDb, fmtPan, UNITY_POS, MAX_DB } from "../audius/ui/js/dsp.js";

assert.equal(dbToPos(0), UNITY_POS);
assert.equal(dbToPos(null), 0);
assert.equal(posToDb(0), null);
assert.ok(Math.abs(dbToPos(MAX_DB) - 1) < 1e-9);
for (const db of [-79, -60, -41.5, -24, -12, -3, 0, 2.5, 6]) {
  assert.ok(Math.abs(posToDb(dbToPos(db)) - db) < 1e-9, `fader taper roundtrip ${db}`);
}
let prev = -1;
for (let p = 0.02; p <= 1; p += 0.01) {          // monotonic
  const d = posToDb(p);
  assert.ok(d > prev || prev === -1, `monotonic at ${p}`);
  prev = d;
}
for (const db of [-65, -55, -45, -35, -25, -12, -3, 0]) {
  assert.ok(Math.abs(meterDb(meterPos(db)) - db) < 1e-9, `meter roundtrip ${db}`);
}
assert.equal(meterPos(-20), 0.5);
assert.equal(fmtDb(null), "−∞ dB");
assert.equal(fmtDb(6.0206), "+6.0 dB");
assert.equal(fmtDb(-0.04), "0.0 dB");
assert.equal(fmtDb(-12.5), "−12.5 dB");
assert.equal(fmtDb(26, { digits: 0 }), "+26 dB");
assert.equal(parseDb("−12.5 dB"), -12.5);
assert.equal(parseDb("-inf"), null);
assert.equal(parseDb("loud"), undefined);
assert.equal(fmtPan(0), "C");
assert.equal(fmtPan(-0.4), "L40");
console.log("dsp.js: all checks passed");
