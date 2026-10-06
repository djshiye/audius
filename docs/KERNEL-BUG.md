# A bug in the Linux Babyface Pro mixer driver

Found while building Audius (2026-10-06, kernel 7.2.7, also present in `torvalds/master`).

## What's wrong

`sound/usb/mixer_quirks.c` caches each mixer control (crosspoints and main-out volumes) in one
integer:

```c
#define SND_BBFPRO_MIXER_IDX_MASK 0x3ff   /* 10-bit DSP index (main outs live at 992+) */
#define SND_BBFPRO_MIXER_VAL_SHIFT 9      /* ...but the value starts at bit 9 */

kcontrol->private_value = idx | (new_val << SND_BBFPRO_MIXER_VAL_SHIFT);
idx       = kcontrol->private_value & SND_BBFPRO_MIXER_IDX_MASK;     /* in put() */
old_value = kcontrol->private_value >> SND_BBFPRO_MIXER_VAL_SHIFT;   /* in put() and get() */
```

Bit 0 of the value and bit 9 of the index share a bit. As a result:

1. **Crosspoints (index < 512):** after a write of an *odd* value, bit 9 of the index is set, so every
   later write to that control is sent to DSP address `index + 512` instead of the crosspoint, and
   reads come back as `value | 1`. The control stays like that until the driver re-probes.
2. **Main-out volumes (index 992–1003, bit 9 already set):** writes reach the right address, but reads
   always come back as `value | 1`. A never-written main out reads `1`, and restoring `1` is skipped
   because it equals the (mis-read) cache. That's why `alsactl` stores `Main-Out … value 1`, and why
   the boot-time restore never touches the output volumes: they stay where the device's knob and
   memory have them.

alsamixer's percentage steps produce odd values, so using it on the routing controls can silently
detach them from the hardware.

## The fix (one line)

```diff
--- a/sound/usb/mixer_quirks.c
+++ b/sound/usb/mixer_quirks.c
@@
 #define SND_BBFPRO_MIXER_MAIN_OUT_CH_OFFSET 992
 #define SND_BBFPRO_MIXER_IDX_MASK 0x3ff
 #define SND_BBFPRO_MIXER_VAL_MASK 0x3ffff
-#define SND_BBFPRO_MIXER_VAL_SHIFT 9
+#define SND_BBFPRO_MIXER_VAL_SHIFT 10
 #define SND_BBFPRO_MIXER_VAL_MIN 0 // -inf
 #define SND_BBFPRO_MIXER_VAL_MAX 65536 // +6dB
```

`private_value` is an `unsigned long`; `65536 << 10` still fits comfortably. Worth sending to
`linux-sound@vger.kernel.org` (Cc the quirk's author, Thomas Ebeling).

## How Audius copes

- It only ever writes **even** values to these controls (inaudible: one step is 1/32768 of unity),
  so it never triggers the bug.
- It reads volumes back with bit 0 cleared, and treats a main out that reads `0` as **unknown**
  (never written; the device holds it), not as silent.
- A crosspoint that already reads odd is **locked**: Audius won't write it, because the write would
  land on the wrong DSP address. It shows up hatched in Routing.

## Clearing a locked crosspoint

Reconnecting the Babyface alone doesn't help: `alsa-state` saved the odd value and restores it at
every boot, which locks the control again. Make the saved crosspoint values even once:

```sh
sudo systemctl stop alsa-state          # saves the current state, then stops the daemon
sudo python3 tools/fix-alsa-state.py    # backs up /var/lib/alsa/asound.state, evens the crosspoints
sudo reboot                             # the daemon restores the corrected state at boot
```

The tool changes only the Babyface's `… Playback Volume` crosspoints. It deliberately leaves
`Main-Out` values alone: their stored `1` is what keeps the boot restore from overriding your knob.

During development (2026-10-06) one such crosspoint was locked on the author's card:
`Line-ADAT8-ADAT8` (optical input 8 → optical output 8). Nothing is connected to the optical
ports, and the crosspoint sits at −96 dB, so it is inaudible; the cleanup above clears it.
