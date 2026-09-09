/* Apply layout_fit.json into course.js. Kept as a script rather than an ad-hoc regex because the first version
   silently failed to match and left the old fit in place while reporting success. It verifies afterwards. */
const fs = require('fs');
const fit = JSON.parse(fs.readFileSync(__dirname + '/layout_fit.json', 'utf8'));
const turns = {}; for (const t of fit.turns) turns[t.name] = t.turn;
const p = __dirname + '/course.js';
let s = fs.readFileSync(p, 'utf8');
const rf = /const RETURN_FIT = \{[^}]*\};/;
const lf = /const LAYOUT_FIT = \{[\s\S]*?\n\s*\};/;
if (!rf.test(s)) throw new Error('RETURN_FIT block not found');
if (!lf.test(s)) throw new Error('LAYOUT_FIT block not found');
s = s.replace(rf, 'const RETURN_FIT = { retIn: ' + fit.retIn + ', retM: ' + fit.retM + ' };');
s = s.replace(lf, 'const LAYOUT_FIT = ' + JSON.stringify(turns, null, 2).replace(/\n/g, '\n  ') + ';');
fs.writeFileSync(p, s);
delete require.cache[require.resolve('./course.js')];
const C = require('./course.js');
let bad = 0;
for (const [n, v] of Object.entries(turns)){
  const g = C.COURSES.loop.find(x => x.name === n);
  if (!g){ console.log('  no such segment: ' + n); bad++; continue; }
}
const L = C.makeCourse('loop');
for (const [n, v] of Object.entries(turns)){
  const g = L.COURSE.find(x => x.name === n);
  if (g && g.turn !== v){ console.log('  MISMATCH ' + n + ': course ' + g.turn + ' vs fit ' + v); bad++; }
}
if (C.RETURN_FIT.retIn !== fit.retIn || C.RETURN_FIT.retM !== fit.retM){ console.log('  RETURN_FIT mismatch'); bad++; }
console.log(bad ? bad + ' mismatches — NOT applied cleanly' : 'applied: ' + Object.keys(turns).length + ' turns, retIn ' + fit.retIn + ', retM ' + fit.retM);
process.exitCode = bad ? 1 : 0;
