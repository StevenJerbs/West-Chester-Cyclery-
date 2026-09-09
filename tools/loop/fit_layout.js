/* Lay the loop out so it never crosses itself.

   Hand-tuning turn values is chasing a chaotic system: every change moves everything downstream. Instead, hold
   the berms fixed (they are the design — their radius, bank and turn are what the trail *is*) and let the
   connecting segments' turns float. Hill-climb them to maximise the minimum self-clearance, with soft penalties
   keeping the total turn near a full circuit and the fire-road return a plausible length.

   Prints the winning turn values to paste into course.js. Deterministic (seeded). */
const C = require('./course.js');
const CL = require('./clearance.js');

/* Held fixed: the berms and switchbacks (they are the design), the start, and everything you must not ride
   round a corner on — a tabletop, a road gap, a drop, a bridge or a creek crossing is straight by construction.
   The deliberate hip keeps its authored turn. */
const SEED_FIXED = new Set(['TRAILHEAD', 'HIP 30 FT']);
const src = C.COURSES.loop;
const isStraightOnly = g => !!g.jump || g.pool || g.deck || g.road;
const free = [];
src.forEach((g, i) => { if (!g.corner && !SEED_FIXED.has(g.name) && !isStraightOnly(g)) free.push({ i, name: g.name, turn: g.turn || 0 }); });
console.log('free connectors: ' + free.length + '   fixed: berms/switchbacks, jumps, road gap, creek, bridge, start, hip');

function evaluate(turns, retIn, retM){
  /* rebuild a fresh course with these turns */
  const course = src.map((g, i) => Object.assign({}, g));
  free.forEach((f, k) => { course[f.i] = Object.assign({}, src[f.i], { turn: turns[k] }); });
  let built;
  try { built = C.buildCourse(course, { retIn, retM }); } catch (e){ return { score: -1e9 }; }
  const { PATH, COURSE_LEN } = built;
  const ret = course[course.length - 1];

  const step = 4, N = Math.floor(COURSE_LEN / step), P = [], elev = [];
  { let b = 0; const eAt = []; for (const g of course){ eAt.push({ s: g.start, base: g.base, grade: g.grade }); }
    for (let i = 0; i < PATH.n; i++){ const u = i * PATH.ds;
      let lo = 0, hi = eAt.length; while (hi - lo > 1){ const m = (lo + hi) >> 1; if (eAt[m].s <= u) lo = m; else hi = m; }
      elev.push(eAt[lo].base + eAt[lo].grade * (u - eAt[lo].s)); } }
  for (let i = 0; i < N; i++){
    const f = (i * step) / PATH.ds, a = Math.min(PATH.n - 1, Math.floor(f));
    P.push([PATH.x[a], PATH.z[a]]);
  }
  const sc = CL.scan(P, u => { const f = u / PATH.ds, a = Math.min(PATH.n - 1, Math.floor(f)); return elev[a]; }, COURSE_LEN, step);
  const viol = sc.viol, minD = sc.worst.d, minPair = [sc.worst.a, sc.worst.b];
  const turnSum = course.reduce((a, g) => a + (g.turn || 0), 0);
  /* soft constraints: a full circuit, a return of sane length and grade, and a compact-ish world */
  let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9;
  for (const p of P){ x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); z0 = Math.min(z0, p[1]); z1 = Math.max(z1, p[1]); }
  const span = Math.max(x1 - x0, z1 - z0);
  /* A connector may bend, but it may not become a corner: turn per metre is curvature, and a tight radius on a
     rock slab or a jump run-in is something the rider has to brake and slide through. Cap it at 5 deg/m (R ~ 11 m),
     and harder still on rock. */
  let curvePen = 0;
  free.forEach((f, k) => {
    const g = course[f.i], lim = (g.type === 'rock' || g.type === 'built') ? 2.6 : 5.0;
    const rate = Math.abs(turns[k]) / Math.max(4, g.len);
    if (rate > lim) curvePen += (rate - lim) * 26;
  });
  const pen = Math.abs(turnSum + 360) * 0.05
            + Math.max(0, 150 - ret.len) * 0.10 + Math.max(0, ret.len - 420) * 0.05
            + Math.max(0, Math.abs(ret.grade) - 0.095) * 400
            + Math.max(0, span - 430) * 0.05 + curvePen;
  return { score: -viol - pen, viol, minD, minPair, turnSum, retLen: ret.len, retGrade: ret.grade, span, COURSE_LEN };
}

