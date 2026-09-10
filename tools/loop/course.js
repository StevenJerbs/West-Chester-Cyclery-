/* Cascade Loop — the course definition, shared by the physics, the runtime world and the Blender build.
   Dual module: `require()` it in Node, or drop it in a <script> tag (it attaches everything to window).

   This is the single source of truth for the trail. It extends the Suspension Lab's SEG/COURSES DSL
   (suspension-lab.html:347-544) with the segment types a level-sized loop needs, and fixes two defects in the
   original:

     1. The berm bank was built unconditionally on the +l side. Verified numerically: +l is the OUTSIDE of a turn
        only when `turn` is negative, so every right-hand berm in the existing courses is banked on the INSIDE.
        Here the wall side is -sign(turn), which is the outside in every case.
     2. The bank cross-section was a linear wedge (h += tan(bank)*l) with a crease at the centreline and no top.
        Here it is a real berm: flat tread, a smoothstep wall rolling over at the crest, then the back falling
        away at the angle of repose.

   Also new: curvature ramps in and out over a clothoid instead of stepping (corner-lab.html:293-299 does this
   for its two corners; over 21 berms it matters), and every surface query takes an optional lateral offset `l`
   so the rider can pick a line up the berm or through the rock garden. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else Object.assign(root, api);
})(typeof self !== 'undefined' ? self : this, function () {
'use strict';

const D2R = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = t => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
function hash(n){ const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }

/* =============== the trail's cross-section =============== */
/* Every segment shares one cross-section function so the ribbon, the terrain bench, the physics and the Blender
   build cannot disagree. `l` is metres from the centreline, +l is the path's left-hand normal (-sin th, cos th). */
const REPOSE = 35 * D2R;                                          // loose dirt holds about this
function bermHeight(turnDeg){ return Math.max(0.55, 1.30 * Math.abs(turnDeg) / 90); }   // >90 deg turns need >=1.30 m
function bermProfile(l, bank, Hb, side){
  const x = l * side;                                             // x > 0 climbs the wall
  const crown = -0.035 * l * l;                                   // the trail is crowned everywhere
  if (x <= 0.45) return crown;
  const l1 = 0.45 + Hb / Math.tan(bank);                          // where the wall reaches the crest
  if (x < l1) return crown + Hb * Math.pow(smooth((x - 0.45) / (l1 - 0.45)), 1.6);
  return crown + Hb - Math.tan(REPOSE) * (x - l1);                // over the top, down the back
}
function plainProfile(l){
  const a = Math.abs(l);
  let h = -0.035 * l * l;                                         // crown
  if (a > 0.18 && a < 0.42) h -= 0.022;                           // the two tyre grooves
  if (a > 0.85) h -= 0.13 * (a - 0.85);                           // singletrack: the tread is gone by 0.85 m and the shoulder falls to the litter
  return h;
}

/* =============== segment constructors =============== */
/* Each returns { len, grade, type, h(t), ... }. `h(t)` is the feature height on top of base + grade*t.
   `cross(t, l)` is the lateral profile, defaulting to the plain crowned trail.
   Jump-family segments MUST set `lipAt` and `jump{}` or the rider's preload/pop controller never fires. */
