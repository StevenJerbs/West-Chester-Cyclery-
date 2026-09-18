/* Geometry gate for the Cascade Loop: length, elevation closure, turn closure, the solved return grade, and
   corridor self-clearance (the terrain builder needs the trail never to come near itself). Runs in ~50 ms —
   run it after every course edit, before spending time on the physics. */
const C = require('./course.js');
const CL = require('./clearance.js');
const L = C.makeCourse('loop');

const zones = [];
for (const g of L.COURSE){
  const z = g.zone || 'RETURN';
  let e = zones.find(q => q.name === z);
  if (!e){ e = { name: z, len: 0, dh: 0, segs: 0, turn: 0, feats: [] }; zones.push(e); }
  e.len += g.len; e.dh += g.grade * g.len + (g.hEnd || 0); e.segs++; e.turn += (g.turn || 0);
  if (g.jump) e.feats.push(g.jump.kind);
  if (g.corner && g.corner.Hb > 0) e.feats.push('berm');
}

const totLen = L.COURSE_LEN;
const descent = L.COURSE.filter(g => g.zone !== 'MILL GRADE' && g.name !== 'RETURN CLIMB');
const descLen = descent.reduce((a, g) => a + g.len, 0);
const descDh = descent.reduce((a, g) => a + g.grade * g.len + (g.hEnd || 0), 0);
const turnSum = L.COURSE.reduce((a, g) => a + (g.turn || 0), 0);

console.log('=== CASCADE LOOP · geometry ===');
console.log('total loop        ' + totLen.toFixed(1) + ' m   (descent ' + descLen.toFixed(0) + ' m, climb ' + (totLen - descLen).toFixed(0) + ' m)');
console.log('descent relief    ' + descDh.toFixed(1) + ' m  at ' + (100 * descDh / descLen).toFixed(1) + '% average');
console.log('return climb      ' + L.retLen.toFixed(1) + ' m at ' + (100 * L.retGrade).toFixed(2) + '%');
console.log('elevation closes  ' + Math.abs(L.closeErr).toFixed(4) + ' m  ' + (Math.abs(L.closeErr) < 0.1 ? 'OK' : 'FAIL'));
console.log('turn sum          ' + turnSum.toFixed(0) + ' deg  (want about -360, residual ' + (turnSum + 360).toFixed(0) + ')  ' + (Math.abs(turnSum + 360) < 60 ? 'OK' : 'CHECK'));

/* position closure: the Hermite guarantees it, but assert anyway */
const p0 = L.pathAt(0), pe = L.pathAt(L.COURSE_LEN - 0.001);
console.log('path closes       ' + Math.hypot(pe.x - p0.x, pe.z - p0.z).toFixed(2) + ' m');

/* corridor self-clearance: any two samples more than 40 m apart in arc length must be >= 17 m apart on the
   ground, or the terrain bench and the flora scatter will interfere between neighbouring parts of the trail. */
const step = 2.0, N = Math.floor(L.COURSE_LEN / step);
const P = []; for (let i = 0; i < N; i++){ const q = L.pathAt(i * step); P.push([q.x, q.z]); }
/* The descent leaves the trailhead and the fire road returns to it, so the two necessarily run alongside each
   other there — that is what a trailhead is, and the world builder treats it as one shared staging clearing.
   Exclude that neighbourhood (HEAD m of either end) and require real separation everywhere else. */
const sc = CL.scan(P, s => L.terrainAt(s), L.COURSE_LEN, step);
console.log('closest approach  ' + sc.worst.d.toFixed(1) + ' m horizontally, ' + sc.worst.dh.toFixed(1) + ' m vertically' +
            '  (s=' + sc.worst.a.toFixed(0) + '/' + sc.worst.b.toFixed(0) + ')');
console.log('ribbons merging   ' + sc.merged + '   ' + (sc.merged === 0 ? 'OK' : 'FAIL'));
console.log('cliff banks       ' + sc.cliffs + '   ' + (sc.cliffs === 0 ? 'OK' : 'FAIL — steeper than an armoured bank holds'));

/* bounding box, for the terrain tiler */
let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9;
for (const p of P){ x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); z0 = Math.min(z0, p[1]); z1 = Math.max(z1, p[1]); }
console.log('bbox              ' + (x1 - x0).toFixed(0) + ' x ' + (z1 - z0).toFixed(0) + ' m');

/* every jump must carry lipAt and jump{} or the rider never preloads */
const jumps = L.COURSE.filter(g => g.jump);
const bad = jumps.filter(g => g.lipAt === undefined);
console.log('\njump primitives   ' + jumps.length + '   lipAt present on all: ' + (bad.length === 0 ? 'OK' : 'FAIL ' + bad.map(g => g.name)));
for (const g of jumps) console.log('   ' + g.name.padEnd(20) + g.jump.kind.padEnd(9) + 'H ' + g.jump.H.toFixed(2) + ' m  deck ' +
  g.jump.deck.toFixed(1) + ' m  lip@' + g.lipAt.toFixed(2) + '  land ' + g.jump.landDeg + ' deg' + (g.hEnd ? '  hEnd ' + g.hEnd.toFixed(2) : ''));

const berms = L.COURSE.filter(g => g.corner && g.corner.Hb > 0);
console.log('\nberms             ' + berms.length);
for (const g of berms) console.log('   ' + g.name.padEnd(20) + 'turn ' + String(g.turn).padStart(5) + '  R ' + String(g.corner.R).padStart(4) +
  '  bank ' + (g.corner.bank / C.D2R).toFixed(0) + ' deg  wall ' + g.corner.Hb.toFixed(2) + ' m  side ' + (g.corner.side > 0 ? '+l' : '-l') +
  ' (' + (g.corner.side === -Math.sign(g.turn) ? 'outside OK' : 'INSIDE — BUG') + ')');

console.log('\n=== zones ===');
for (const z of zones) console.log('  ' + z.name.padEnd(16) + String(z.segs).padStart(3) + ' segs  ' + z.len.toFixed(0).padStart(5) + ' m  ' +
  (z.dh >= 0 ? '+' : '') + z.dh.toFixed(1).padStart(6) + ' m  turn ' + String(z.turn).padStart(5) + '  ' +
  [...new Set(z.feats)].join(','));
