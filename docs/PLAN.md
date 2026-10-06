# Audius: plan

A control panel for the **RME Babyface Pro FS in Class Compliant (CC) mode** on Fedora/GNOME.
It replaces alsamixer and TotalMix FX (which doesn't exist on Linux) with one window that makes
the daily jobs obvious (set the mic, choose where you listen, balance what you hear) and keeps
the full TotalMix-style matrix one click away.

## 1. What the hardware gives us

Everything goes through the kernel's `snd-usb-audio` quirk for USB `2a39:3fb0`
(`sound/usb/mixer_quirks.c`, `snd_bbfpro_*`). It exposes 316 ALSA controls on the card:

| Controls | Count | Range | Meaning |
|---|---|---|---|
| `Mic-AN{1,2}-<out> Playback Volume`, `Line-<in>-<out> Playback Volume` | 144 | 0–65536 | Hardware input → hardware output send (TotalMix submix) |
| `PCM-<ch>-<out> Playback Volume` | 144 | 0–65536 | Computer playback channel → hardware output send |
| `Main-Out <out>` | 12 | 0–65536 | Hardware output volume (TotalMix's third row, the knob's target) |
| `Mic-AN{1,2} Gain` | 2 | 0–65 | Preamp gain in dB, 1 dB steps |
| `Line-IN{3,4} Gain` | 2 | 0–18 | Instrument/line gain, 0.5 dB steps (0–9 dB) |
| `Mic-AN{1,2} 48V`, `Mic-AN{1,2} PAD` | 4 | bool | Phantom power, −11 dB pad |
| `Line-IN{3,4} Sens.` | 2 | enum | `-10dBV` / `+4dBu` reference level |
| `Sample Clock Source` | 1 | enum | `AutoSync` / `Internal` |
| `IEC958 Switch`, `IEC958 Pro Mask`, `IEC958 Emphasis` | 3 | bool | Optical out = S/PDIF (off = ADAT), S/PDIF professional format, emphasis |

Volume is **linear**: `0` = −∞, `32768` = 0 dB, `65536` = +6 dB, so `dB = 20·log10(raw/32768)`.

Inputs: `AN1 AN2` (XLR mic/line), `IN3 IN4` (Hi-Z instrument/line), `AS1 AS2` (optical S/PDIF or
ADAT 1/2), `ADAT3–8`. Outputs: `AN1 AN2` (XLR, the speakers), `PH3 PH4` (both headphone jacks),
`AS1 AS2`, `ADAT3–8`. Playback channels carry the output names.

### Constraints that shape the design

1. **Write-only.** The driver caches the last value it wrote and never reads the device. A write
   equal to the cached value is skipped.
2. **The front panel is invisible.** IN/OUT + the knob change gain and output volume inside the
   device; the computer is never told. So output volume is *shared* between Audius and the knob.
3. **No hardware meters.** Levels must be measured from the audio streams through PipeWire. In the
   default *Analog Stereo* profile only capture 1/2 (Mic 1/2) and playback 1/2 exist. The DSP's
   monitor mix can't be measured at all.
4. **Today's state** (2026-10-06): every active send is `65536` (+6 dB, alsamixer's "100%"), and every
   `Main-Out` reads `1`. That `1` is not a level: it's a kernel bug (see `docs/KERNEL-BUG.md`). The
   main outs were never written, the boot-time restore skips them for the same reason, and the
   output volumes live entirely on the device (knob + its own memory). Audius treats them as
   *unknown* until it sets them.
5. **Kernel bug:** the quirk caches `index | value << 9` with a 10-bit index. Odd values written to a
   crosspoint redirect later writes to `index + 512`. Audius only writes even values and locks any
   crosspoint that already reads odd.

## 2. Safety rules (non-negotiable)

- Audius **never writes on startup** and never "syncs" by itself. It reads the kernel cache.
- Output volume changes are **ramped**. If Audius hasn't set that output in the last 45 s, or the
  window was away (the knob may have moved), the first change **fades in from −60 dB over 0.7 s**
  instead of jumping. Nothing gets louder in one step.
- Each output has a **user-defined volume ceiling** (default 0 dB).
- Turning speakers on while their volume is unknown or near silence starts them at **−40 dB**.
- Only **even** raw values are ever written to volume controls (kernel bug workaround).
- Turning an output off/on is done with its **sends**, not its volume, so it never fights the knob.
- **48V asks first** (ribbon mics, pops). Undo and scenes never touch 48V or output volume.
- "Resend everything" exists for a power-cycled device, skips 48V, and only includes volumes on request.

## 3. Architecture