const SEG = {
  flat: (len, grade) => ({ len, grade, type: 'dirt', h: () => 0 }),
  roots: (len, grade, A) => ({ len, grade, type: 'dirt',
    h: t => A * Math.max(0, Math.sin(t * 4.1)) * (0.5 + 0.5 * Math.sin(t * 1.3 + 1)) }),
  rollers: (n, lam, A, grade) => ({ len: n * lam, grade, type: 'dirt',
    h: t => A * (1 - Math.cos(2 * Math.PI * t / lam)) / 2 }),

  /* Large rollers. A pure sinusoid goes vague past 8 m; real big rollers have a flatter crest and a tighter
     transition, which is what the pump actually keys on. `p` shapes that (1 = sinusoid, 2 = flat-topped). */
  bigroller: (list, grade) => {                                   // list = [[lam, A], ...] — never uniform
    let len = 0; const at = [];
    for (const [lam, A] of list){ at.push({ s: len, lam, A }); len += lam; }
    return { len, grade, type: 'dirt', rollers: at,
      h: t => { let acc = 0;
        for (const r of at){ const u = t - r.s; if (u < 0 || u > r.lam) continue;
          const c = (1 - Math.cos(2 * Math.PI * u / r.lam)) / 2;
          acc += r.A * Math.pow(c, 0.78); }                        // <1 flattens the crest, steepens the trough
        return acc; } };
  },

  washboard: (n, lam, A, grade) => ({ len: n * lam, grade, type: 'dirt',
    h: t => A * Math.pow(Math.max(0, Math.sin(Math.PI * t / lam)), 1.4) }),

  /* Rock garden with a rideable channel: the cells shrink toward the centreline so there is an A-line and the
     shoulders stay chunky. `chan` 0 = uniform, 1 = a clean line down the middle. */
  rockgarden: (len, grade, hmax, chan) => ({ len, grade, type: 'rock', noPedal: [0, 99], chan: chan,
    h: t => {
      const cw = 0.45, cell = Math.floor(t / cw), f = t / cw - cell;
      const a = 0.02 + hash(cell) * hmax, b = 0.02 + hash(cell + 1) * hmax;
      const w = Math.pow(Math.sin(Math.PI * clamp(t / len, 0, 1)), 0.3);
      return (a + (b - a) * smooth((f - 0.82) / 0.18)) * w;
    },
    cross: (t, l) => {
      const a = Math.abs(l), c = 1 - (chan || 0) * (1 - smooth((a - 0.25) / 0.7));
      const cell = Math.floor(t / 0.45);
      return plainProfile(l) + (c - 1) * (0.02 + hash(cell) * hmax) * 0.8;   // the channel is cut into the rock
    } }),

  rocks: (len, grade, hmax) => SEG.rockgarden(len, grade, hmax, 0),
  gout: (len, D, grade) => ({ len, grade, type: 'dirt', h: t => -D * (1 - Math.pow(Math.abs(2 * t / len - 1), 1.5)) }),

  /* Park tabletop: radiused transition -> straight face -> deck -> knuckle -> landing ramp -> round-out.
     hEnd lifts (step-up) or drops (step-down) the trail after the landing. Proven on the Tortuga course. */
  table: (H, lipDeg, R, deck, landDeg, grade, hEnd = 0) => {
    const th = lipDeg * D2R, ya = R * (1 - Math.cos(th)), xa = R * Math.sin(th);
    const face = Math.max(0, H - ya) / Math.tan(th), lipL = xa + face;
    const drop = H - hEnd, landL = drop / Math.tan(landDeg * D2R) + 3.8, run = 1.5;
    return { len: lipL + deck + landL + run, grade, type: 'built', noPedal: [0, 99], lipAt: lipL, hEnd,
      jump: { H, deck, lipDeg, landDeg, kind: 'table' },
      h: t => {
        if (t < xa) return R - Math.sqrt(Math.max(0, R * R - t * t));
        if (t < lipL) return ya + (t - xa) * Math.tan(th);
        if (t < lipL + deck) return H;
        if (t < lipL + deck + landL){ const u = (t - lipL - deck) / landL; return H - drop * (u * u * (3 - 2 * u)); }
        return hEnd; } };
  },

  /* Rock drop: a short takeoff ledge ABOVE the landing, which falls away at landDeg. No deck — you are in the
     air the moment the ledge ends — so it needs far less run than a step-down of the same height. */
  drop: (H, lipLen, ledge, landDeg, runout, grade) => {
    const lipL = lipLen + ledge, landL = H / Math.tan(landDeg * D2R) + 1.4;
    return { len: lipL + landL + runout, grade, type: 'rock', noPedal: [0, 99], lipAt: lipL, hEnd: -H,
      jump: { H, deck: 0, lipDeg: 0, landDeg, kind: 'drop' },
      h: t => {                                                    // trail level along the ledge, then H lower
        if (t < lipL) return 0;
        if (t < lipL + landL){ const u = (t - lipL) / landL; return -H * (u * u * (3 - 2 * u)); }
        return -H; } };
  },

  /* Road gap: a table whose "deck" is the road surface, dropped `gapDrop` below the lip. Coming up short lands
     you on the road rather than in a void, which is both how these are actually built and what lets the sim
     fail it survivably. Emits road{} for the crossing road mesh and culvert. */
  /* A road gap is a step-down: the lip is on the upper bank, the road cuts below, and the landing is a ramp on
     the far bank that starts near lip height and falls away, leaving the trail `hEnd` lower than it arrived.
     That drop is what buys the carry to clear the road. Coming up short lands on the road, which is
     survivable and slow — exactly the failure the sim should be able to reproduce. */
  roadgap: (H, lipDeg, R, roadW, roadDrop, landDeg, grade) => {
    const th = lipDeg * D2R, ya = R * (1 - Math.cos(th)), xa = R * Math.sin(th);
    const face = Math.max(0, H - ya) / Math.tan(th), lipL = xa + face;
    const shoulder = 1.0, roadY = -roadDrop;                       // road cut below trail level
    const knuckle = H - 0.35, hEnd = -(H - 0.35) * 0.0 - 0.95;     // far bank top, and where the trail resumes
    const landL = (knuckle - hEnd) / Math.tan(landDeg * D2R) + 3.8, run = 2.0;
    const gapL = roadW + 2 * shoulder;
    return { len: lipL + gapL + landL + run, grade, type: 'built', noPedal: [0, 99], lipAt: lipL, hEnd,
      jump: { H, deck: gapL, lipDeg, landDeg, kind: 'roadgap' },
      road: { w: roadW, at: lipL + shoulder + roadW / 2, y: roadY },
      h: t => {
        if (t < xa) return R - Math.sqrt(Math.max(0, R * R - t * t));
        if (t < lipL) return ya + (t - xa) * Math.tan(th);
        if (t < lipL + shoulder){ const u = (t - lipL) / shoulder; return lerp(H, roadY, smooth(u)); }
        if (t < lipL + shoulder + roadW) return roadY;             // the road bench
        if (t < lipL + gapL){ const u = (t - lipL - shoulder - roadW) / shoulder; return lerp(roadY, knuckle, smooth(u)); }
        if (t < lipL + gapL + landL){ const u = (t - lipL - gapL) / landL; return lerp(knuckle, hEnd, u * u * (3 - 2 * u)); }
        return hEnd; } };
  },

  huck: (H, up, ledge, out, grade) => ({ len: up + ledge + out, grade, type: 'built', noPedal: [0, 99],
    lipAt: up + ledge, jump: { H, deck: 0, lipDeg: 0, landDeg: 12, kind: 'huck' },
    h: t => t < up ? H * (1 - Math.cos(Math.PI * t / up)) / 2 : t < up + ledge ? H : 0 }),

  /* Creek ford: a dip with a flat wet bottom. `pool` tells the world builder where the water plane goes and the
     physics where the extra rolling drag is. */
  creek: (len, wetLen, depth, grade) => {
    const w0 = (len - wetLen) / 2, w1 = w0 + wetLen;
    return { len, grade, type: 'water', noPedal: [0, 99], pool: { s0: w0, s1: w1, depth },
      wet: t => t > w0 && t < w1,
      h: t => {
        if (t < w0) return -depth * smooth(t / w0);
        if (t < w1) return -depth;
        return -depth * (1 - smooth((t - w1) / (len - w1))); } };
  },

  bridge: (len, grade, w) => ({ len, grade, type: 'built', deck: { w },
    h: t => 0.06 * Math.sin(Math.PI * clamp(t / len, 0, 1)) + (Math.floor(t / 0.30) % 2 ? 0.012 : 0) }),

  slab: (len, grade) => ({ len, grade, type: 'rock', noPedal: [0, 99], h: t => 0.015 * Math.sin(t * 1.7) }),
  rootweb: (len, grade, A) => ({ len, grade, type: 'dirt',
    h: t => A * (0.55 * Math.max(0, Math.sin(t * 5.3)) + 0.30 * Math.max(0, Math.sin(t * 8.7 + 1.2)) + 0.35 * Math.max(0, Math.sin(t * 2.9 + 2.1))) }),
  chute: (len, grade) => ({ len, grade, type: 'dirt', noPedal: [0, 99],
    h: t => 0.05 * Math.pow(Math.max(0, Math.sin(Math.PI * t / 0.8)), 1.4) }),

  /* A real berm. The turn is realised over a trapezoidal curvature profile (clothoid in, constant, clothoid out)
     rather than a step, and the bank is a shaped wall on the OUTSIDE of the turn. */
  berm: (turnDeg, R, bankDeg, grade, opt) => {
    opt = opt || {};
    const arc = R * Math.abs(turnDeg) * D2R, cloth = opt.cloth !== undefined ? opt.cloth : 6.0;
    const len = arc + cloth;                                       // the ramps add roughly one cloth of length
    const bank = bankDeg * D2R, Hb = bankDeg > 0 ? (opt.Hb || bermHeight(turnDeg)) : 0;
    const side = -Math.sign(turnDeg);                              // the outside of the turn, in +l terms
    const ramp = t => clamp(Math.min(t, len - t) / cloth, 0, 1);   // 0 at each end, 1 through the middle
    return { len, grade, type: 'dirt', turn: turnDeg, cloth,
      corner: { R, bank, cloth, side, Hb },
      noPedal: [0, 99],
      kappaShape: t => ramp(t),                                    // buildPath integrates this, normalised
      bankAt: t => bank * ramp(t),
      h: t => bankDeg > 0 ? 0 : 0.02 * Math.max(0, Math.sin(t * 6.3)),   // flat corners carry braking ripples
      cross: (t, l) => Hb > 0 ? bermProfile(l, bank, Hb * ramp(t), side) : plainProfile(l) };
  },

  /* An unbanked switchback for the fire road: wide, flat, pedalled. */
  switchback: (turnDeg, R, grade) => {
    const arc = R * Math.abs(turnDeg) * D2R, cloth = 4.0, len = arc + cloth;
    return { len, grade, type: 'built', turn: turnDeg, cloth, corner: { R, bank: 0, cloth, side: -Math.sign(turnDeg), Hb: 0 },
      kappaShape: t => clamp(Math.min(t, len - t) / cloth, 0, 1),
      bankAt: () => 0, h: () => 0 };
  }
};

