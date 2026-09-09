/* Assemble trail-loop.html from the proven parts plus the new world generator.

   The page is built rather than hand-written because three of its four big pieces already exist and are
   validated: the PNW asset module and its baked-light materials (pump-lab), the V10 physics and rider posture
   controller (suspension-lab), and the bike rig. Re-deriving them by hand would fork them. What is new here is
   the world generator — spatial hash, two-tier terrain, chunked ribbon, quality tiers — and the mode layer.

   Run: node tools/loop/build_page.js     ->  trail-loop.html
*/
const fs = require('fs');
const path = require('path');
const REPO = path.resolve(__dirname, '../..');
const R = f => fs.readFileSync(path.join(REPO, f), 'utf8');
const between = (s, a, b, label) => {
  const i = s.indexOf(a), j = b === null ? s.length : s.indexOf(b, i + a.length);
  if (i < 0 || (b !== null && j < 0)) throw new Error('could not slice ' + label);
  return s.slice(i, b === null ? undefined : j);
};

const pump = R('pump-lab.html');
const susp = R('suspension-lab.html');
const course = fs.readFileSync(path.join(__dirname, 'course.js'), 'utf8');

/* ---- 1. assets: the PNW module, and PNW_DATA without the 1.09 MB sculpted track or the old bake strings ---- */
const pnwModule = between(pump, 'const PNW = (() => {', '</script>', 'PNW module');
const dataLine = between(pump, 'const PNW_DATA = ', '\n', 'PNW_DATA');
const data = JSON.parse(dataLine.slice('const PNW_DATA = '.length).trim().replace(/;$/, ''));   // the source is CRLF
for (const k of ['track', 'bake_terrain', 'bake_track']) delete data[k];   // the loop generates its own surfaces
const assetsJson = 'const PNW_DATA = ' + JSON.stringify(data) + ';';
const assetKB = (assetsJson.length / 1024).toFixed(0);

/* ---- 2. physics: the V10 head and the solver tail, with our course between them ---- */
const physHead = between(susp, 'const D2R = Math.PI / 180, G9 = 9.81;',
  '/* =============== terrain: an elevation-profiled course of trail features ===============', 'physics head');
const physTail = between(susp, '/* =============== dampers and springs ===============',
  '/* =============== ui ===============', 'physics tail');

/* ---- 3. the bike rig and its pose function ---- */
const rig = between(susp, '/* limbs */', '/* =============== main loop ===============', 'bike rig');

/* ---- 4. the pieces this build writes itself ---- */
const worldJs = fs.readFileSync(path.join(__dirname, 'page/world.js'), 'utf8');
const uiJs = fs.readFileSync(path.join(__dirname, 'page/ui.js'), 'utf8');
const loopJs = fs.readFileSync(path.join(__dirname, 'page/loop.js'), 'utf8');
const headHtml = fs.readFileSync(path.join(__dirname, 'page/head.html'), 'utf8');

const CDN = ['https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js',
  'postprocessing/Pass.js', 'postprocessing/EffectComposer.js', 'postprocessing/RenderPass.js',
  'postprocessing/ShaderPass.js', 'shaders/CopyShader.js', 'shaders/SSAOShader.js', 'math/SimplexNoise.js',
  'postprocessing/SSAOPass.js', 'shaders/LuminosityHighPassShader.js', 'postprocessing/UnrealBloomPass.js',
  'shaders/SMAAShader.js', 'postprocessing/SMAAPass.js', 'objects/Reflector.js']
  .map(u => '<script src="' + (u.startsWith('http') ? u : 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/' + u) + '"></script>')
  .join('\n');

/* the course module runs as a plain script here; strip its UMD wrapper and expose the API */
const courseInline = course
  .replace(/^\(function \(root, factory\) \{[\s\S]*?\}\)\(typeof self[^\n]*\n/m, '/* course.js, inlined */\nconst COURSE_API = (() => {\n')
  .replace(/return \{ SEG, COURSES, makeCourse[^\n]*\n\}\);\n?$/m, (m) => m.replace(/\}\);\s*$/, '})();\n'));

const out = headHtml
  + '\n' + CDN + '\n'
  + '<script>\n\'use strict\';\n' + assetsJson + '\n' + pnwModule + '\n</script>\n'
  + '<script>\n\'use strict\';\n'
  + '/* ============ the course: tools/loop/course.js, inlined ============ */\n' + courseInline + '\n'
  + 'const { SEG, COURSES, makeCourse } = COURSE_API;\n'
  + 'const LOOP = makeCourse(\'loop\');\n'
  + 'const COURSE = LOOP.COURSE, COURSE_LEN = LOOP.COURSE_LEN, PATH = LOOP.PATH, OBST = LOOP.OBST;\n'
  + 'const pathAt = LOOP.pathAt, segAt = LOOP.segAt, terrainAt = LOOP.terrainAt;\n'
  /* The solver is one-dimensional along `scroll`; it samples the ground through groundAt/groundEnv and nothing
     else. Injecting the rider\'s lateral line here — rather than editing the solver — buys high and low lines
     through the berms and the rock gardens without touching a line of physics that the gate has signed off. */
  + 'let RIDE_LINE = 0;\n'
  + 'const groundAt = (u, l) => LOOP.groundAt(u, l === undefined ? RIDE_LINE : l);\n'
  + 'const groundEnv = (u, r, l) => LOOP.groundEnv(u, r, l === undefined ? RIDE_LINE : l);\n'
  + 'const baseGrade = LOOP.baseGrade, groundType = LOOP.groundType;\n'
  + 'const bankAt = LOOP.bankAt, bankSide = LOOP.bankSide, crossAt = LOOP.crossAt, lineLimit = LOOP.lineLimit;\n'
  + 'const addObst = LOOP.addObst, obstH = LOOP.obstH;\n\n'
  + '/* ============ UI shim: the physics reads its setup from these ============ */\n' + uiJs + '\n'
  + '/* ============ physics: suspension-lab.html, verbatim ============ */\n'
  + '/*<<<PHYSICS>>>*/\n' + physHead + physTail + '/*<<</PHYSICS>>>*/\n\n'
  + '/* ============ the world ============ */\n' + worldJs + '\n'
  + '/* ============ the bike, from suspension-lab.html ============ */\n' + rig + '\n'
  + '/* ============ modes, camera and the frame loop ============ */\n' + loopJs + '\n'
  + '</script>\n';

fs.writeFileSync(path.join(REPO, 'trail-loop.html'), out);
console.log('trail-loop.html  ' + (out.length / 1024).toFixed(0) + ' KB');
console.log('  assets ' + assetKB + ' KB (' + Object.keys(data).length + ' meshes, no sculpted track)');
console.log('  physics ' + ((physHead.length + physTail.length) / 1024).toFixed(0) + ' KB, course ' +
            (courseInline.length / 1024).toFixed(0) + ' KB, world ' + (worldJs.length / 1024).toFixed(0) + ' KB');
/* syntax-check every inline block */
let bad = 0;
for (const m of out.matchAll(/<script>([\s\S]*?)<\/script>/g)){
  try { new Function(m[1]); } catch (e){ console.log('  SYNTAX: ' + e.message); bad++; }
}
console.log(bad ? '  ' + bad + ' block(s) failed to parse' : '  all script blocks parse');
process.exitCode = bad ? 1 : 0;
