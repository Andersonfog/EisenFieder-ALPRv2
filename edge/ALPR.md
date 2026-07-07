# How the license-plate reader works (and how to measure it)

The plate reader is the heart of this system, so it doesn't just "run OCR on
a photo" — it works the way commercial ALPR systems (Flock, OpenALPR) do.

## The big idea: many looks, one answer

A car crossing your entrance is on camera for a few seconds — that's a dozen
or more chances to read the plate. Any *single* photo can lie (motion blur,
sun glare, a shadow across one character), but the *mistakes change from
frame to frame while the truth doesn't*. So the system:

1. **Reads the plate on every frame** while the vehicle is tracked
   (budgeted — see `alpr_reads_per_track` in config.yaml).
2. **Votes character by character** across all those reads. Each read's vote
   is weighted by how much it deserves trust: the OCR's own per-character
   confidence, how large the plate was (closer = better), and how sharp the
   crop was (a blur-free frame outvotes a smeared one).
3. **Logs one answer** when the vehicle leaves — the consensus, with a
   confidence that goes *up* when independent frames agree and *down* when
   they disagree.

Real example from testing: one frame had sun glare across the middle of the
plate and read `7123`, one frame read nothing, one clean frame read
`7ABC123`. The vote threw out the corrupted read and logged the right plate.

## Extra accuracy layers

**Off-length reads still count.** A frame that read `7ABC12` (missed the last
character) used to be thrown away because it couldn't line up with the
7-character reads. Now it's *aligned* to the consensus so the six characters
it DID see still vote. More evidence per pass, especially at long range.

**Look-alike votes are pooled.** If half the frames read `B` and half read
`8`, they aren't disagreeing — they all saw the same stamped glyph and only
differ on letter-vs-digit. Those votes are pooled (so confidence stays high),
and the plate-layout check decides which twin it is (`ABC123B` isn't a US
layout; `ABC1238` is).

**Deskew.** A plate seen at an angle (tilted mount, turning car) is rotated
level before the retry OCR — tilt is the single biggest cause of misreads.

**Enhance-and-retry.** If a read comes back doubtful, the plate crop is
deskewed, upscaled (small far-away plates), contrast-boosted (shadows/glare),
sharpened (mild blur), and exposure-fixed (night / washed-out), and each
version is OCR'd again. All the reads of that frame are then **merged
character by character** — one version may nail the left half while another
nails the right. Same pixels, better presented; never invention.

**Format repair.** OCR classically confuses look-alike characters: `O`/`0`,
`I`/`1`, `B`/`8`, `S`/`5`. If — and only if — a *low-confidence* character is
the one thing stopping the plate from matching a real US plate layout (like
California's `7ABC123` digit-letters-digits shape), it's swapped and the event
notes it was repaired. A confidently-read character is **never** altered
(unless the frames themselves split between its two twins — see pooling
above), so an unusual plate can't be "corrected" into fiction. Turn this off
with `alpr_format_correction: false`.

**It stops when it's sure.** Once several confident reads agree exactly
(`alpr_lock_after_agree`), the system stops re-reading that vehicle — the
answer can't change, so the CPU goes back to detection and tracking instead.
It also skips OCR on motion-blurred frames (`alpr_skip_blur_below`): a smeared
frame would only add noise to the vote. Both matter a lot on a Raspberry Pi.

**Best-shot photo.** The plate close-up saved with each event is the sharpest,
largest crop captured during the whole pass — not just whatever the last frame
looked like.

**Honesty rules, same as everywhere else in this project:**
- No read → the plate field is blank. Never a guess.
- Reads weaker than `alpr_min_read_conf` are treated as noise and dropped.
- A real photo never gets a fake "estimated" plate box drawn on it.

## Measuring accuracy on YOUR camera

Accuracy claims mean nothing until measured at your mounting angle and light.

1. Let the camera run, then copy some plate close-ups out of `data/events/`
   (or use any photos you have where you know the plate).
2. Put them in a folder, named after the TRUE plate:

   ```
   plates/
     7ABC123.jpg
     8XYZ456_1.jpg     <- several photos of one plate: add _1, _2, ...
     8XYZ456_2.jpg
   ```

3. Run the measuring tool:

   ```
   cd edge
   python -m tools.measure_alpr --data plates
   ```

You get the exact-match rate (the number that matters), character accuracy
(how close the misses were), and a confidence table that tells you things
like "at confidence ≥ 0.85 the system answers 90% of the time and is right
98% of the time" — use that to pick how cautious watchlist alerts should be.

## Tuning knobs (config.yaml → `detector:`)

| Setting | Default | What it does |
|---|---|---|
| `alpr_reads_per_track` | 10 | OCR budget per vehicle pass (CPU vs accuracy) |
| `alpr_min_vehicle_px` | 56 | Skip OCR while the vehicle is still tiny/far |
| `alpr_retry_below_conf` | 0.90 | Below this, retry on an enhanced crop |
| `alpr_min_read_conf` | 0.50 | Weaker reads are discarded as noise |
| `alpr_format_correction` | true | O↔0 / I↔1 repair, layout-confirmed only |
| `alpr_lock_after_agree` | 3 | Stop reading once this many confident reads agree (0 = never) |
| `alpr_skip_blur_below` | 8.0 | Skip motion-blurred frames before OCR (0 = off) |

On a Raspberry Pi, lower `alpr_reads_per_track` to ~6 if CPU runs hot; the
fusion still works with fewer reads. The early lock usually kicks in after
3-4 reads anyway, so the full budget is only spent on genuinely hard plates.

The accuracy report also prints your **top character mix-ups** (e.g.
`8->B x3`). If one pair keeps dominating on your camera, that's a clue worth
acting on — the repair maps can be extended for it.