/* =============== the course =============== */
/* 12 zones. Every feature the brief asked for: large rollers (Cedar Speedway), jumps (The Gallery), rock drops
   (Slate Quarry, The Washout), a road gap (Logging Road), rock gardens (The Washout, Boulder Field) and 21 berms
   spread through all of it. Dimensions follow real bike-park practice: rollers at ~10 m of length per metre of
   height, berms at R >= 6 m with the wall reaching 26-34 degrees at mid-height, tables with radiused lips. */
const Z = (name, seg, extra) => Object.assign(seg, { name }, extra || {});
const COURSES = {};
COURSES.loop = [
  /* 1 — TRAILHEAD */
  Z('TRAILHEAD', SEG.flat(10, 0.0), { turn: 0, zone: 'TRAILHEAD' }),
  Z('ROLL-IN', SEG.flat(14, -0.046), { turn: 22, zone: 'TRAILHEAD' }),

  /* 2 — CEDAR SPEEDWAY: the large rollers */
  Z('CEDAR ROLLERS 1', SEG.bigroller([[10.5, 0.52], [11.0, 0.46], [10.0, 0.58]], -0.070), { turn: -6, zone: 'CEDAR SPEEDWAY' }),
  Z('SPEEDWAY BERM L', SEG.berm(-70, 9, 28, -0.078), { zone: 'CEDAR SPEEDWAY' }),
  Z('CEDAR ROLLERS 2', SEG.bigroller([[10.5, 0.50], [10.0, 0.56], [11.0, 0.44], [10.5, 0.52]], -0.062), { turn: 8, zone: 'CEDAR SPEEDWAY' }),
  Z('SPEEDWAY BERM R', SEG.berm(36, 8, 24, -0.078), { zone: 'CEDAR SPEEDWAY' }),

  /* 3 — THE WASHOUT: rock garden 1 and a small ledge drop */
  Z('WASHOUT ENTRY', SEG.flat(10, -0.139), { turn: 12, zone: 'THE WASHOUT' }),
  Z('ROCK GARDEN UPPER', SEG.rockgarden(34, -0.11, 0.24, 0.6), { turn: 18, zone: 'THE WASHOUT' }),
  Z('LEDGE DROP 0.9', SEG.drop(0.9, 1.2, 0.5, 42, 4.0, -0.124), { zone: 'THE WASHOUT' }),
  Z('CATCH BERM L', SEG.berm(-55, 7.5, 30, -0.093), { zone: 'THE WASHOUT' }),

  /* 4 — SLATE QUARRY: the big rock drop */
  Z('QUARRY SLAB', SEG.slab(14, -0.20), { turn: 30, zone: 'SLATE QUARRY' }),
  Z('QUARRY DROP 1.9', SEG.drop(1.9, 1.6, 0.8, 34, 6.5, -0.139), { zone: 'SLATE QUARRY' }),
  Z('LOWER SLAB', SEG.slab(9, -0.16), { turn: 25, zone: 'SLATE QUARRY' }),
  Z('QUARRY BERM L', SEG.berm(-72, 8, 32, -0.093), { zone: 'SLATE QUARRY' }),

  /* 5 — THE GALLERY: the jump line */
  Z('GALLERY RUN-IN', SEG.flat(16, -0.124), { turn: 20, zone: 'THE GALLERY' }),
  Z('TABLE 14 FT', SEG.table(0.95, 24, 3.7, 3.6, 25, -0.123), { zone: 'THE GALLERY' }),
  Z('GALLERY BERM L', SEG.berm(-82, 8.5, 28, -0.113), { zone: 'THE GALLERY' }),
  Z('TABLE 18 FT', SEG.table(1.10, 26, 4.0, 4.4, 26, -0.123), { zone: 'THE GALLERY' }),
  Z('STEP-DOWN 22 FT', SEG.table(1.15, 26, 4.2, 3.2, 28, -0.05, -1.1), { zone: 'THE GALLERY' }),
  Z('GALLERY BERM R', SEG.berm(76, 8, 30, -0.113), { zone: 'THE GALLERY' }),
  Z('GALLERY LINK', SEG.flat(9, -0.12), { zone: 'THE GALLERY' }),
  Z('TABLE 26 FT', SEG.table(1.15, 23, 4.8, 4.2, 26, -0.123), { zone: 'THE GALLERY' }),
  Z('HIP RUN-IN', SEG.flat(9, -0.12), { zone: 'THE GALLERY' }),
  Z('HIP 30 FT', SEG.table(1.35, 29, 5.0, 2.7, 28, -0.123), { turn: -20, zone: 'THE GALLERY' }),
  Z('GALLERY EXIT BERM', SEG.berm(-40, 9, 26, -0.113), { zone: 'THE GALLERY' }),

  /* 6 — LOGGING ROAD GAP */
  Z('GAP RUN-IN', SEG.flat(18, -0.132), { zone: 'LOGGING ROAD' }),
  Z('ROAD GAP', SEG.roadgap(1.05, 24, 4.4, 3.4, 0.7, 30, -0.046), { zone: 'LOGGING ROAD' }),
  Z('GAP OUTRUN', SEG.flat(12, -0.093), { turn: -15, zone: 'LOGGING ROAD' }),

  /* 7 — FERN HOLLOW: the water */
  Z('HOLLOW ENTRY', SEG.rootweb(16, -0.05, 0.05), { turn: 14, zone: 'FERN HOLLOW' }),
  Z('CREEK FORD', SEG.creek(16, 7, 0.35, -0.031), { zone: 'FERN HOLLOW' }),
  Z('HOLLOW TRAVERSE', SEG.flat(14, -0.046), { turn: 10, zone: 'FERN HOLLOW' }),
  Z('CREEK BRIDGE', SEG.bridge(11, -0.01, 2.4), { zone: 'FERN HOLLOW' }),
  Z('HOLLOW BERM L', SEG.berm(-46, 10, 24, -0.062), { zone: 'FERN HOLLOW' }),

  /* 8 — BOULDER FIELD: rock garden 2 */
  Z('ROCK GARDEN LOWER', SEG.rockgarden(28, -0.09, 0.21, 0.55), { turn: 16, zone: 'BOULDER FIELD' }),
  Z('BOULDER DROP', SEG.drop(0.8, 1.4, 0.6, 32, 5.0, -0.093), { zone: 'BOULDER FIELD' }),
  Z('BOULDER EXIT', SEG.rockgarden(18, -0.07, 0.18, 0.65), { turn: 20, zone: 'BOULDER FIELD' }),
  Z('BOULDER BERM L', SEG.berm(-64, 8, 28, -0.093), { zone: 'BOULDER FIELD' }),

  /* 9 — THE ORGAN PIPES: berms and pump rollers, alternating */
  Z('PIPES BERM L 1', SEG.berm(-86, 7, 32, -0.078), { zone: 'ORGAN PIPES' }),
  Z('PIPES PUMP 1', SEG.rollers(3, 8, 0.34, -0.078), { zone: 'ORGAN PIPES' }),
  Z('PIPES BERM R 1', SEG.berm(92, 7.5, 32, -0.078), { zone: 'ORGAN PIPES' }),
  Z('PIPES PUMP 2', SEG.rollers(3, 7.5, 0.30, -0.078), { zone: 'ORGAN PIPES' }),
  Z('PIPES BERM L 2', SEG.berm(-80, 8, 30, -0.078), { zone: 'ORGAN PIPES' }),
  Z('PIPES BERM R 2', SEG.berm(84, 7, 32, -0.078), { zone: 'ORGAN PIPES' }),
  Z('PIPES PUMP 3', SEG.rollers(4, 8.5, 0.38, -0.062), { zone: 'ORGAN PIPES' }),
  Z('PIPES BERM L 3', SEG.berm(-60, 7.5, 30, -0.078), { zone: 'ORGAN PIPES' }),

  /* 10 — DEVIL'S ELBOW: the last berms and the sprint */
  Z('ELBOW BERM L', SEG.berm(-100, 9, 34, -0.078), { zone: "DEVIL'S ELBOW" }),
  Z('ELBOW STRAIGHT', SEG.flat(14, -0.078), { zone: "DEVIL'S ELBOW" }),
  Z('ELBOW BERM R', SEG.berm(96, 8, 32, -0.078), { zone: "DEVIL'S ELBOW" }),
  Z('ELBOW BERM L 2', SEG.berm(-60, 9, 28, -0.062), { zone: "DEVIL'S ELBOW" }),
  Z('SPRINT OUT', SEG.flat(16, -0.046), { turn: 36, zone: "DEVIL'S ELBOW" }),

  /* 11 — MILL GRADE: the fire road back up */
  Z('MILL GRADE 1', Object.assign(SEG.flat(158, 0.085), { type: 'built' }), { turn: 10, zone: 'MILL GRADE', noPedal: null }),
  Z('SWITCHBACK 1', SEG.switchback(-118, 11, 0.07), { zone: 'MILL GRADE' }),
  Z('MILL GRADE 2', Object.assign(SEG.flat(152, 0.085), { type: 'built' }), { turn: 8, zone: 'MILL GRADE' }),
  Z('SWITCHBACK 2', SEG.switchback(90, 11, 0.07), { zone: 'MILL GRADE' }),
  Z('MILL GRADE 3', Object.assign(SEG.flat(148, 0.085), { type: 'built' }), { turn: 6, zone: 'MILL GRADE' }),
  Z('SWITCHBACK 3', SEG.switchback(-118, 11, 0.07), { zone: 'MILL GRADE' }),
  Z('MILL GRADE 4', Object.assign(SEG.flat(142, 0.085), { type: 'built' }), { turn: 6, zone: 'MILL GRADE' }),
  Z('SWITCHBACK 4', SEG.switchback(42, 11, 0.07), { zone: 'MILL GRADE' })
];

