/* The rideability gate for the Cascade Loop.

   Runs the Suspension Lab's bike/rider physics headlessly over the new course, unmodified: the head (bike
   geometry, VPP linkage) and tail (springs, dampers, rider posture, the physics step) are sliced out of
   suspension-lab.html and the course block in between is replaced with tools/loop/course.js. So this validates
   the same solver the page will run, not a copy of it.

   Nothing else in the build starts until every assertion here passes.

   usage: node loop_lap.js [pro|avg] [--json out.json] [--trace]  */
const fs = require('fs');
const path = require('path');
const REPO = path.resolve(__dirname, '../..');
const C = require('./course.js');

const rider = (process.argv[2] === 'avg' ? 'avg' : 'pro');
const wantJson = process.argv.indexOf('--json');

/* ---- slice the physics out of the lab -------------------------------------------------------------- */
const lab = fs.readFileSync(path.join(REPO, 'suspension-lab.html'), 'utf8');
const iHead = lab.indexOf('const D2R = Math.PI / 180, G9 = 9.81;');
const iCourse = lab.indexOf('/* =============== terrain: an elevation-profiled course of trail features ===============');
const iTail = lab.indexOf('/* =============== dampers and springs ===============');
const iEnd = lab.indexOf('/* =============== ui ===============');
if (iHead < 0 || iCourse < 0 || iTail < 0 || iEnd < 0) throw new Error('could not locate the physics block in suspension-lab.html');
const head = lab.slice(iHead, iCourse);          // constants, V10 geometry, VPP linkage + travel table
const tail = lab.slice(iTail, iEnd);             // springs, dampers, bodies, rider posture, the physics step

/* ---- the course, exposed as the bare globals the lab's physics expects ------------------------------ */
const L = C.makeCourse('loop');
const courseGlue = `
const COURSE = __L.COURSE, COURSE_LEN = __L.COURSE_LEN, PATH = __L.PATH, OBST = __L.OBST;
const pathAt = __L.pathAt, segAt = __L.segAt, terrainAt = __L.terrainAt, groundAt = __L.groundAt;
const groundEnv = __L.groundEnv, baseGrade = __L.baseGrade, groundType = __L.groundType;
const bankAt = __L.bankAt, lineLimit = __L.lineLimit;
`;

/* ---- the UI the lab's physics reads its setup from ------------------------------------------------- */
const DEF = { rlb: 150, effort: 300, vcap: 26, rSpring: 475, rLsc: 8, rHsc: 4, rLsr: 8, rHsr: 4,
              fSpring: 72, fVol: 3, fLsc: 5, fHsc: 3, fLsr: 6, fHsr: 4 };
const uiGlue = `
const ui = new Proxy({}, { get: (t, k) => t[k] || (t[k] = { value: __DEF[k] !== undefined ? __DEF[k] : 0, textContent: '', style: {} }) });
`;

