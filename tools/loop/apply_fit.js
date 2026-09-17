/* Apply layout_fit.json into course.js. Kept as a script rather than an ad-hoc regex because the first version
   silently failed to match and left the old fit in place while reporting success. It verifies afterwards. */
const fs = require('fs');
const COURSE_ID = process.argv.indexOf('--course') >= 0 ? process.argv[process.argv.indexOf('--course') + 1] : 'loop';
const PFX = COURSE_ID === 'loop' ? '' : COURSE_ID.toUpperCase() + '_';
const fit = JSON.parse(fs.readFileSync(__dirname + (COURSE_ID === 'loop' ? '/layout_fit.json' : '/layout_fit_' + COURSE_ID + '.json'), 'utf8'));
const turns = {}; for (const t of fit.turns) turns[t.name] = t.turn;
const p = __dirname + '/course.js';
let s = fs.readFileSync(p, 'utf8');
const rf = new RegExp('const ' + PFX + 'RETURN_FIT = \\{[^}]*\\};');
const lf = new RegExp('const ' + PFX + 'LAYOUT_FIT = \\{[\\s\\S]*?\\n\\s*\\};');
if (!rf.test(s)) throw new Error('RETURN_FIT block not found');
if (!lf.test(s)) throw new Error('LAYOUT_FIT block not found');
s = s.replace(rf, 'const ' + PFX + 'RETURN_FIT = { retIn: ' + fit.retIn + ', retM: ' + fit.retM + ' };');
s = s.replace(lf, 'const ' + PFX + 'LAYOUT_FIT = ' + JSON.stringify(turns, null, 2).replace(/\n/g, '\n  ') + ';');
fs.writeFileSync(p, s);
delete require.cache[require.resolve('./course.js')];
const C = require('./course.js');
let bad = 0;
for (const [n, v] of Object.entries(turns)){
  const g = C.COURSES[COURSE_ID].find(x => x.name === n);
  if (!g){ console.log('  no such segment: ' + n); bad++; continue; }
}
const L = C.makeCourse(COURSE_ID);
for (const [n, v] of Object.entries(turns)){
  const g = L.COURSE.find(x => x.name === n);
  if (g && g.turn !== v){ console.log('  MISMATCH ' + n + ': course ' + g.turn + ' vs fit ' + v); bad++; }
}
const RF = C[PFX + 'RETURN_FIT']; if (RF.retIn !== fit.retIn || RF.retM !== fit.retM){ console.log('  RETURN_FIT mismatch'); bad++; }
console.log(bad ? bad + ' mismatches — NOT applied cleanly' : 'applied: ' + Object.keys(turns).length + ' turns, retIn ' + fit.retIn + ', retM ' + fit.retM);
process.exitCode = bad ? 1 : 0;
