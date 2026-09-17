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
| `measure_page.py` | The runtime gate: loads the page headlessly in the installed Chrome, teleports to six features, reports draw calls, triangles and build time, and screenshots each stop. `low|high [dir] [course]`. |
| `page/speed.js` | Speed you can feel: the lens widens and the camera drops with speed, the frame edges streak, and the Pump Lab's trackside sound plays on this physics. |
| `layout_fit_rampage.json` | The fitted layout of the Rampage line (the loop's lives in `layout_fit.json`). |

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
node check_geom.js --course rampage         # every script takes --course; fit_layout / apply_fit / loop_lap too
```

## Rampage

`?course=rampage` (or the COURSE control) is a second course in the same page: a freeride line down a Utah ridge,
built to the scale of the real thing on features the gates can check. A **40% roll-in**, an exposed spine, a 20 ft
drop, a **36 ft canyon gap** that steps down 5.5 m onto the far wall (come up short and you land nine metres down in
the canyon), a 30 ft cliff drop onto a 38 deg face, a 40 ft step-down, a 25 ft flat drop, then the shuttle road back
up. 1,396 m, 86 m of relief on the descent. The V10 rides it on its lab setup with a 34 mph cap and a full-face lid.

**Freeride drops are built differently from trail drops**, and `SEG.drop` now knows the difference: above 3 m the
landing is a short knuckle, a straight face at the landing angle carrying most of the height, and a round-out at the
bottom, so an overshoot still lands on the face at the face's angle. What kills is the flat, and the flat is a long way
down. Jumps may carry a run-in speed (`vMax`, m/s): the rider brakes to it before the lip the way a rider sets up a
drop, with a 1.8 m/s^2 budget because on a steep run-in gravity fights the brakes.

**The desert** is the same world generator with a biome switch that comes with the course: mesa relief that stacks into
sandstone benches (`hillsDesert`), red dirt and desert varnish for colours, juniper and pinyon (the conifers, small and
tinted olive), sage, dry grass and a great deal of red rock, a warm sky and clearer air, no moss (`uMoss` on the ground
material), no leaves, no mist. `PNW.instanced` takes a tint; `PNW.sky` takes colours.

**Tricks.** `TRICK` is a global the page writes every frame and the lab physics reads: `F` held through the lip throws a
backflip (`chassis.w` gets 5.4 rad/s at takeoff, the bar-authority controller stands down, holding the key tucks to
1.3x and letting go opens up to 0.8x, so timing the release is the trick), `N` takes both hands off the bars and `G`
takes the right hand back to the saddle, for as long as they are held. The rig draws all three. There are touch
buttons for a phone. A run is judged the way a freeride run is: 120 a backflip rotation, 60 a no-hander, 80 a seat grab,
x1.3 for a combination, 25 a second of air, x1.25 for a clean landing (inside 10 deg, not sketchy), x0.6 sketchy,
nothing for a crash.

**The landing verdict** applies to everyone, labs included. On the first contact after air the physics wraps the pitch
into [-pi, pi], takes the face under the wheel that touched (the same 24 cm baseline the drive forces use, not the
segment's smoothed grade), and measures the attitude against it and the speed into the ground along its normal. Inside
the tolerance the suspension and the legs take it; past 23 deg or 8.0 m/s (pro; 5.8 average) it is sketchy, the speed
scrubs 18% and the bike wobbles; past 43 deg, or 29 deg nose-first, or 9.5 m/s (7.2 average), or with the hands off
the bars, it is a crash: the bike stops, goes over on its side, and the page respawns the rider at the top of the zone
two seconds later. Coming down on the bike rather than the wheels (inverted within a frame's height of the ground) is
a crash too. A hop over a root (under a quarter second of air) is never a landing.

**In the air the rider steers the bike to the face it is about to land on.** The physics marches the ballistic path
forward until it meets the ground while descending and takes the slope there as the pitch target: a flat landing
reads -6 deg nose-up, a 38 deg face reads -38. Only a descending hit counts, so grazing a tabletop's deck near the
apex is not the landing and a hop over a root never registers. This is the difference between landing on the wheels
and landing on the front wheel, and it is why the 30 ft cliff lands 3 deg off its face.

**Speed you can feel.** The lens opens from 46 to 70 deg with speed and a little more in the air, the camera shakes with
fork velocity through the rough and goes still in the air, radial streaks build at the frame edges past 20 mph, and the
Pump Lab's trackside recording plays underneath (SOUND button): tyre roar rising with speed and brightening with the
suspension's work, freehub when the rider stops pedalling, wind taking over in the air, a hit on every landing and
bottom-out, scaled by how hard. The clips are shared with the Pump Lab at build time.

### Measured (Rampage)

| | low | high |
|---|---|---|
| world build | 135 ms | 315 ms |
| draw calls | 14–24 | 62–131 |
| triangles | 0.48–0.55 M | 2.9–3.8 M |

Both gates pass for both riders: pro lap 304 s, average 305 s, every landing within 4 deg of its face, no crashes.

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
7. **The verdict used the segment's grade, not the face.** `gradeS` is a smoothed base grade; a 20 ft drop onto a 40 deg
   face read as 10 m/s into the ground at 5 deg of mismatch. The verdict now takes the slope under the wheel that
   touched.
8. **The landing predictor grazed the deck.** The first ballistic march called any ground contact the landing, so over
   a tabletop it read the deck (flat) and pitched the bike flat onto a 25 deg ramp; on a rock garden every hop pitched
   the bike somewhere. Only a descending hit counts now.
9. **The harness never applied its speed cap.** `vcap` in the lab is a slider handler, not part of `applyTuning`, so
   the gate rode Rampage at 26 mph however DEF was set. It sets `vCap` explicitly now.
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