const src = uiGlue + head + courseGlue + tail + `
/* ---- run one lap, recording what matters per zone -------------------------------------------------- */
riderMode = '${rider}'; applyTuning(); reset();
const FPS = 30, traj = [], zones = new Map(), events = [];
let t = 0, nextRec = 0, wasAir = false, airStart = 0, airStartS = 0, airStartPhi = 0, minV = 1e9, stalls = 0;
const zoneOf = u => { const g = segAt(u)[0]; return g.zone || 'RETURN'; };
for (let i = 0; i < 600 * 400; i++){
  const before = lap;
  const segBefore = segAt(scroll)[0];
  step(PDT); t += PDT;
  const [g, gt] = segAt(scroll);
  const air = wheelF.tire <= 0 && wheelR.tire <= 0;
  const zn = g.zone || 'RETURN';
  if (!zones.has(zn)) zones.set(zn, { name: zn, vIn: v, vMin: v, vMax: v, tF: 0, tR: 0,
      boF: wheelF.bo, boR: wheelR.bo, air: 0, tIn: t, states: new Set(), maxUse: 0, slid: 0 });
  const Z = zones.get(zn);
  Z.vOut = v; Z.vMin = Math.min(Z.vMin, v); Z.vMax = Math.max(Z.vMax, v);
  Z.tF = Math.max(Z.tF, wheelF.s); Z.tR = Math.max(Z.tR, wheelR.t); Z.tOut = t;
  Z.states.add(poseState); if (air) Z.air += PDT;
  Z.boF2 = wheelF.bo; Z.boR2 = wheelR.bo;
  Z.maxUse = Math.max(Z.maxUse, corner.usage); if (corner.sliding) Z.slid += PDT;
  if (g.zone !== 'MILL GRADE' && zn !== 'RETURN'){ minV = Math.min(minV, v); if (v < 2.0) stalls += PDT; }
  /* takeoff / landing bookkeeping on every jump */
  if (air && !wasAir){ airStart = t; airStartS = scroll; airStartPhi = chassis.phi; }
  if (!air && wasAir){
    const dur = t - airStart;
    if (dur > 0.10){
      const [lg, lt] = segAt(scroll);
      const slope = Math.atan((groundAt(scroll + 0.5) - groundAt(scroll - 0.5)) / 1.0);
      events.push({ kind: 'air', from: segAt(airStartS)[0].name, to: lg.name, zone: zoneOf(airStartS),
        dur: +dur.toFixed(3), gap: +(scroll - airStartS).toFixed(2), v: +(v / 0.447).toFixed(1),
        landSlope: +(slope * 180 / Math.PI).toFixed(1), phi: +(chassis.phi * 180 / Math.PI).toFixed(1),
        mis: +((chassis.phi - slope) * 180 / Math.PI).toFixed(1),
        landAt: +lt.toFixed(2), landLen: +lg.len.toFixed(1) });
    }
  }
  wasAir = air;
  if (t >= nextRec){ nextRec += 1 / FPS;
    traj.push([+t.toFixed(3), +scroll.toFixed(3), +v.toFixed(3), +chassis.y.toFixed(4), +chassis.phi.toFixed(4),
      +wheelF.s.toFixed(4), +wheelR.t.toFixed(4), +rider.u.toFixed(4), +cur.hx.toFixed(3), +cur.hy.toFixed(3),
      +cur.torso.toFixed(2), poseState, +crank.toFixed(3), +corner.lean.toFixed(4), +brakeF.toFixed(0),
      air ? 1 : 0, +wheelF.y.toFixed(4), +wheelR.y.toFixed(4), +dropper.toFixed(3)]); }
  if (lap > before) break;
}
__report({ rider: '${rider}', lapTime: t, minV, stalls, zones: [...zones.values()], events, traj,
  COURSE, COURSE_LEN, GEO, PATH,
  groundSamples: (() => { const a = []; for (let s = 0; s < COURSE_LEN; s += 0.25) a.push(+groundAt(s).toFixed(4)); return a; })() });
`;

let R = null;
new Function('__DEF', '__L', '__report', src)(DEF, L, r => { R = r; });

/* ---- the gate ------------------------------------------------------------------------------------- */
let fails = 0, warns = 0;
const bad = m => { console.log('   FAIL  ' + m); fails++; };
const warn = m => { console.log('   warn  ' + m); warns++; };

console.log('=== CASCADE LOOP · rideability (' + R.rider + ') ===');
console.log('lap ' + R.lapTime.toFixed(1) + ' s over ' + R.COURSE_LEN.toFixed(0) + ' m   min descent speed ' +
            (R.minV / 0.447).toFixed(1) + ' mph   time under 2 m/s: ' + R.stalls.toFixed(2) + ' s\n');

console.log('zone              in   out   min   max mph | fork rear mm | BO  | air s | slide | grip | time');
for (const Z of R.zones){
  const mph = x => (x / 0.447).toFixed(1).padStart(5);
  console.log('  ' + Z.name.padEnd(15) + mph(Z.vIn) + mph(Z.vOut) + mph(Z.vMin) + mph(Z.vMax) +
    ' | ' + String(Math.round(Z.tF * 1000)).padStart(4) + String(Math.round(Z.tR * 1000)).padStart(5) +
    '    | ' + ((Z.boF2 - Z.boF) + '/' + (Z.boR2 - Z.boR)).padEnd(4) +
    '| ' + Z.air.toFixed(2).padStart(5) + ' | ' + Z.slid.toFixed(2).padStart(5) + ' | ' +
    Z.maxUse.toFixed(2).padStart(4) + ' | ' + (Z.tOut - Z.tIn).toFixed(1).padStart(5) + ' s');
}

console.log('\nairs:');
for (const e of R.events){
  const past = e.landAt, ok = e.kind === 'air';
  console.log('  ' + e.from.padEnd(18) + '-> ' + e.to.padEnd(18) + e.dur.toFixed(2) + ' s  ' + e.gap.toFixed(1).padStart(5) +
    ' m  land ' + String(e.landSlope).padStart(6) + ' deg  bike ' + String(e.phi).padStart(6) +
    '  mismatch ' + String(e.mis).padStart(6) + ' deg  ' + e.v + ' mph');
}