```
┌──────────── native window (GTK 4 + libadwaita, Python) ────────────┐
│ transparent header bar: native page switcher + window controls    │
│ ┌──────────── WebKitGTK 6 view: audius://app/index.html ─────────┐ │
│ │ HTML/CSS/JS interface (no build step, ES modules)              │ │
│ └───────────────▲──────────────────────────────┬─────────────────┘ │
│   postMessage(reply)      │                    │  evaluate_javascript│
│ ┌─────────────────────────┴────────────────────▼─────────────────┐ │
│ │ bridge (app.py)  →  mixer.py (pairs, pan, on/off, volume        │ │
│ │ takeover, scenes, undo)  →  babyface.py (control map, dB math,  │ │
│ │ writer thread with ramps)  →  alsa.py (ctypes libasound,        │ │
│ │ events)        meters.py (GStreamer `level` on PipeWire)        │ │
│ └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

- `alsa.py`: ctypes over `libasound.so.2`: enumerate/read/write controls, subscribe to control
  events so alsamixer changes show up live. Separate handles for the writer thread and the UI thread.
- `babyface.py`: channel tables, control names, raw⇄dB, gain encodings; `Babyface` (real card, found
  by USB id) and `DemoDevice` (in-memory, for `--demo` and tests). A writer thread coalesces writes
  per control and runs dB-linear ramps, so dragging never blocks the UI on USB transfers.
- `mixer.py`: the model the UI talks to. Stereo pairs with a balance-law pan (lossless decode of any
  L/R pair; a mono mic at equal L/R is "centred" at its level), send mute, output on/off memory,
  "Listen on", volume takeover and ceilings, link/unlink, scenes, gesture-grouped undo/redo.
- `meters.py`: `pipewiresrc ! level` pipelines for the Babyface source and the sink monitor. They run only
  while the window is visible; GNOME's microphone indicator is expected while they run.
- `config.py`: `~/.config/audius/config.json` (names, links, memories, scenes, prefs, limits).
  Atomic writes, debounced. The device state itself lives in ALSA (`alsa-state` persists it).

## 4. Experience

Navigation: **Overview · Mixer · Routing · Device** (native segmented control in the title bar).

**Overview** (daily use)
- *Listen on: Headphones · Speakers · Both*, the one thing the hardware makes hard.
- *Mic 1*: the signature gain dial with the live level wrapped around it, an "ideal peaks" zone
  (RME's advice: peaks around −3 dBFS), latched clip warning, 48V (asks first) and PAD.
- *Headphones* and *Speakers* cards: volume (knob-aware), and "what you hear": Computer, Mic 1… with
  per-source contribution meters. More sources can be added from the card.
- *Other inputs* (Mic 2, Instrument 3/4) tucked behind a disclosure; optical only when enabled.

**Mixer**: TotalMix's model made explicit: pick the output you are mixing *for*, then every source
gets a fader, pan, mute and meter. The output's volume strip sits at the end.

**Routing**: the full matrix as a grid. Click to connect at 0 dB, scroll to trim, double-click to type.

**Device**: clock source, optical format, S/PDIF options, volume ceilings, meters, the knob guide
("press OUT to switch the knob between speakers, phones and optical"), resend, about.

**Scenes**: save the current mix, recall it with every fader gliding to its place (undoable).
Scenes hold sends, links and on/off states, never volume or 48V.

## 5. Design system (Apple HIG, adapted)

- Thesis: a calm surface for one beloved piece of hardware. Its knob is the heartbeat.
- Vernacular from the object: machined aluminium (the encoder), LED bar meters (green, amber, red),
  the orange P48 LED. **One colour, one meaning**: system accent = values you set; green→amber→red =
  signal level only; orange = phantom power only; red = clipping only.
- Follow the system light/dark setting (no in-app appearance toggle). Accent = GNOME accent colour.
- Type: system UI font (Adwaita Sans, Inter-based, variable `opsz`), tabular numerals for every dB.
  Scale: 28/34 display, 17/22 title, 14/19 headline, 13/18 body, 11/14 caption (floor).
- Contrast ≥ 4.5:1 for text; focus rings on everything; full keyboard control; ARIA roles.
- Motion: meters at display refresh (attack instant, release ~24 dB/s, peak hold 1.2 s); external
  value changes glide on a critically damped spring; scene recall is the one orchestrated moment.
  Reduced motion is respected.
- Native window behaviour: real header bar, window controls and resizing; transparent so the
  design runs edge to edge.

## 6. Verification

- Unit tests: dB maths, gain encodings, pair encode/decode round trips, mute/on-off memory,
  takeover decisions, undo grouping, scenes, demo device.
- `--demo` renders the full UI without hardware. `--screenshot` captures the window for review.
- On the real card: a read-only session must leave every control unchanged (diffed before/after).
  Write paths are tested only on silent ADAT crosspoints and restored exactly.

## 7. Packaging

Private repo `audius`. `install.sh` installs for the current user (no sudo): the package under
`~/.local/share/audius`, a launcher in `~/.local/bin`, desktop entry, icon, metainfo.
`build-aux/audius.spec` builds an RPM; CI checks syntax, runs tests and builds the RPM artifact.

## 8. Later

- Separate *Speakers* and *Headphones* sound outputs for apps (Pro Audio profile + loopback nodes),
  which also unlocks meters for all 12 inputs. Opt-in only, since it changes the desktop's audio setup.
- A compact quick panel (GNOME Shell extension) for Listen on + volume.
- Talkback/DIM shortcuts mirroring the device keys.
