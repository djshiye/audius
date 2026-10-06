#!/usr/bin/env python3
"""Generate the Audius app icon (a machined knob ringed by an LED level meter)."""
import math
import sys

S = 128  # canvas


def polar(cx, cy, r, deg):
    a = math.radians(deg - 90)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def sector(cx, cy, r0, r1, d0, d1):
    (ax, ay), (bx, by) = polar(cx, cy, r1, d0), polar(cx, cy, r1, d1)
    (cx2, cy2), (dx, dy) = polar(cx, cy, r0, d1), polar(cx, cy, r0, d0)
    return (f"M{ax:.2f} {ay:.2f}A{r1} {r1} 0 0 1 {bx:.2f} {by:.2f}"
            f"L{cx2:.2f} {cy2:.2f}A{r0} {r0} 0 0 0 {dx:.2f} {dy:.2f}Z")


def icon():
    cx, cy = 64, 66
    segs = []
    n, arc, start = 19, 270, -135
    lit = 13
    for i in range(n):
        per = arc / n
        d0, d1 = start + i * per + per * 0.16, start + (i + 1) * per - per * 0.16
        if i < lit:
            color = "#32d74b" if i < 11 else "#ffd60a"
            segs.append(f'<path d="{sector(cx, cy, 39, 45.5, d0, d1)}" fill="{color}"/>')
        else:
            segs.append(f'<path d="{sector(cx, cy, 39, 45.5, d0, d1)}" fill="#ffffff" fill-opacity="0.09"/>')
    ptr_x0, ptr_y0 = polar(cx, cy, 13, 38)
    ptr_x1, ptr_y1 = polar(cx, cy, 24, 38)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2b3039"/>
      <stop offset="1" stop-color="#0e1014"/>
    </linearGradient>
    <linearGradient id="rim" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.22"/>
      <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.03"/>
      <stop offset="1" stop-color="#000000" stop-opacity="0.25"/>
    </linearGradient>
    <radialGradient id="well" cx="0.5" cy="0.4" r="0.6">
      <stop offset="0" stop-color="#15181d"/>
      <stop offset="1" stop-color="#07080a"/>
    </radialGradient>
    <radialGradient id="knob" cx="0.5" cy="0.38" r="0.62">
      <stop offset="0" stop-color="#ffffff"/>
      <stop offset="0.45" stop-color="#dfe3e8"/>
      <stop offset="0.85" stop-color="#a9b0b8"/>
      <stop offset="1" stop-color="#868d96"/>
    </radialGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="0.42" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.55"/>
      <stop offset="0.58" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <pattern id="spun" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="3" height="3" fill="none"/></pattern>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
      <feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#000" flood-opacity="0.55"/>
    </filter>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.6" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect x="8" y="8" width="112" height="112" rx="26" fill="url(#tile)"/>
  <rect x="8.5" y="8.5" width="111" height="111" rx="25.5" fill="none" stroke="url(#rim)"/>
  <g filter="url(#glow)">
    {"".join(segs)}
  </g>
  <circle cx="{cx}" cy="{cy}" r="33" fill="url(#well)"/>
  <g filter="url(#shadow)">
    <circle cx="{cx}" cy="{cy}" r="28.5" fill="url(#knob)"/>
  </g>
  {"".join(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#ffffff" stroke-opacity="0.16" stroke-width="0.5"/>' for r in range(8, 28, 3))}
  <circle cx="{cx}" cy="{cy}" r="28.5" fill="url(#sheen)"/>
  <circle cx="{cx}" cy="{cy}" r="28.5" fill="none" stroke="#4b5159" stroke-width="1.2"/>
  <path d="M{ptr_x0:.2f} {ptr_y0:.2f}L{ptr_x1:.2f} {ptr_y1:.2f}" stroke="#23272d" stroke-opacity="0.8" stroke-width="3.6" stroke-linecap="round"/>
</svg>
'''


def symbolic():
    cx, cy = 8, 8.4
    parts = []
    n, arc, start = 9, 270, -135
    for i in range(n):
        per = arc / n
        d0, d1 = start + i * per + per * 0.2, start + (i + 1) * per - per * 0.2
        parts.append(f'<path d="{sector(cx, cy, 5.6, 7.4, d0, d1)}"/>')
    x1, y1 = polar(cx, cy, 3.6, 38)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <g fill="#2e3436">{"".join(parts)}
    <path d="M{cx} {cy - 4.2}a4.2 4.2 0 1 1 0 8.4a4.2 4.2 0 1 1 0-8.4zm{x1 - cx:.2f} {y1 - cy + 4.2:.2f}a0.9 0.9 0 1 0 0.01 0z" fill-rule="evenodd"/>
  </g>
</svg>
'''


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    with open(f"{out}/io.github.djshiye.Audius.svg", "w") as f:
        f.write(icon())
    with open(f"{out}/io.github.djshiye.Audius-symbolic.svg", "w") as f:
        f.write(symbolic())