/* The fire road's return curve: arrival bearing at the trailhead, and how far the Hermite's tangents reach.
   Fitted by tools/loop/fit_layout.js to keep the road clear of the descent it has to climb back past. */
/* Fitted by tools/loop/fit_layout.js: the connector turns and the return-curve shape that keep the fire road
   clear of the descent (min 13 m horizontally, no bank steeper than the angle of repose, total turn -360).
   The authored turns above are the design intent; this layer is the geometry solution. Re-run the fitter
   after changing any berm and paste the new block. */
const RETURN_FIT = { retIn: 5.9, retM: 0.85 };
const LAYOUT_FIT = {
    "ROLL-IN": -18,
    "CEDAR ROLLERS 1": -18,
    "CEDAR ROLLERS 2": 8,
    "WASHOUT ENTRY": 20,
    "ROCK GARDEN UPPER": 14,
    "QUARRY SLAB": 19,
    "LOWER SLAB": 3,
    "GALLERY RUN-IN": -24,
    "GALLERY LINK": 3,
    "HIP RUN-IN": 34,
    "GAP RUN-IN": -26,
    "GAP OUTRUN": 43,
    "HOLLOW ENTRY": 19,
    "HOLLOW TRAVERSE": 35,
    "ROCK GARDEN LOWER": -24,
    "BOULDER EXIT": -22,
    "PIPES PUMP 1": 21,
    "PIPES PUMP 2": 34,
    "PIPES PUMP 3": 13,
    "ELBOW STRAIGHT": 8,
    "SPRINT OUT": 29,
    "MILL GRADE 1": -7,
    "MILL GRADE 2": 40,
    "MILL GRADE 3": -17,
    "MILL GRADE 4": 9
  };

