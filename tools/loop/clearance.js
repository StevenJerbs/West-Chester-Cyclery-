/* The one definition of a trail conflicting with itself, shared by fit_layout.js and check_geom.js so the
   optimiser and the gate cannot disagree.

   Two sections of trail may run close together where there is enough elevation between them to bank at a slope
   dirt (or armoured dirt) holds — that is a switchback, and it is how a trail fits onto a hillside. What must
   not happen is the 3 m ribbons merging, or a wall standing between them that no bank could hold. */
const MIN_ARC = 40;      // closer than this along the trail and it is the same corner, not a conflict
const MIN_SEP = 6.5;     // metres: two 3 m ribbons plus a shoulder
const MAX_BANK = 1.4;    // dh/d: about 54 deg, what an armoured cut bank holds
const NEAR = 25;         // only pairs closer than this can conflict

function scan(sampleXZ, elevAt, courseLen, step){
  const N = sampleXZ.length;
  let worst = { d: 1e9, dh: 0, a: 0, b: 0 }, merged = 0, cliffs = 0, viol = 0;
  for (let i = 0; i < N; i++) for (let j = i + Math.ceil(MIN_ARC / step); j < N; j++){
    if (Math.min((j - i) * step, courseLen - (j - i) * step) < MIN_ARC) continue;
    const dx = sampleXZ[i][0] - sampleXZ[j][0], dz = sampleXZ[i][1] - sampleXZ[j][1], d2 = dx * dx + dz * dz;
    if (d2 > NEAR * NEAR) continue;
    const d = Math.sqrt(d2), dh = Math.abs(elevAt(i * step) - elevAt(j * step));
    if (d < worst.d) worst = { d, dh, a: i * step, b: j * step };
    if (d < MIN_SEP){ merged++; viol += (MIN_SEP - d) * 3; }
    else if (dh / d > MAX_BANK){ cliffs++; viol += (dh / d - MAX_BANK) * 2; }
  }
  return { worst, merged, cliffs, viol };
}
module.exports = { scan, MIN_ARC, MIN_SEP, MAX_BANK, NEAR };
