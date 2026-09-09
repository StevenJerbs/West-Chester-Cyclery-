# Cascade Loop — the course, and the gates it has to pass

A level-sized mountain-bike trail loop: **1,802 m**, a **837 m descent at −9.2% (−77 m)** through eleven zones, closed
by a **966 m fire-road climb**. Every feature the brief asked for is in it — large rollers, a jump line, rock drops,
a road gap, two rock gardens, and seventeen berms.

This directory is the **source of truth for the trail geometry**. The runtime page, the Blender build and the
physics all read `course.js`; nothing else defines the trail.

## Files

| file | what it is |
|---|---|
| `course.js` | The course DSL and the loop itself. Dual module: `require()` it in Node, or drop it in a `<script>`. |
| `clearance.js` | The one definition of "the trail conflicts with itself", shared by the fitter and the gate so they cannot disagree. |
| `fit_layout.js` | Lays the loop out so it never crosses itself. Hill-climbs the connector turns and the return-curve shape, with random restarts. Writes `layout_fit.json`. |
| `apply_fit.js` | Applies `layout_fit.json` into `course.js` and **verifies** it landed. |
| `check_geom.js` | The geometry gate: length, elevation closure, turn closure, self-clearance, and every berm's bank side. |
| `loop_lap.js` | The rideability gate. Runs one lap of the Suspension Lab's physics over this course, headlessly. |
| `build_page.js` | Assembles `../../trail-loop.html` out of the parts below plus the proven code in the labs. |
| `page/head.html` | The page chrome: header, mode and quality controls, the stage, the readout strip. |
| `page/ui.js` | The setup the physics reads, and the three quality tiers. |
| `page/world.js` | The world generator: spatial hash, two-tier terrain, chunked ribbon, structures, water, scatter, leaves, tracks. |
| `page/loop.js` | Input, the ride / cinematic / free-cam modes, the HUD, the minimap and the frame loop. |

## Workflow

```
node check_geom.js          # fast, run after every course edit
node fit_layout.js          # only after changing a berm, a zone length or a grade
node apply_fit.js           # writes the fit back into course.js, verified
node loop_lap.js pro        # the hard gate
node loop_lap.js avg
node loop_lap.js pro --json run_pro.json    # trajectory for the Blender render
node build_page.js          # -> trail-loop.html, with every inline script block syntax-checked
```

## The page

`build_page.js` never copies code by hand. It slices the PNW asset module and its baked-light materials out of
`pump-lab.html`, the V10 solver and the bike rig out of `suspension-lab.html` (between sentinel comments, not by
line number), inlines `course.js`, and adds the four files in `page/`. Re-running it picks up any change to the
labs. The result is a single ~300 KB HTML file with no external data.

The one thing the page adds to the physics is a **lateral line**. The solver is one-dimensional along `scroll`,
so rather than change it, `groundAt` and `groundEnv` are wrapped to inject the rider's offset `l`, which
`course.js` already evaluates against the same cross-section the ribbon is built from. A and D pick a line, and
`lineLimit` opens the berms up to 2.2 m of wall. No line of the gated solver changed.

Add `?q=low|med|high` to force a quality tier, and `LOOPSIM.goto(metres)` in the console to jump to a feature.

### Measured

| | low | high |
|---|---|---|
| world build | 258 ms | 616 ms |
| draw calls, in the trees | 98–107 | 329–485 |
| triangles | 630 k | 2.6 M |
| desktop frame rate | 60 fps | 60 fps |

A full lap through the page's own loop with no rider input: **368 s, no stalls**, slowest point 5.1 mph on the
fire road at 1,632 m.

**The draw-call budget is missed, and the reason is the bike.** Of 108 meshes in the low tier, **72 are the rig**
— every frame tube, spoke, limb and brake lever is its own mesh, inherited from the labs where one bike against
75 m of trail was free. The entire world is the other 36. Merging the rig's rigid sub-assemblies (each wheel is
ten meshes that never move relative to one another) would take the low tier to roughly 50 and is the next thing
to do.

Two things SSAO is standing in for on desktop have a cheap substitute on mobile: the ribbon and the corridor band
write an approximate openness into the `bake.y` channel — how far a vertex sits below what is beside it, which is
what a berm bowl, a bench cut and a rock-garden channel all are. It is the same channel the Cycles bake will
overwrite, so it costs nothing later.