console.log('\nchecks:');
const jumps = R.COURSE.filter(g => g.jump);
for (const g of jumps){
  const ev = R.events.filter(e => e.from === g.name);
  if (!ev.length){ bad(g.name + ': never left the ground'); continue; }
  const e = ev[0];
  /* a drop or a huck is a roll-off, not a launch; a road gap is the biggest air on the trail by design */
  const lo = (g.jump.kind === 'drop' || g.jump.kind === 'huck') ? 0.22 : 0.45;
  const hi = g.jump.kind === 'roadgap' ? 1.75 : 1.45;
  if (e.dur < lo) bad(g.name + ': air ' + e.dur + ' s is under ' + lo);
  else if (e.dur > hi) bad(g.name + ': air ' + e.dur + ' s is over ' + hi);
  if (Math.abs(e.mis) > 22) bad(g.name + ': landed ' + e.mis + ' deg off the landing slope');
  else if (Math.abs(e.mis) > 15) warn(g.name + ': landed ' + e.mis + ' deg off the landing slope');
  if (g.jump.kind === 'table' || g.jump.kind === 'roadgap'){
    const deckEnd = g.lipAt + g.jump.deck;
    if (e.to === g.name && e.landAt < deckEnd)
      bad(g.name + ': cased — down on the deck at ' + e.landAt + ' m of ' + deckEnd.toFixed(1) +
          '  (carried ' + e.gap.toFixed(1) + ' m at ' + e.v + ' mph; deck should be about ' + Math.max(2.5, e.gap * 0.72).toFixed(1) + ' m)');
  }
}
for (const Z of R.zones){
  if (Z.name === 'MILL GRADE' || Z.name === 'RETURN') continue;
  const boF = Z.boF2 - Z.boF, boR = Z.boR2 - Z.boR, cap = R.rider === 'pro' ? 1 : 3;
  if (boF > cap || boR > cap) bad(Z.name + ': ' + boF + '/' + boR + ' bottom-outs (cap ' + cap + ')');
  if (Z.maxUse > (R.rider === 'pro' ? 1.00 : 1.15)) bad(Z.name + ': grip usage peaked at ' + Z.maxUse.toFixed(2));
  if (Z.slid > 0.35) bad(Z.name + ': sliding for ' + Z.slid.toFixed(2) + ' s');
}
const mill = R.zones.find(z => z.name === 'MILL GRADE');
if (mill && mill.vMin < 1.5) bad('MILL GRADE: stalled to ' + (mill.vMin / 0.447).toFixed(1) + ' mph');
if (R.stalls > 0.5) bad('descent: ' + R.stalls.toFixed(2) + ' s under 2 m/s');
if (R.lapTime < 150 || R.lapTime > 420) warn('lap time ' + R.lapTime.toFixed(0) + ' s is outside 150-420 s');

console.log(fails ? '\n' + fails + ' FAILURES, ' + warns + ' warnings — not rideable yet' : '\nall checks passed' + (warns ? ' (' + warns + ' warnings)' : ''));

if (wantJson > 0){
  const out = { rider: R.rider, fps: 30, lapTime: +R.lapTime.toFixed(2), courseLen: +R.COURSE_LEN.toFixed(2),
    columns: ['t','s','v','chassisY','phi','forkTravel','rearTravel','riderU','hipX','hipY','torsoDeg','state','crank','lean','brakeN','air','wheelFy','wheelRy','dropper'],
    path: { ds: R.PATH.ds, pts: (() => { const a = []; for (let i = 0; i < R.PATH.n; i++) a.push([+R.PATH.x[i].toFixed(3), +R.PATH.z[i].toFixed(3), +R.PATH.th[i].toFixed(4)]); return a; })() },
    course: R.COURSE.map(g => ({ name: g.name, zone: g.zone || 'RETURN', start: +g.start.toFixed(2), len: +g.len.toFixed(2),
      grade: +g.grade.toFixed(4), base: +g.base.toFixed(3), type: g.type, turn: g.turn || 0 })),
    obst: R.OBST || [], geo: R.GEO, groundSamples: R.groundSamples, events: R.events, traj: R.traj };
  fs.writeFileSync(process.argv[wantJson + 1], JSON.stringify(out));
  console.log('wrote ' + process.argv[wantJson + 1] + ' (' + R.traj.length + ' frames)');
}
process.exitCode = fails ? 1 : 0;
