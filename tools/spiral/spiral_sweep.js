// Headless sweep of the Spiral Lab model (physics lifted verbatim from spiral-lab.html between 'use strict' and the ui block).
// Writes spiral_sweep.json: gains vs radius and entry speed for every scene x technique (Earth and zero-g), plus a few
// full traces (s, r, L, E, W, F/bw, lead angle) for the figures.
const fs = require('fs');
const html = fs.readFileSync(__dirname + '/../../spiral-lab.html', 'utf8');
const a = html.indexOf("'use strict';"), z = html.indexOf('/* =============== ui ===============');
let base = html.slice(a, z);
base = base.replace("let G = 9.81, R = 6.0, V0 = 10 * 0.447, STROKE = 0.30, TSCALE = 0.4, riding = true;", "let G = 9.81, R = 6.0, V0 = 10 * 0.447, STROKE = 0.30, TSCALE = 0.4, riding = true; const $ = () => ({ textContent: '' });");
const src = base + `

function runOne(scn, ti, Rm, v0mph, g, trace){
  scene = SCENES[scn]; tech = TECHS[ti]; R = Rm; V0 = v0mph * 0.447; G = g; STROKE = 0.30;
  reset(); const T = []; let n = 0;
  while (!S.done && n < 200000){ step(S, tech, 1 / 2000); step(GH, RIGID, 1 / 2000); n++;
    if (trace && (n % 20) === 0){ const e = energies(S), q = e.q, gyv = scene.top ? 0 : G, k = e.k, f = e.f, vt = e.sd * f, sp = Math.hypot(vt, S.hd);
      const lead = sp > 0.05 ? 90 - Math.acos(Math.max(-1, Math.min(1, Math.sign(S.F) * S.hd / sp))) / D2R : 0;
      T.push([+S.s.toFixed(3), +(R - scene.sign * S.h).toFixed(3), +(S.ps * R).toFixed(1), +(e.T + e.V).toFixed(1), +S.W.toFixed(1), +(S.F / BW).toFixed(3), +lead.toFixed(2), +(e.sd / 0.447).toFixed(2), +k.toFixed(4), +S.h.toFixed(3), +(S.ps * R - S.Lg).toFixed(1)]); } }
  const e = energies(S), E = e.T + e.V, gyv = scene.top ? 0 : G, Ventry = S.E0 - 0.5 * (M_B + M_R) * V0 * V0;
  const veq = Math.sqrt(Math.max(0, 2 * (E - Ventry - M_R * gyv * (S.h * e.ny - H0)) / (M_B + M_R)));
  return { gain: +((veq - V0) / 0.447).toFixed(3), W: +S.W.toFixed(1), chk: +((E - S.E0) - S.W).toFixed(2), vExit: +(e.sd / 0.447).toFixed(2), stalled: S.phase.startsWith('STALLED'), trace: T.length ? T : undefined, arc: [P.s0, P.s3] };
}
const out = { radii: [3, 4, 5, 6, 7, 8, 9], speeds: [8, 10, 12, 14, 16], scenes: SCENES.map(x => x.id), techs: TECHS.map(x => x.id), grid: {}, traces: {} };
for (const g of [9.81, 0]) for (let sc = 0; sc < 3; sc++) for (let ti = 0; ti < 4; ti++){
  const key = (g ? 'earth' : 'zerog') + '/' + SCENES[sc].id + '/' + TECHS[ti].id; out.grid[key] = {};
  for (const Rm of out.radii) for (const v of out.speeds){ const r = runOne(sc, ti, Rm, v, g, false); out.grid[key][Rm + '@' + v] = [r.gain, r.W, r.chk, r.stalled ? 1 : 0]; } }
for (const [name, sc, ti, Rm, v, g] of [['trough_curve', 0, 0, 6, 10, 9.81], ['trough_slope', 0, 1, 6, 10, 9.81], ['trough_passive', 0, 2, 6, 10, 9.81], ['trough_rigid', 0, 3, 6, 10, 9.81],
  ['trough_curve_zerog', 0, 0, 6, 10, 0], ['crest_pull', 1, 0, 6, 10, 9.81], ['crest_pull_zerog', 1, 0, 6, 10, 0], ['crest_rigid', 1, 3, 6, 10, 9.81], ['berm_curve', 2, 0, 6, 10, 9.81], ['berm_passive', 2, 2, 6, 10, 9.81], ['berm_rigid', 2, 3, 6, 10, 9.81]]){
  const r = runOne(sc, ti, Rm, v, g, true); out.traces[name] = { trace: r.trace, arc: r.arc, gain: r.gain, W: r.W }; }
require('fs').writeFileSync(__dirname + '/spiral_sweep.json', JSON.stringify(out));
console.log('sweep done', Object.keys(out.grid).length, 'series,', Object.keys(out.traces).length, 'traces');
for (const k of Object.keys(out.grid)) console.log(k.padEnd(28), 'R6@10:', out.grid[k]['6@10'][0], 'mph', '| R4@14:', out.grid[k]['4@14'][0], 'mph', '| R9@8:', out.grid[k]['9@8'][0]);
`;
new Function('require', '__dirname', src)(require, __dirname);