/* =============== path + elevation =============== */
/* Integrates each segment's curvature (constant, or a segment's own kappaShape normalised so the total turn is
   exactly `turn`), then closes the loop with a cubic Hermite resampled to exact arc-length spacing, which becomes
   the RETURN CLIMB segment whose grade is solved so the elevation profile closes too. */
function buildCourse(COURSE, opt){
  opt = opt || {};
  const PATH = { ds: 0.25, x: [], z: [], th: [], k: [], n: 0 };
  let x = 0, z = 0, th = 0;
  for (const g of COURSE){
    const n = Math.max(1, Math.round(g.len / PATH.ds)); g.len = n * PATH.ds;
    const turn = (g.turn || 0) * D2R;
    let kapAt;
    if (g.kappaShape){                                             // normalise the shape so its integral == turn
      let area = 0; for (let i = 0; i < n; i++) area += g.kappaShape((i + 0.5) * PATH.ds) * PATH.ds;
      const k0 = area > 1e-9 ? turn / area : 0;
      kapAt = t => k0 * g.kappaShape(t);
    } else { const kap = turn / g.len; kapAt = () => kap; }
    for (let i = 0; i < n; i++){
      const t = i * PATH.ds;
      PATH.x.push(x); PATH.z.push(z); PATH.th.push(th); PATH.k.push(kapAt(t));
      x += Math.cos(th) * PATH.ds; z += Math.sin(th) * PATH.ds; th += kapAt(t) * PATH.ds;
    }
  }
  /* the Hermite return, resampled by arc length */
  /* The road has to arrive at the trailhead on a different bearing from the one the trail departs on, or the
     two run parallel for a hundred metres and the heightfield cannot bench both. RET_IN is that arrival heading;
     the trail leaves at 0, so this makes a Y at the trailhead instead of a seam. */
  const RET_IN = (opt.retIn !== undefined ? opt.retIn : -58) * D2R;
  const p0 = [x, z], t0 = [Math.cos(th), Math.sin(th)];
  const m = (opt.retM !== undefined ? opt.retM : 0.9) * Math.hypot(x, z);
  const t1 = [Math.cos(RET_IN), Math.sin(RET_IN)];
  const H = u => { const h00 = 2*u*u*u - 3*u*u + 1, h10 = u*u*u - 2*u*u + u, h11 = u*u*u - u*u;
    return [h00 * p0[0] + h10 * m * t0[0] + h11 * m * t1[0], h00 * p0[1] + h10 * m * t0[1] + h11 * m * t1[1]]; };
  /* Resample the Hermite to exact arc length. The original picked the first fine sample past each ds, so the
     spacing jittered by up to one fine step; the heading differences inherited that jitter and became noisy
     curvature. The rider leans to curvature, the lean scales gravity through the suspension, and the noise
     shook the bike into the air on what is a perfectly smooth gravel road. Interpolate instead, and take the
     heading analytically from the curve rather than from finite differences of the samples. */
  const NF = 20000, fine = [], cum = [0];
  for (let i = 0; i <= NF; i++) fine.push(H(i / NF));
  for (let i = 1; i <= NF; i++) cum.push(cum[i-1] + Math.hypot(fine[i][0] - fine[i-1][0], fine[i][1] - fine[i-1][1]));
  const total = cum[NF], nRet = Math.max(2, Math.round(total / PATH.ds)), retLen = nRet * PATH.ds;
  const at = d => {                                                // point at arc length d, by interpolation
    let lo = 0, hi = NF;
    while (hi - lo > 1){ const m = (lo + hi) >> 1; if (cum[m] <= d) lo = m; else hi = m; }
    const f = (d - cum[lo]) / Math.max(1e-9, cum[hi] - cum[lo]);
    return [lerp(fine[lo][0], fine[hi][0], f), lerp(fine[lo][1], fine[hi][1], f)];
  };
  const pts = []; for (let i = 0; i < nRet; i++) pts.push(at(i / nRet * total));
  const eps = Math.min(0.5, total / 200);
  let prevTh = th;
  for (let i = 0; i < nRet; i++){
    const d = i / nRet * total, p1 = at(Math.max(0, d - eps)), p2 = at(Math.min(total, d + eps));
    let a = Math.atan2(p2[1] - p1[1], p2[0] - p1[0]);              // central difference: smooth by construction
    while (a - prevTh > Math.PI) a -= 2 * Math.PI; while (a - prevTh < -Math.PI) a += 2 * Math.PI;
    PATH.x.push(pts[i][0]); PATH.z.push(pts[i][1]); PATH.th.push(a); PATH.k.push((a - prevTh) / PATH.ds); prevTh = a;
  }
  /* one smoothing pass on the return's curvature: the join at each end is still a step */
  { const n0 = PATH.k.length - nRet;
    const kk = PATH.k.slice(n0);
    for (let p = 0; p < 3; p++) for (let i = 1; i < kk.length - 1; i++) kk[i] = (kk[i-1] + 2 * kk[i] + kk[i+1]) / 4;
    for (let i = 0; i < nRet; i++) PATH.k[n0 + i] = kk[i]; }
  PATH.n = PATH.x.length;
  /* The closing climb is graded fire road, not singletrack. It matters: a rooty surface bounces the rider
     airborne, `poseState` latches to 'land', and the physics stops pedalling for 0.45 s each time — which on
     a 10% grade compounds into a stall. Gravel. */
  const ret = Z('RETURN CLIMB', Object.assign(SEG.flat(retLen, 0), { type: 'built' }), { zone: 'MILL GRADE' });
  COURSE.push(ret);
  let COURSE_LEN = 0; for (const g of COURSE){ g.start = COURSE_LEN; COURSE_LEN += g.len; }
  let b = 0; for (const g of COURSE){ if (g === ret) g.grade = -b / g.len; g.base = b; b += g.grade * g.len + (g.hEnd || 0); }
  return { PATH, COURSE_LEN, ret, closeErr: b };
}