let seed = 12345; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
let bestIn = -58, bestM = 0.9;
let best = free.map(f => f.turn), bestE = evaluate(best, bestIn, bestM);
let gBest = best.slice(), gE = bestE, gIn = bestIn, gM = bestM;
console.log('start   violation ' + bestE.viol.toFixed(1) + '  minD ' + bestE.minD.toFixed(1) + ' m   turnSum ' + bestE.turnSum.toFixed(0) +
            '   return ' + bestE.retLen.toFixed(0) + ' m @ ' + (100 * bestE.retGrade).toFixed(1) + '%   score ' + bestE.score.toFixed(2));

/* A plain hill-climb gets stuck: the layout is chaotic and one bad early acceptance strands it in a local
   minimum with the trail still crossing itself. Restart from a fresh random layout whenever progress stops. */
const RESTARTS = 14, ITERS = 4200;
let T = 26;
for (let outer = 0; outer < RESTARTS; outer++){
 if (outer){
   best = free.map(() => (rnd() * 2 - 1) * 34); bestIn = -170 + rnd() * 260; bestM = 0.85 + rnd() * 1.1;
   bestE = evaluate(best, bestIn, bestM);
 }
 for (let iter = 0; iter < ITERS; iter++){
  const cand = best.slice();
  const nMut = 1 + Math.floor(rnd() * 3);
  for (let m = 0; m < nMut; m++){
    const k = Math.floor(rnd() * cand.length);
    cand[k] = Math.max(-52, Math.min(52, cand[k] + (rnd() * 2 - 1) * T));
  }
  let cIn = bestIn, cM = bestM;
  if (rnd() < 0.45){ cIn = Math.max(-170, Math.min(90, bestIn + (rnd() * 2 - 1) * T * 2.2)); }
  if (rnd() < 0.45){ cM = Math.max(0.85, Math.min(2.0, bestM + (rnd() * 2 - 1) * T * 0.02)); }
  const e = evaluate(cand, cIn, cM);
  if (e.score > bestE.score){ best = cand; bestE = e; bestIn = cIn; bestM = cM; }
  T = 26 * Math.pow(0.02, iter / ITERS) + 1.2;
 }
 if (bestE.score > gE.score){ gBest = best.slice(); gE = bestE; gIn = bestIn; gM = bestM; }
 console.log('  restart ' + outer + '  this ' + bestE.viol.toFixed(2) + ' viol / minD ' + bestE.minD.toFixed(1) +
   '   best so far ' + gE.viol.toFixed(2) + ' viol / minD ' + gE.minD.toFixed(1) + ' m');
 if (gE.viol === 0 && gE.minD > 11 && gE.score > -2) break;
}
best = gBest; bestE = gE; bestIn = gIn; bestM = gM;

console.log('\nbest    clearance ' + bestE.minD.toFixed(1) + ' m  (worst pair s=' + bestE.minPair[0].toFixed(0) + '/' + bestE.minPair[1].toFixed(0) + ')');
console.log('        loop ' + bestE.COURSE_LEN.toFixed(0) + ' m   turnSum ' + bestE.turnSum.toFixed(0) +
            '   return ' + bestE.retLen.toFixed(0) + ' m @ ' + (100 * bestE.retGrade).toFixed(1) + '%   span ' + bestE.span.toFixed(0) + ' m');
console.log('\nturn values to apply:');
free.forEach((f, k) => { if (Math.abs(best[k] - f.turn) > 0.5) console.log("  " + f.name.padEnd(22) + String(Math.round(f.turn)).padStart(5) + '  ->  ' + String(Math.round(best[k])).padStart(5)); });
require('fs').writeFileSync(__dirname + '/layout_fit.json', JSON.stringify({ retIn: +bestIn.toFixed(1), retM: +bestM.toFixed(3), turns: free.map((f, k) => ({ name: f.name, turn: Math.round(best[k]) })) }, null, 1));
console.log('\nwritten to layout_fit.json');
