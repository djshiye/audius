# Audius design system

Grounded in Apple's Human Interface Guidelines (design principles of June 2026) and in the object on
the desk: the Babyface Pro FS's machined aluminium encoder, its LED bar meters, the orange P48 LED.

**Thesis.** A calm surface for one beloved piece of hardware. The daily jobs (where am I listening,
is my mic level right, what do I hear) are obvious; the full matrix is one click away.

**Signature.** The gain dial: a machined knob (spun-metal face, engraved pointer) ringed by LED
segments that show the live input level, plus a thin bracket where RME says the loudest peaks
belong (−12 to −3 dBFS). Gain you set and level you get, in one control. The app icon, the Mixer's
fader caps and the Device page's illustration use the same aluminium.

## Colour: one colour, one meaning

| Token | Meaning | Dark | Light | Contrast on card (dark / light) |
|---|---|---|---|---|
| `--accent` | values you set (sliders, gain arc, selection) | GNOME accent | GNOME accent | text uses `--accent-text`: ≈7:1 / ≈5.3:1 |
| `--level-green/amber/red` | signal level only (meters, LED ring) | #32d74b / #ffd60a / #ff453a | #28c840 / #ffc400 / #ff3b30 | not used for text |
| `--phantom` | 48V only | #ff9f0a | #ff9500 (text #a85600) | 8.6:1 / 5.3:1 |
| `--clip` | clipping only | #ff453a | #d70015 | 5.2:1 / 5.4:1 |
| `--text` / `-2` / `-3` | primary / secondary / tertiary text | #eceff4 / #a3aab5 / #7c8490 | #1d1d1f / #5c5d66 / #6e6f78 | 15.3 · 7.5 · 4.7 / 16.8 · 6.5 · 4.9 |
| `--surface` | cards | #16191e | #ffffff | |
| `--bg` | window | #0d0f12 + faint accent glow | #f2f2f5 | |

Mute is neutral (inverted "M", struck-through name), never red: red means clipping.
The appearance follows GNOME's light/dark setting; there is no in-app switch.

## Type

The system face (Adwaita Sans, an Inter derivative with a variable optical-size axis), tabular
figures for every number that changes.

| Role | Size / leading | Weight |
|---|---|---|
| Display (offline title) | 28 / 34 | 700 |
| Dial value | 30 / 34 (opsz 32) | 650 |
| Card title | 15 / 20 | 650 |
| Body | 13 / 18 | 400–600 |
| Caption, tick labels | 11 / 14 (9.5 for fader scales) | 600 |

## Layout

- Native window: a transparent header bar carries the window controls and the page switcher, so
  the interface runs edge to edge. Minimum width 560 px.
- Overview: gain card (fixed 300–360 px) + two output cards; 2 columns under 1120 px, 1 under 760.
- Cards: 20 px radius, 18–20 px padding, layered hairline + shadow instead of borders.
- Rows inside cards: label and value on one line, full-width control below.

## Controls

- **Sliders and faders** use a console taper: unity (0 dB) at 80 % of travel with a detent mark,
  +6 dB at the top, −∞ at the bottom. Clicking the track *pages* 6 dB toward the pointer (the macOS
  default), so a stray click never jumps a level. Shift = fine, Alt-click = unity, double-click =
  type a value, scroll and arrow keys adjust.
- **Meters** use IEC 60268-18 deflection (more room near the top), instant attack, 26 dB/s release,
  1.2 s peak hold, latched clip.
- **Segmented controls** for mutually exclusive choices (Listen on, Mixing for, reference level,
  clock, optical format); the selection pill slides.
- **Confirmations** only where harm is possible (turning 48V on, resending volumes).

## Motion

- External value changes (undo, scenes, alsamixer) glide on a critically damped spring (~0.3 s).
- Scene recall is the one orchestrated moment: every fader glides at once while the hardware ramps.
- Popovers scale in from their anchor; pages fade up 6 px. All of it collapses to instant under
  "reduce animations".

## Accessibility

Every control is reachable by keyboard with a visible focus ring, has an ARIA role, label and value
text ("Mic 1 gain, +26 dB"), and nothing is told by colour alone (clipping says "Clipped", 48V says
"48V", mutes strike the name through). Text scales with GNOME's text-scaling factor.