/* =============== the API the physics and the world builder consume =============== */
function makeCourse(courseId, opt){
  const COURSE = (COURSES[courseId] || COURSES.loop).map(g =>
    (courseId === 'loop' && LAYOUT_FIT[g.name] !== undefined) ? Object.assign({}, g, { turn: LAYOUT_FIT[g.name] }) : g);
  const { PATH, COURSE_LEN, ret, closeErr } = buildCourse(COURSE, opt || RETURN_FIT);

  function pathAt(sIn){
    let sp = sIn % COURSE_LEN; if (sp < 0) sp += COURSE_LEN;
    const f = sp / PATH.ds, i = Math.min(PATH.n - 1, Math.floor(f)), j = (i + 1) % PATH.n, t = f - i;
    let th1 = PATH.th[j]; const th0 = PATH.th[i];
    while (th1 - th0 > Math.PI) th1 -= 2 * Math.PI; while (th1 - th0 < -Math.PI) th1 += 2 * Math.PI;
    return { x: lerp(PATH.x[i], PATH.x[j], t), z: lerp(PATH.z[i], PATH.z[j], t),
             theta: lerp(th0, th1, t), kappa: lerp(PATH.k[i], PATH.k[j], t) };
  }
  function segAt(u){
    let p = u % COURSE_LEN; if (p < 0) p += COURSE_LEN;
    let lo = 0, hi = COURSE.length;
    while (hi - lo > 1){ const m = (lo + hi) >> 1; if (COURSE[m].start <= p) lo = m; else hi = m; }
    return [COURSE[lo], p - COURSE[lo].start];
  }
  function terrainAt(u){ const [g, t] = segAt(u); return g.base + g.grade * t + g.h(t); }
  function crossAt(u, l){ if (!l) return 0; const [g, t] = segAt(u); return (g.cross || plainProfile2)(t, l); }
  function plainProfile2(t, l){ return plainProfile(l); }
  function bankAt(u){ const [g, t] = segAt(u); return g.bankAt ? g.bankAt(t) : 0; }
  function bankSide(u){ const [g] = segAt(u); return g.corner ? g.corner.side : 0; }

  /* obstacles */
  const OBST = [];
  function addObst(segName, t, o){ const g = COURSE.find(x => x.name === segName); if (!g) return; OBST.push(Object.assign({ u: g.start + t }, o)); }
  function obstH(o, d){
    if (o.type === 'log'){ const r = o.r; return Math.abs(d) < r ? r + Math.sqrt(r * r - d * d) : 0; }
    const half = o.w / 2;
    if (o.type === 'rock'){ const e = 0.06, a = Math.abs(d); return a < half ? o.h * smooth((half - a) / e) : 0; }
    if (o.type === 'shelf'){ const x = d + half; if (x < 0 || x > o.w) return 0; return x < o.ramp ? o.h * smooth(x / o.ramp) : o.h; }
    return 0;
  }
  /* obstacles bucketed by 4 m of arc length: groundAt is called ~150k times building the ribbon, and a linear
     scan of 90 obstacles inside that is the difference between 180 ms and 20 s. */
  const OB_DS = 4; let OB_BUCKETS = null;
  function bucketObst(){
    OB_BUCKETS = new Map();
    for (const o of OBST){ const b = Math.floor(o.u / OB_DS);
      for (const k of [b - 1, b, b + 1]){ if (!OB_BUCKETS.has(k)) OB_BUCKETS.set(k, []); if (!OB_BUCKETS.get(k).includes(o)) OB_BUCKETS.get(k).push(o); } }
  }
  function groundAt(u, l){
    let h = terrainAt(u) + crossAt(u, l || 0);
    if (OBST.length){
      if (!OB_BUCKETS) bucketObst();
      const list = OB_BUCKETS.get(Math.floor(((u % COURSE_LEN) + COURSE_LEN) % COURSE_LEN / OB_DS));
      if (list) for (const o of list){ const d = u - o.u; if (d > -2 && d < 2) h += obstH(o, d) * (o.w ? clamp(1 - Math.abs(l || 0) / (o.w * 0.9 + 0.4), 0, 1) : 1); }
    }
    return h;
  }
  function baseGrade(u){ return segAt(u)[0].grade; }
  function groundType(u){ return segAt(u)[0].type; }
  const ENV_OFF = [-0.85, -0.5, 0, 0.5, 0.85];
  function groundEnv(u, r, l){
    let best = -1e9;
    for (const k of ENV_OFF){ const dx = k * r; const y = groundAt(u + dx, l) - (r - Math.sqrt(r * r - dx * dx)); if (y > best) best = y; }
    return best;
  }
  /* how far up the berm the rider is allowed to go, and how far off-line elsewhere (singletrack: 0.7 m each side) */
  function lineLimit(u){
    const [g] = segAt(u);
    if (g.corner && g.corner.Hb > 0){ const s = g.corner.side; return s > 0 ? [-0.6, 2.2] : [-2.2, 0.6]; }
    return [-0.7, 0.7];
  }
  function invalidateObst(){ OB_BUCKETS = null; }

  return { COURSE, COURSE_LEN, PATH, closeErr, retLen: ret.len, retGrade: ret.grade,
           pathAt, segAt, terrainAt, crossAt, bankAt, bankSide, groundAt, groundEnv, groundType, baseGrade,
           OBST, addObst, obstH, lineLimit, invalidateObst, plainProfile, bermProfile };
}

return { SEG, COURSES, makeCourse, buildCourse, RETURN_FIT, LAYOUT_FIT, plainProfile, bermProfile, bermHeight, D2R, clamp, lerp, smooth, hash };
});
