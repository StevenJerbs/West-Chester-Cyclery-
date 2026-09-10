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
| `page/rig_merge.js` | The bike and rider as one draw call: every posed part's world matrix baked into one geometry each frame. |
| `measure_page.py` | The runtime gate: loads the page headlessly in the installed Chrome, teleports to six features, reports draw calls, triangles and build time, and screenshots each stop. |

## Workflow

```
node check_geom.js          # fast, run after every course edit
node fit_layout.js          # only after changing a berm, a zone length or a grade
node apply_fit.js           # writes the fit back into course.js, verified
node loop_lap.js pro        # the hard gate
node loop_lap.js avg
node loop_lap.js pro --json run_pro.json    # trajectory for the Blender render
node build_page.js          # -> trail-loop.html, with every inline script block syntax-checked
python measure_page.py low shots/   # draw calls, triangles, build time, screenshots; also `high`
SETUP='{"rSpring":500}' node loop_lap.js pro   # sweep a setup through the gate without editing it
```

## The page

`build_page.js` never copies code by hand. It slices the PNW asset module and its baked-light materials out of
`pump-lab.html`, the V10 solver and the bike rig out of `suspension-lab.html` (between sentinel comments, not by
line number), inlines `course.js`, and adds the four files in `page/`. Re-running it picks up any change to the
labs. The result is a single ~300 KB HTML file with no external data.

**The bike is a Starling Murmur** (2021, size L, as Pinkbike's Field Test rode it: 150 mm Ohlins fork, 140 mm on a
TTX coil, 29"), not the labs' V10. It was chosen from mtbkin's per-bike kinematics results as the full-suspension
bike the keypoint model tracks most tightly (BB-to-rear-axle spread 6.9 px, 99% of frames tracked), and it is easy
to model for the same reason it is easy to track: a steel single pivot, one rigid swingarm with the shock driven
straight off it. The lab's physics now carries a `BIKES` table and reads a global `BIKE` before it builds its
geometry and linkage table; the page sets `BIKE = 'murmur'`, the labs leave it unset and stay on the V10. The
Murmur's pivot and shock mounts were placed to give 140.8 mm at 60 mm of stroke with the leverage falling 2.44 to
2.21 (9% progressive) and 5 mm of rearward axle path. `RIG_STYLE = 'enduro'` swaps the full-face for a half shell.

**The setup is firm for a 140 mm bike, and the gate chose it.** 450 lb/in on the coil with the rebound slowed to
10 / 6 clicks, 92 psi with three tokens in the fork. Softer bottoms out in the Gallery; 500 lb/in kicked the pro
rider nose-up off the second Cedar roller into a loop-out; slower rebound packs. Sweeps run through
`SETUP='{...}' node loop_lap.js`.

**One draw call for the bike.** The rig arrives from the lab as 72 meshes. Nothing in `pose()` needs them to be
meshes — it only sets transforms — so `rig_merge.js` hides each part and, after every `pose()`, bakes its world
matrix into one shared geometry with the colour per vertex: about 2,300 vertices transformed on the CPU per frame
for 71 draw calls saved. The merged mesh is the one shadow caster on the desktop tiers.

**Singletrack.** The tread is 1.7 m wide: tyre grooves inside 0.42 m, the shoulder falling away past 0.85 m into
needle litter, and the rider's line limited to 0.7 m each side (2.2 m up a berm wall). The ribbon still reaches
3.2 m so the bench and the berm backs stay one surface; what reads as trail is the middle. Ground cover crowds
the edge: sedge tufts, fallen-leaf cards and moss hummocks are three small assets built in `world.js` in the
same `{v, t, c}` format the Blender assets use, one instanced draw call each, plus small ferns from 0.9 m and
hemlock regen. The baked material has a `ground` kind now (two octaves of detail normal, moss where the bake says
shade, a broad mottle) alongside the richer `track` kind (grain, pebbles, wet ruts), and every swaying plant
carries its own shade and a fine grain so a stand of one species is not one colour.

**Lean is a controller, not a spring.** The bike is an inverted pendulum on its contact line and the only thing
that can lean it is the steer angle, so the rider's controller in `pose()` steers *out* of the turn to start a lean
(countersteer), then holds the geometric steer that balances it. The bars visibly flick the wrong way at every
turn-in; in the air the lean holds. Below ~8 mph the speed is floored. This is visual: the physics' `corner.lean`
still sets the load through the suspension.

The one thing the page adds to the physics is a **lateral line**. The solver is one-dimensional along `scroll`,
so rather than change it, `groundAt` and `groundEnv` are wrapped to inject the rider's offset `l`, which
`course.js` already evaluates against the same cross-section the ribbon is built from. A and D pick a line, and
`lineLimit` opens the berms up to 2.2 m of wall. No line of the gated solver changed.

Add `?q=low|med|high` to force a quality tier, and `LOOPSIM.goto(metres)` in the console to jump to a feature.

### Measured

`measure_page.py`, headless Chrome 152, six stops (trailhead, upper rock garden, road gap, Organ Pipes berm,
switchback, Mill Grade):

| | low | high |
|---|---|---|
| world build | 157 ms | 331 ms |
| draw calls | 30–41 | 116–323 |
| triangles | 0.70–0.76 M | 4.2–9.8 M |
| desktop frame rate | 60 fps | 60 fps |

Before the rig merge the same stops read 97–108 (low) and 314–506 (high); the bike was 72 of the low tier's 108.
The three ground-cover species cost three draw calls. The low tier is inside the < 50 mobile budget.

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

Current state: **both gates pass** on the Murmur with the setup above. Pro lap 313 s, average 311 s; one warning
each (the average rider lands the 22 ft step-down 16° nose-down, the pro lands the road gap 16° nose-down).

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
5. **The rider looped out, and the physics helped.** Whenever the front wheel was unloaded with the rear on the
   ground the lab added a fixed nose-up torque — the push off a ledge that keeps a drop level. A shorter-travel bike
   with a stiffer coil kicks its front up off a big roller, the same push kept it going, and the chassis hit the
   0.9 rad pitch clamp and rode the rest of the lap on its rear wheel. The push now applies only while the nose is
   low and not already rotating, and past 20° the rider does the opposite: straight arms driving the bars down.
   The 500 lb/in setup that looped out passes the gate now. Fixed in the lab, so the V10 has it too.
6. **The harness booked the whole lap to the trailhead.** The step that closes the lap lands at s = 0, so the
   trailhead's record ran until lap end and inherited every bottom-out on the course. The lap-close check now runs
   before the zone bookkeeping.

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
