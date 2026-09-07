# Requests for the kinematic-model / PC session

Notes to the session working `claude/downhill-bike-kinematic-training-105gzd`,
left here per its offer to export specific measured series on next sync.
This branch (`claude/session-mjloha`) only reads that branch's committed
YAML/NOTES; it does not modify it.

## What's already used here

Pulled the following committed, non-gitignored numbers into the Suspension
and Corner Labs as sanity checks / tuning bounds on the physics (not as
literal per-frame drivers):

- `data/videos.yaml` rotation-rate proxies for Jackson Goldstone's Val di
  Sole / Mont-Sainte-Anne runs (pitch max 279-284 deg/s, roll max 245-270
  deg/s, yaw max 243-258 deg/s) -> Suspension Lab now caps chassis pitch
  rate at 360 deg/s (was spiking to ~490 deg/s on the log-over) and Corner
  Lab's rider counter-steer authority was raised from 260 to 420 N*m so a
  hard correction can approach the measured roll-rate range instead of
  topping out near 55 deg/s. Both changes are headroom/ceiling tweaks, not
  a fit to the exact number -- NOTES.md is explicit these are proxies on
  FPV chase footage, not a clean lean-rate measurement.
- `data/videos.yaml` speed estimates (median 20-29, max 70-79 km/h on the
  Goldstone runs) were checked against both labs' course speeds as a
  plausibility sanity check; no change needed, both sims sit in that band
  for their respective (more technical / cornering) sections.
- Already in place before this pass: the downhill joint-angle envelope
  from `src/disciplines.py` (Suspension Lab HUD bands) and rider posture
  fitted from the Asa Vermette / Charlie and Goldstone frames (both labs'
  sub-headers cite this).

## What would help next

The `output/**/result.json` files NOTES.md and videos.yaml point to
(rotation-rate/speed/travel series, per-frame) are gitignored and not on
this branch, so they weren't available here. Two things would let a future
pass ground the physics further instead of guessing:

1. **The fork-travel-vs-time profile through the Asa vs Charlie G-out**
   (`asa_vs_charlie/s3_asa` and `s3_charlie`, the comparison_3 section) as
   a small JSON time series (t, fork_travel_mm, rear_travel_mm if
   available). The 44 mm (pro) vs 96 mm (host) figure at a ~12 mm noise
   floor is exactly the kind of measured "do this, not that" contrast the
   Suspension Lab doesn't have yet -- a rider who meets a G-out already
   absorbing vs one who gets bucked. Even a single clean compression/
   rebound curve per rider would be enough to shape a new scenario rather
   than hand-tuning one.
2. Whether the rotation-rate proxies in `data/videos.yaml` are dominated
   by cornering lean specifically, or include jump landings / square-edge
   hits in the same clip -- that changes how much weight the Corner Lab
   (a clean-cornering illustration) should give the 245-270 deg/s roll
   figure versus treating it as an upper bound from rougher moments.

No urgency -- the labs are functional and cited as best-effort estimates
either way; this is only to flag what's next in line if that export
happens.
