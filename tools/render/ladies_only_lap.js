// Headless lap of the Suspension Lab's Ladies Only-inspired course (physics block lifted verbatim from suspension-lab.html).
// Writes a 30 fps trajectory for the Blender render and prints per-segment stats.
const fs = require('fs');
const base = fs.readFileSync(__dirname + '/susp_base.js'  /* lines 271-857 of suspension-lab.html: sed -n '271,857p' suspension-lab.html > susp_base.js */, 'utf8');
const rider = process.argv[2] || 'pro';
const src = `
const DEF = { rlb: 150, effort: 300, vcap: 26, rSpring: 475, rLsc: 8, rHsc: 4, rLsr: 8, rHsr: 4, fSpring: 72, fVol: 3, fLsc: 5, fHsc: 3, fLsr: 6, fHsr: 4 };
const ui = new Proxy({}, { get: (t, k) => t[k] || (t[k] = { value: DEF[k] !== undefined ? DEF[k] : 0, textContent: '', style: {} }) });
` + base + `
riderMode = '${rider}'; applyTuning(); reset();
const FPS = 30, traj = [], seg = new Map(); let t = 0, nextRec = 0;
for (let i = 0; i < 600 * 240; i++){
  const before = lap; step(PDT); t += PDT;
  const [g, gt] = segAt(scroll); const airborne = wheelF.tire <= 0 && wheelR.tire <= 0;
  if (!seg.has(g.name)) seg.set(g.name, { name: g.name, start: g.start, len: g.len, vIn: v, vMin: v, vMax: v, tF: 0, tR: 0, boF: wheelF.bo, boR: wheelR.bo, air: 0, tIn: t, states: new Set() });
  const S = seg.get(g.name); S.vOut = v; S.vMin = Math.min(S.vMin, v); S.vMax = Math.max(S.vMax, v); S.tF = Math.max(S.tF, wheelF.s); S.tR = Math.max(S.tR, wheelR.t); S.tOut = t; S.states.add(poseState); if (airborne) S.air += PDT; S.boF2 = wheelF.bo; S.boR2 = wheelR.bo;
  if (t >= nextRec){ nextRec += 1 / FPS;
    traj.push([+t.toFixed(3), +scroll.toFixed(3), +v.toFixed(3), +chassis.y.toFixed(4), +chassis.phi.toFixed(4), +wheelF.s.toFixed(4), +wheelR.t.toFixed(4), +rider.u.toFixed(4), +cur.hx.toFixed(3), +cur.hy.toFixed(3), +cur.torso.toFixed(2), poseState, +crank.toFixed(3), +corner.lean.toFixed(4), +brakeF.toFixed(0), airborne ? 1 : 0, +wheelF.y.toFixed(4), +wheelR.y.toFixed(4), +dropper.toFixed(3)]); }
  if (lap > before) break;
}
const P = []; for (let i = 0; i < PATH.n; i++) P.push([+PATH.x[i].toFixed(3), +PATH.z[i].toFixed(3), +PATH.th[i].toFixed(4)]);
const out = { rider: '${rider}', fps: FPS, lapTime: +t.toFixed(2), courseLen: +COURSE_LEN.toFixed(2), columns: ['t','s','v','chassisY','phi','forkTravel','rearTravel','riderU','hipX','hipY','torsoDeg','state','crank','lean','brakeN','air','wheelFy','wheelRy','dropper'],
  path: { ds: PATH.ds, pts: P }, course: COURSE.map(g => ({ name: g.name, start: +g.start.toFixed(2), len: +g.len.toFixed(2), grade: +g.grade.toFixed(3), base: +g.base.toFixed(3), type: g.type })),
  obst: OBST.map(o => Object.assign({}, o)), geo: GEO, groundSamples: (() => { const a = []; for (let s = 0; s < COURSE_LEN; s += 0.25) a.push(+groundAt(s).toFixed(4)); return a; })(),
  segments: [...seg.values()].map(S => ({ name: S.name, start: S.start, len: S.len, vIn: +(S.vIn / 0.447).toFixed(1), vOut: +(S.vOut / 0.447).toFixed(1), vMin: +(S.vMin / 0.447).toFixed(1), vMax: +(S.vMax / 0.447).toFixed(1), forkMax: Math.round(S.tF * 1000), rearMax: Math.round(S.tR * 1000), boF: S.boF2 - S.boF, boR: S.boR2 - S.boR, air: +S.air.toFixed(2), time: +(S.tOut - S.tIn).toFixed(2), states: [...S.states] })),
  traj };
require('fs').writeFileSync(__dirname + '/ladies_only_run_${rider}.json', JSON.stringify(out));
console.log('rider', out.rider, 'lap', out.lapTime, 's over', out.courseLen, 'm; frames', traj.length);
for (const S of out.segments) console.log(S.name.padEnd(22), 'in', String(S.vIn).padStart(5), 'out', String(S.vOut).padStart(5), 'min', String(S.vMin).padStart(5), 'max', String(S.vMax).padStart(5), 'mph | fork', String(S.forkMax).padStart(3), 'rear', String(S.rearMax).padStart(3), 'mm | BO', S.boF + '/' + S.boR, '| air', S.air, 's |', S.time, 's |', S.states.join(','));
`;
new Function('require', '__dirname', src)(require, __dirname);