`fit_layout.js` optimises the **connector** turns only. The berms, the jumps, the road gap, the creek and the bridge
hold their authored values — they are the design; the connectors are the geometry solution. The authored turns stay
readable in `COURSES.loop`; the fitted values live in the `LAYOUT_FIT` block and are applied in `makeCourse`.

## What the gates check

**Geometry** — the loop closes in position and elevation (to 0.0001 m); total turn is within 60° of a full circuit;
no two sections of trail more than 40 m apart along the trail come within 6.5 m of each other (the ribbons would
merge) or stand behind a bank steeper than 1.4 (54°, what an armoured cut bank holds); every jump carries `lipAt`
and `jump{}`; every berm is banked on the **outside** of its turn.

**Rideability** — a full lap completes for both the pro and average riders; no stalls; every jump leaves the ground
with the right air time and lands past the knuckle on its ramp, not on the deck; landing attitude within 22° of the
landing slope; bottom-outs within cap; grip usage under 1.0 (pro) / 1.15 (avg) with no sustained sliding; the fire
road never drops below 1.5 m/s.

Current state: **both gates pass.** Pro lap 348 s, average 314 s.

## Four defects found and fixed along the way

1. **Berms were banked on the wrong side.** `suspension-lab.html:1049` lifts the bank on the `+l` side
   unconditionally, and `:1014` on `side > 0`. Verified numerically that `+l` is the *outside* of a turn only when
   `turn` is negative — so every right-hand berm in the existing Ladies Only and Tortuga courses is banked on the
   **inside**. Here the wall side is `-sign(turn)`, which is the outside in every case. Worth backporting.
2. **The bank was a linear wedge** (`h += tan(bank)·l`) with a crease at the centreline and no top. Replaced with a
   real cross-section: flat tread to 0.45 m, a smoothstep wall that rolls over at the crest, then the back falling
   away at the angle of repose — and a clothoid ramp in and out instead of a step in curvature.
3. **The loop-closing Hermite was resampled badly**, and this one actually broke the physics. The original picked
   the first fine sample past each 0.25 m, so the spacing jittered and the heading differences inherited that
   jitter as noisy curvature. The rider leans to curvature, lean scales gravity through the suspension, and the
   noise shook the bike airborne on a perfectly smooth gravel road — which then latched `poseState` to `'land'`,
   cut pedalling for 0.45 s at a time, and stalled the climb. Now resampled by interpolation to exact arc length,
   with the heading taken from a central difference on the curve and one smoothing pass on the return's curvature.
4. **The trail ribbon is wound backwards.** `suspension-lab.html:1055` emits `(a, b, a+1)`, whose cross product is
   forward × left — straight *down*. The labs get away with it because their ribbon is `DoubleSide` and
   flat-shaded, but it means every trail surface in them takes its lighting from underneath. Here the first
   `FrontSide` build made whole zones vanish, which is how it surfaced. Wound `(a, a+1, b)` now. Worth backporting
   with the berm fix.

## Zones

| # | zone | m | Δh | contents |
|---|---|---|---|---|
| 1 | TRAILHEAD | 24 | −0.6 | staging deck; the fire road returns alongside |
| 2 | CEDAR SPEEDWAY | 102 | −7.0 | large rollers, λ 10–11 m, 0.44–0.58 m; two berms |
| 3 | THE WASHOUT | 65 | −8.3 | rock garden, 0.9 m ledge drop, catch berm |
| 4 | SLATE QUARRY | 52 | −9.4 | granite slabs, **1.9 m rock drop**, berm |
| 5 | THE GALLERY | 156 | −18.6 | the jump line: 5 tables and a step-down, 3 berms |
| 6 | LOGGING ROAD | 47 | −5.2 | **the road gap** — 1.3 m lip over a 4.4 m road cut |
| 7 | FERN HOLLOW | 71 | −2.9 | creek ford, bridge, pools |
| 8 | BOULDER FIELD | 71 | −6.9 | second rock garden, 0.8 m drop |
| 9 | ORGAN PIPES | 162 | −12.1 | six berms alternating with pump rollers |
| 10 | DEVIL'S ELBOW | 87 | −6.0 | three berms and the sprint out |
| 11 | MILL GRADE | 966 | +77.1 | graded fire road, four switchbacks, closes the loop |
