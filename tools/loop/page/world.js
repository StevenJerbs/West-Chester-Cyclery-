/* =============== the world =============== */
/* Everything here is generated at load from course.js. Nothing but the asset meshes and (later) the Cycles bake
   strings ships in the file — at 1.8 km a sculpted track would be ~20 MB of inline JSON and blow the artifact cap.

   Three things are different from the labs, and all three are forced by the scale:
     1. `trailInfo` is a bucket grid, not a linear scan. At 1.8 km it is 3,600 path samples against ~200k terrain
        and scatter queries; the labs' linear scan is 7x10^8 distance computations and takes about a minute.
     2. The terrain is two tiers: a coarse heightfield over the whole world with the trail corridor cut out of it,
        and a fine band that follows the path and carries the bench cut and the berm banks.
     3. The build is staged across frames behind a progress bar, because 1.8 km of ribbon is ~160k vertices and
        doing it in one synchronous block drops the tab for two seconds with a white canvas. */

const _tBuild = performance.now();
const canvas = $('gl'), stage = $('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: Q.aa, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(Q.dpr, window.devicePixelRatio || 1));
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = Q.exp;
renderer.shadowMap.enabled = Q.shadow > 0;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xA9B8AE);
scene.fog = new THREE.FogExp2(0xA8B7AC, Q.fog);   // exponential: distance reads as depth rather than as a wall
const camera = new THREE.PerspectiveCamera(46, 16 / 9, 0.1, 900);
let camAz = 0, camEl = 0;
const camPos = new THREE.Vector3(-4, 3, 4), camLook = new THREE.Vector3();

const sun = new THREE.DirectionalLight(0xF6F2E4, Q.sun);
sun.position.set(25, 80, 12);
if (Q.shadow > 0){
  sun.castShadow = true;
  sun.shadow.mapSize.set(Q.shadow, Q.shadow);
  sun.shadow.camera.near = 1; sun.shadow.camera.far = 90;
  sun.shadow.camera.left = -13; sun.shadow.camera.right = 13;
  sun.shadow.camera.top = 13; sun.shadow.camera.bottom = -13;
  sun.shadow.bias = -0.0012;
}
scene.add(sun, sun.target);
scene.add(new THREE.HemisphereLight(0xC3D2C6, 0x2C3524, Q.hemi));

const mat = c => new THREE.MeshStandardMaterial({ color: c, roughness: 0.88, metalness: 0 });
const box = (w, h, d, c) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(c));

/* A timber bridge is ~76 boxes and a road bench is 4. Left as separate meshes that is 80 draw calls, and with
   SSAO on it is 240, because the pass re-renders the scene for depth and for normals. Bake them into one. */
const _bm = new THREE.Matrix4(), _bq = new THREE.Quaternion(), _be = new THREE.Euler(), _bv = new THREE.Vector3();
function bakeBoxes(parts, opts){
  const per = 24, tri = 36;
  const pos = new Float32Array(parts.length * per * 3), col = new Float32Array(parts.length * per * 3);
  const nrm = new Float32Array(parts.length * per * 3), idx = new Uint32Array(parts.length * tri);
  const c = new THREE.Color(), unit = new THREE.BoxGeometry(1, 1, 1);
  const up = unit.attributes.position.array, un = unit.attributes.normal.array, ui = unit.index.array;
  parts.forEach((p, k) => {
    _be.set(p.rx || 0, p.ry || 0, 0); _bq.setFromEuler(_be);
    _bm.compose(_bv.set(p.x, p.y, p.z), _bq, new THREE.Vector3(p.w, p.h, p.d));
    const nm = new THREE.Matrix3().getNormalMatrix(_bm);
    c.setHex(p.c);
    for (let i = 0; i < per; i++){
      const o = (k * per + i) * 3;
      _bv.set(up[i * 3], up[i * 3 + 1], up[i * 3 + 2]).applyMatrix4(_bm);
      pos[o] = _bv.x; pos[o + 1] = _bv.y; pos[o + 2] = _bv.z;
      _bv.set(un[i * 3], un[i * 3 + 1], un[i * 3 + 2]).applyMatrix3(nm).normalize();
      nrm[o] = _bv.x; nrm[o + 1] = _bv.y; nrm[o + 2] = _bv.z;
      col[o] = c.r; col[o + 1] = c.g; col[o + 2] = c.b;
    }
    for (let i = 0; i < tri; i++) idx[k * tri + i] = ui[i] + k * per;
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('bake', PNW.bakeAttr(null, parts.length * per));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  const m = new THREE.Mesh(g, PNW.bakedMat(Object.assign({ roughness: 0.9 }, opts || {})));
  m.castShadow = m.receiveShadow = true; scene.add(m); return m;
}

/* ---------------- the path, and the bucket grid over it ---------------- */
const pathSamp = [];
for (let i = 0; i < PATH.n; i += 2)
  pathSamp.push({ x: PATH.x[i], z: PATH.z[i], s: i * PATH.ds, th: PATH.th[i], h: LOOP.terrainAt(i * PATH.ds) });
let bx0 = 1e9, bx1 = -1e9, bz0 = 1e9, bz1 = -1e9;
for (const q of pathSamp){ bx0 = Math.min(bx0, q.x); bx1 = Math.max(bx1, q.x); bz0 = Math.min(bz0, q.z); bz1 = Math.max(bz1, q.z); }
const WCX = (bx0 + bx1) / 2, WCZ = (bz0 + bz1) / 2;
const WSIZE = Math.max(bx1 - bx0, bz1 - bz0) + 150;

/* The blend weight is 1/(d^4+1), so a sample 60 m away contributes 1.3e-7 against a near sample's ~1 — three
   20 m cells in each direction is not an approximation at any precision the terrain can show. */
const HCELL = 20, HREACH = 3, HSTRIDE = 4096;
const HKEY = (ix, iz) => (ix + 2048) * HSTRIDE + (iz + 2048);
const HASH = new Map();
for (const q of pathSamp){
  const k = HKEY(Math.floor(q.x / HCELL), Math.floor(q.z / HCELL));
  let a = HASH.get(k); if (!a) HASH.set(k, a = []);
  a.push(q);
}
function trailInfo(x, z){
  const cx = Math.floor(x / HCELL), cz = Math.floor(z / HCELL);
  let wsum = 0, hsum = 0, best = null, bd = 1e9;
  for (let R = HREACH; R <= 48; R += 4){
    wsum = 0; hsum = 0; best = null; bd = 1e9;
    for (let i = -R; i <= R; i++) for (let j = -R; j <= R; j++){
      const a = HASH.get(HKEY(cx + i, cz + j)); if (!a) continue;
      for (let n = 0; n < a.length; n++){
        const q = a[n], dx = x - q.x, dz = z - q.z, d2 = dx * dx + dz * dz;
        if (d2 < bd){ bd = d2; best = q; }
        const w = 1 / (d2 * d2 + 1); wsum += w; hsum += w * q.h;
      }
    }
    if (best) break;
  }
  if (!best) return { h: 0, d: 1e6, s: 0, l: 0, side: 1 };
  /* +l is the path's left-hand normal, the same convention course.js's cross-sections use */
  const l = -Math.sin(best.th) * (x - best.x) + Math.cos(best.th) * (z - best.z);
  return { h: hsum / wsum, d: Math.sqrt(bd), s: best.s, l, side: Math.sign(l) || 1 };
}

/* Value noise. The terrain was tinted with sin(x*0.7)*cos(z*0.9), whose 9 m period sampled on a 3.3 m grid
   aliases into corduroy stripes across the whole hillside. Noise that is smooth at the sampling scale does not. */
function vnoise(x, z){
  const ix = Math.floor(x), iz = Math.floor(z), fx = x - ix, fz = z - iz;
  const u = fx * fx * (3 - 2 * fx), w = fz * fz * (3 - 2 * fz);
  const h2 = (a, b) => hash(a * 157.31 + b * 311.7);
  return lerp(lerp(h2(ix, iz), h2(ix + 1, iz), u), lerp(h2(ix, iz + 1), h2(ix + 1, iz + 1), u), w);
}
const fbm = (x, z) => 0.6 * vnoise(x, z) + 0.3 * vnoise(x * 2.3 + 5.1, z * 2.3 - 3.7) + 0.1 * vnoise(x * 5.7, z * 5.7 + 9.4);

function hills(x, z){
  return 3.6 * Math.sin(x * 0.0165 + 1.3) * Math.cos(z * 0.0142 - 0.4)
       + 2.4 * Math.sin(x * 0.032 - z * 0.024 + 2.0)
       + 1.3 * Math.cos(z * 0.052 + x * 0.009)
       + 0.55 * Math.sin(x * 0.121) * Math.cos(z * 0.104)
       + 2.1 * (fbm(x * 0.021, z * 0.021) - 0.5)
       + 0.7 * (fbm(x * 0.085 + 17, z * 0.085 - 4) - 0.5);
}
/* Out past the corridor the ground is hillside; inside it, it is whatever cross-section the ribbon is using, so
   the bench cut, the berm walls and their backs are one surface with the trail rather than a plane it floats on. */
function worldHeight(x, z, ti){
  ti = ti || trailInfo(x, z);
  if (ti.d > 1e5) return hills(x, z);
  const w = smooth((ti.d - 3.4) / 9.5);
  const bench = LOOP.terrainAt(ti.s) + LOOP.crossAt(ti.s, clamp(ti.l, -7, 7));
  return lerp(bench, ti.h + hills(x, z), w);
}

/* ---------------- the build, staged across frames ---------------- */
const WORLD = { terrain: null, corridor: [], ribbon: [], water: [], leaves: null, tracks: null, ready: false, times: {} };
const STEPS = [];
const buildStep = (label, fn) => STEPS.push({ label, fn });   // not `step`: the physics solver owns that name

/* -- coarse terrain, with the trail corridor cut out of it -- */
const CGRID = QNAME === 'low' ? 120 : 176;
buildStep('terrain', () => {
  const n = CGRID + 1, cell = WSIZE / CGRID;
  const pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3);
  const hs = new Float32Array(n * n), ds = new Float32Array(n * n);
  const c = new THREE.Color();
  for (let iz = 0; iz < n; iz++) for (let ix = 0; ix < n; ix++){
    const i = iz * n + ix;
    const x = WCX - WSIZE / 2 + ix * cell, z = WCZ - WSIZE / 2 + iz * cell;
    const ti = trailInfo(x, z);
    hs[i] = worldHeight(x, z, ti); ds[i] = ti.d;
    pos[i * 3] = x; pos[i * 3 + 1] = hs[i] - 0.04; pos[i * 3 + 2] = z;
  }
  for (let iz = 0; iz < n; iz++) for (let ix = 0; ix < n; ix++){
    const i = iz * n + ix, x = pos[i * 3], z = pos[i * 3 + 2];
    const i1 = ix + 1 < n ? i + 1 : i, i2 = iz + 1 < n ? i + n : i;
    const slope = Math.hypot((hs[i1] - hs[i]) / cell, (hs[i2] - hs[i]) / cell);
    const nz = fbm(x * 0.055, z * 0.055), patch = fbm(x * 0.017 + 11, z * 0.017 - 7);
    if (slope > 0.80) c.setHSL(0.30, 0.06, 0.20 + 0.10 * nz);                     // scree and exposed rock on the steeps
    else if (patch > 0.60) c.setHSL(0.075, 0.30, 0.085 + 0.055 * nz);             // needle duff under closed canopy
    else if (patch < 0.36) c.setHSL(0.24, 0.30, 0.10 + 0.07 * nz);                // moss and salal in the openings
    else c.setHSL(0.30 + 0.035 * nz, 0.22, 0.075 + 0.06 * nz);
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
  }
  const idx = [];
  for (let iz = 0; iz + 1 < n; iz++) for (let ix = 0; ix + 1 < n; ix++){
    const a = iz * n + ix, b = a + 1, d2 = a + n, e = d2 + 1;
    if (Math.min(ds[a], ds[b], ds[d2], ds[e]) < CUT_R) continue;                 // the corridor band covers this
    idx.push(a, d2, b, b, d2, e);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('bake', PNW.bakeAttr('bake_terrain', n * n));
  g.setIndex(idx); g.computeVertexNormals();
  const m = new THREE.Mesh(g, PNW.bakedMat({ flatShading: true, roughness: 0.96 }));
  m.receiveShadow = true; scene.add(m); WORLD.terrain = m;
});
const CUT_R = 7.0;    // the band reaches 10 m, so the tiers overlap by 3 m — a tight berm folds the band's normals and a butt joint would show sky

/* -- fine corridor band: the bench cut, the berm backs and the ground the camera actually sees -- */
/* The closest the loop comes to itself is 12.6 m, so a band wider than about half that has two legs drawing
   their own cross-section over the same ground. Ten metres each side leaves them clear of one another. */
const COR_L = QNAME === 'low' ? [-10, -7, -5, -3.4, 0, 3.4, 5, 7, 10]
                              : [-10, -8, -6.4, -5.2, -4.2, -3.4, -2.6, 0, 2.6, 3.4, 4.2, 5.2, 6.4, 8, 10];
const COR_DS = QNAME === 'low' ? 2.2 : 1.3;
const COR_CHUNKS = Math.max(4, Q.chunks - 2);
buildStep('corridor', () => {
  const NL = COR_L.length, NR = Math.floor(COURSE_LEN / COR_DS);
  const rows = Math.ceil(NR / COR_CHUNKS);
  const c = new THREE.Color();
  for (let ch = 0; ch < COR_CHUNKS; ch++){
    const r0 = ch * rows, r1 = Math.min(NR, r0 + rows) + 1, nr = r1 - r0;
    if (nr < 2) continue;
    const pos = new Float32Array(nr * NL * 3), col = new Float32Array(nr * NL * 3), idx = [];
    const bk = new Float32Array(nr * NL * 2), row = new Float32Array(NL);
    for (let i = 0; i < nr; i++){
      const s = ((r0 + i) % NR) * COR_DS, P = pathAt(s);
      const rx = -Math.sin(P.theta), rz = Math.cos(P.theta), h0 = LOOP.terrainAt(s);
      const gt = groundType(s);
      for (let j = 0; j < NL; j++){
        const l = COR_L[j], k = (i * NL + j) * 3;
        const x = P.x + rx * l, z = P.z + rz * l;
        /* Inside 5 m the band is the trail's own cross-section, so it cannot disagree with the ribbon; outside
           9 m it is the hillside; between, a blend. */
        const near = h0 + LOOP.crossAt(s, l);
        const w = smooth((Math.abs(l) - 3.6) / 3.4);
        const y = w > 0 ? lerp(near, worldHeight(x, z), w) : near;
        pos[k] = x; pos[k + 1] = row[j] = y - 0.03; pos[k + 2] = z;
        const a = Math.abs(l), nz = fbm(x * 0.28, z * 0.28), lit = fbm(x * 0.06 + 3, z * 0.06 + 8);
        if (a < 3.0) c.setHex(gt === 'rock' ? 0x4E564C : gt === 'built' ? 0x59492F : 0x33261A).offsetHSL(0, 0, 0.03 * nz - 0.015 - 0.012 * a);
        else if (lit > 0.58) c.setHSL(0.075, 0.28, 0.075 + 0.05 * nz);            // the litter berm the trail cut threw up
        else c.setHSL(0.29 + 0.04 * nz, 0.22, 0.070 + 0.055 * nz);
        col[k] = c.r; col[k + 1] = c.g; col[k + 2] = c.b;
      }
      for (let j = 0; j < NL; j++){ const o = (i * NL + j) * 2; bk[o] = 1; bk[o + 1] = openness(row[j], row, 3.4); }
      /* Wind so the face normal is up. suspension-lab.html:1055 pushes (a, b, a+1) here, whose cross product
         is forward x left = straight down — the labs get away with it because their ribbon is DoubleSide and
         flat-shaded, but it means every trail surface in them is lit from underneath. */
      if (i + 1 < nr) for (let j = 0; j + 1 < NL; j++){
        const a = i * NL + j, b = (i + 1) * NL + j;
        idx.push(a, a + 1, b, a + 1, b + 1, b);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.setAttribute('bake', new THREE.BufferAttribute(bk, 2));
    g.setIndex(idx); g.computeVertexNormals();
    const m = new THREE.Mesh(g, PNW.bakedMat({ roughness: 0.95 }));
    m.receiveShadow = true; scene.add(m); WORLD.corridor.push(m);
  }
});

/* `bakedMat` reads a two-channel `bake` attribute: sun visibility and ambient occlusion, both ray-traced in
   Cycles. Until that bake exists the attribute is all ones, which on the mobile tier — no shadow map, no SSAO —
   leaves nothing at all darkening a crease and the whole world reads as pale sand. A berm bowl, a bench cut and
   a rock-garden channel are all cases of "this point sits below what is beside it", which is cheap to measure
   from the cross-section the ribbon is already evaluating, and it writes into the same channel the real bake
   will overwrite. */
function openness(y, row, drop){
  let hi = y;
  for (let k = 0; k < row.length; k++) if (row[k] > hi) hi = row[k];
  return clamp(1 - (hi - y) / drop, 0.42, 1);
}

/* -- the ribbon: the surface the wheels actually ride -- */
const RIB_L = QNAME === 'low'  ? [-3.2, -2.4, -1.8, -1.3, -0.8, -0.35, 0, 0.35, 0.8, 1.3, 1.8, 2.4, 3.2]
            : QNAME === 'med'  ? [-3.2, -2.6, -2.1, -1.7, -1.35, -1.0, -0.7, -0.45, -0.22, 0, 0.22, 0.45, 0.7, 1.0, 1.35, 1.7, 2.1, 2.6, 3.2]
            : [-3.2, -2.75, -2.35, -2.0, -1.7, -1.42, -1.15, -0.9, -0.68, -0.48, -0.3, -0.14, 0, 0.14, 0.3, 0.48, 0.68, 0.9, 1.15, 1.42, 1.7, 2.0, 2.35, 2.75, 3.2];
const RIB_DS = QNAME === 'low' ? 0.55 : QNAME === 'med' ? 0.34 : 0.25;
const RIB_CHUNKS = Q.chunks;
buildStep('trail', () => {
  const NL = RIB_L.length, NR = Math.floor(COURSE_LEN / RIB_DS);
  const rows = Math.ceil(NR / RIB_CHUNKS);
  const GC = { dirt: 0x35281B, rock: 0x555D52, built: 0x6A5637, water: 0x2C2A22 };
  const c = new THREE.Color();
  for (let ch = 0; ch < RIB_CHUNKS; ch++){
    const r0 = ch * rows, r1 = Math.min(NR, r0 + rows) + 1, nr = r1 - r0;
    if (nr < 2) continue;
    const pos = new Float32Array(nr * NL * 3), col = new Float32Array(nr * NL * 3), idx = [];
    const bk = new Float32Array(nr * NL * 2), row = new Float32Array(NL);
    for (let i = 0; i < nr; i++){
      const s = ((r0 + i) % NR) * RIB_DS, P = pathAt(s);
      const rx = -Math.sin(P.theta), rz = Math.cos(P.theta);
      const base = GC[groundType(s)] || GC.dirt;
      for (let j = 0; j < NL; j++){
        const l = RIB_L[j], k = (i * NL + j) * 3;
        pos[k] = P.x + rx * l; pos[k + 1] = row[j] = LOOP.groundAt(s, l) + 0.02; pos[k + 2] = P.z + rz * l;
        const a = Math.abs(l);
        c.setHex(base);
        /* the worn line: two packed, darker, wetter ruts either side of the crown, going to loose at the edges */
        const rut = a > 0.2 && a < 0.62 ? -0.030 : 0;
        c.offsetHSL(0, 0, rut + ((i + j) % 2 ? -0.010 : 0.008) + 0.055 * smooth((a - 1.1) / 0.9) - 0.012 * Math.sin(s * 0.9));
        col[k] = c.r; col[k + 1] = c.g; col[k + 2] = c.b;
      }
      for (let j = 0; j < NL; j++){ const o = (i * NL + j) * 2; bk[o] = 1; bk[o + 1] = openness(row[j], row, 1.6); }
      /* Wind so the face normal is up. suspension-lab.html:1055 pushes (a, b, a+1) here, whose cross product
         is forward x left = straight down — the labs get away with it because their ribbon is DoubleSide and
         flat-shaded, but it means every trail surface in them is lit from underneath. */
      if (i + 1 < nr) for (let j = 0; j + 1 < NL; j++){
        const a = i * NL + j, b = (i + 1) * NL + j;
        idx.push(a, a + 1, b, a + 1, b + 1, b);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.setAttribute('bake', new THREE.BufferAttribute(bk, 2));
    g.setIndex(idx); g.computeVertexNormals();
    const m = new THREE.Mesh(g, PNW.bakedMat({ roughness: 0.94 }, 'track'));   // FrontSide: the corridor band is underneath
    m.receiveShadow = true; scene.add(m); WORLD.ribbon.push(m);
  }
});

/* The logging road is a graded bench cut into the hillside, running across the trail. It was first built as two
   long boxes flanking a deck, which put a 2.4 m wall right across the rider's approach to the lip. A bench is
   what it actually is: flat and level with the road cut where the trail crosses it, tipping away into the
   hillside at both ends so it neither floats above the ground nor buries itself in it. */
function buildRoad(g){
  const s0 = g.start + g.road.at, C = pathAt(s0);
  const roadY = LOOP.terrainAt(s0);                                               // h(t) already sits at the bench
  const HALF = 40, DU = 2.0, LAT = [-1, -0.62, -0.5, -0.18, 0.18, 0.5, 0.62, 1];
  /* the road runs along the trail's left normal, and its width lies along the trail's own direction */
  const fx = Math.cos(C.theta), fz = Math.sin(C.theta), nx = -fz, nz = fx;
  const nu = Math.round(2 * HALF / DU) + 1, NLr = LAT.length;
  const pos = new Float32Array(nu * NLr * 3), col = new Float32Array(nu * NLr * 3), idx = [];
  const c = new THREE.Color();
  for (let i = 0; i < nu; i++){
    const u = -HALF + i * DU;
    for (let j = 0; j < NLr; j++){
      const t = LAT[j], across = t * (g.road.w / 2 + 1.6);
      const px = C.x + nx * u + fx * across, pz = C.z + nz * u + fz * across;
      const shoulder = Math.abs(t) > 0.55 ? -0.28 * (Math.abs(t) - 0.55) / 0.45 : 0;
      const fade = smooth((Math.abs(u) - 16) / 22);                               // tip into the hillside at the ends
      const y = lerp(roadY + shoulder, worldHeight(px, pz) - 0.9, fade);
      const k = (i * NLr + j) * 3;
      pos[k] = px; pos[k + 1] = y; pos[k + 2] = pz;
      const gr = fbm(px * 0.5, pz * 0.5);
      if (Math.abs(t) < 0.55) c.setHSL(0.09, 0.07, 0.30 + 0.09 * gr);             // crushed rock, wheel-tracked
      else c.setHSL(0.22, 0.20, 0.13 + 0.06 * gr);                                // the grassy verge
      col[k] = c.r; col[k + 1] = c.g; col[k + 2] = c.b;
      if (i + 1 < nu && j + 1 < NLr){
        const a = i * NLr + j, b = (i + 1) * NLr + j;
        idx.push(a, a + 1, b, a + 1, b + 1, b);
      }
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  geo.setAttribute('bake', PNW.bakeAttr(null, nu * NLr));
  geo.setIndex(idx); geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, PNW.bakedMat({ roughness: 0.95 }, 'track'));
  m.receiveShadow = true; scene.add(m);
  const cu = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, g.road.w + 3.2, 10, 1, true), mat(0x3B3A36));
  cu.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(fx, 0, fz));   // lies across the road
  cu.position.set(C.x + nx * 11, roadY - 0.45, C.z + nz * 11);
  scene.add(cu);
}

/* -- built structures: the logging road under the gap, the creek bridge, the start deck -- */
buildStep('structures', () => {
  const parts = [];                                                              // one geometry for every structure
  for (const g of COURSE){
    if (g.road) buildRoad(g);                                                    // the fire road the gap jumps
    if (g.deck){                                                                 // the creek bridge: planks, then rails
      const NP = Math.floor(g.len / 0.32);
      for (let i = 0; i < NP; i++){
        const s = g.start + (i + 0.5) * g.len / NP, P = pathAt(s);
        parts.push({ w: 0.28, h: 0.055, d: g.deck.w, x: P.x, y: LOOP.terrainAt(s) + 0.03, z: P.z,
                     ry: -P.theta, c: i % 3 === 0 ? 0x6B5B43 : 0x77664C });
      }
      for (let i = 0; i <= 10; i++) for (const sgn of [-1, 1]){
        const s = g.start + i * g.len / 10, P = pathAt(s), y = LOOP.terrainAt(s);
        const o = sgn * (g.deck.w / 2 - 0.06);
        parts.push({ w: 0.07, h: 0.85, d: 0.07, x: P.x - Math.sin(P.theta) * o, y: y + 0.45,
                     z: P.z + Math.cos(P.theta) * o, ry: -P.theta, c: 0x5C4E3A });
        if (i < 10){
          const s2 = g.start + (i + 0.5) * g.len / 10, P2 = pathAt(s2);
          parts.push({ w: g.len / 10 + 0.06, h: 0.06, d: 0.06, x: P2.x - Math.sin(P2.theta) * o,
                       y: LOOP.terrainAt(s2) + 0.85, z: P2.z + Math.cos(P2.theta) * o, ry: -P2.theta, c: 0x5C4E3A });
        }
      }
    }
  }
  if (parts.length) bakeBoxes(parts, { roughness: 0.88 });
  const P0 = pathAt(4), rx0 = -Math.sin(P0.theta), rz0 = Math.cos(P0.theta);
  PNW.instanced(scene, 'startdeck', [{ x: P0.x + rx0 * 3.4, y: worldHeight(P0.x + rx0 * 3.4, P0.z + rz0 * 3.4) - 0.05,
                                       z: P0.z + rz0 * 3.4, ry: -P0.theta, s: 1.0 }], 0);
  const sg = pathAt(6);
  PNW.instanced(scene, 'sign', [{ x: sg.x - Math.sin(sg.theta) * 2.4, y: LOOP.terrainAt(6), z: sg.z + Math.cos(sg.theta) * 2.4, ry: -sg.theta, s: 1.2 }], 0);
});

/* -- water: the creek, and the pools either side of it -- */
buildStep('water', () => {
  const pools = [];
  for (const g of COURSE) if (g.pool) pools.push({ g, p: g.pool });
  for (const { g, p } of pools){
    const sMid = g.start + (p.s0 + p.s1) / 2, P = pathAt(sMid);
    const y = LOOP.terrainAt(sMid) + p.depth * 0.62;                             // the water sits below the banks
    const w = (p.s1 - p.s0) + 3.0;
    /* The creek runs across the trail, so the plane is long across and narrow along. Reflector reflects about its
       own local +Z, so its plane is left unrotated and the mesh is turned instead — rotating the geometry would
       leave the reflection normal pointing sideways. */
    let m;
    if (Q.reflect && typeof THREE.Reflector === 'function'){
      m = new THREE.Reflector(new THREE.PlaneGeometry(24, w, 1, 1),
        { textureWidth: 512, textureHeight: 512, color: 0xFFFFFF, clipBias: 0.004 });
      m.rotation.order = 'YXZ';
      m.rotation.set(-Math.PI / 2, -P.theta, 0);
      /* Reflector's own shader blends the reflection over its colour with an overlay, which on a bright forest
         sky comes out as a sheet of white. Water is not a mirror at this angle: mix the reflection in by
         Fresnel over a peat-dark base, and ripple the sample so it is not a hard mirror image. */
      const rm = m.material;
      rm.uniforms.uT = { value: 0 }; rm.uniforms.uDeep = { value: new THREE.Color(0x22302B) };
      rm.uniforms.uCam = { value: camera.position };
      const NL2 = String.fromCharCode(10);
      rm.vertexShader = rm.vertexShader
        .replace('void main() {', 'varying vec3 vWpos;' + NL2 + 'void main() {')
        .replace('#include <logdepthbuf_vertex>',
                 '#include <logdepthbuf_vertex>' + NL2 + 'vWpos = (modelMatrix * vec4(position, 1.0)).xyz;');
      rm.fragmentShader = 'uniform float uT; uniform vec3 uDeep; uniform vec3 uCam; varying vec3 vWpos;' + NL2 +
        rm.fragmentShader.replace(
          'gl_FragColor = vec4( blendOverlay( base.rgb, color ), 1.0 );',
          ['float rip = sin(vWpos.x * 3.1 + uT * 1.3) * 0.004 + sin(vWpos.z * 4.3 - uT * 0.9) * 0.004;',
           'base = texture2DProj( tDiffuse, vUv + vec4(rip, rip * 0.6, 0.0, 0.0) );',
           'float ct = clamp(abs(normalize(uCam - vWpos).y), 0.0, 1.0);',
           'float fres = 0.045 + 0.955 * pow(1.0 - ct, 4.0);',
           'gl_FragColor = vec4( mix(uDeep, base.rgb * 0.92, clamp(fres, 0.0, 0.82)), 1.0 );'].join(NL2));
      WORLD.waterMat = WORLD.waterMat || []; WORLD.waterMat.push(rm);
    } else {
      const geo = new THREE.PlaneGeometry(24, w, 1, 1); geo.rotateX(-Math.PI / 2);
      geo.setAttribute('bake', PNW.bakeAttr(null, geo.attributes.position.count));
      m = new THREE.Mesh(geo, PNW.bakedMat({ color: 0x38473F, roughness: 0.12, metalness: 0.1,
        transparent: true, opacity: 0.86, vertexColors: false }, 'water'));
      m.rotation.y = -P.theta;
    }
    m.position.set(P.x, y, P.z);
    scene.add(m); WORLD.water.push(m);
    /* wet stones along the waterline */
    const st = [];
    for (let i = 0; i < 46; i++){
      const a = (hash(i * 3.1) - 0.5) * 40, b = (hash(i * 7.7) - 0.5) * (w + 5);
      const rx = -Math.sin(P.theta), rz = Math.cos(P.theta);
      if (Math.abs(a) < 2.6 && Math.abs(b) < 1.5) continue;                       // keep the ford line clean
      st.push({ x: P.x + rx * a - Math.cos(P.theta) * b, y: y - 0.1 - hash(i * 2.3) * 0.2,
                z: P.z + rz * a - Math.sin(P.theta) * b, ry: hash(i) * 6.28, s: 0.3 + hash(i * 5.5) * 0.5 });
    }
    PNW.instanced(scene, 'boulder', st, 0);
  }
});

/* -- scatter: the forest, sized to the quality tier -- */
buildStep('forest', () => {
  let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const P = { cedar: [], cedar2: [], cedar3: [], fir: [], hemlock: [], maple: [], snag: [],
              fern: [], salal: [], foxglove: [], boulder: [], stump: [], nurselog: [], sticks: [], rockedge: [] };
  const put = (a, x, z, y, s0, s1) => a.push({ x, y, z, ry: rnd() * 6.28, s: s0 + rnd() * (s1 - s0) });
  /* Sample along the trail rather than over the bounding box: the loop's corridor is maybe a fifth of its bbox,
     and box-rejection at 1.8 km throws away four samples in five. */
  const near = (dMin, dMax) => {
    const s = rnd() * COURSE_LEN, Pp = pathAt(s);
    const l = (dMin + rnd() * (dMax - dMin)) * (rnd() < 0.5 ? -1 : 1);
    const x = Pp.x - Math.sin(Pp.theta) * l, z = Pp.z + Math.cos(Pp.theta) * l;
    const ti = trailInfo(x, z);
    return ti.d < dMin * 0.72 ? null : { x, z, ti };                              // it fell next to another leg
  };
  const far = () => {
    for (let k = 0; k < 12; k++){
      const x = WCX + (rnd() - 0.5) * WSIZE * 0.94, z = WCZ + (rnd() - 0.5) * WSIZE * 0.94;
      const ti = trailInfo(x, z); if (ti.d > 26) return { x, z, ti };
    }
    return null;
  };
  const F = Q.flora;
  const H = (q, o) => worldHeight(q.x, q.z, q.ti) + (o || 0);
  for (let i = 0; i < Math.round(1500 * F); i++){                                 // the canopy along the corridor
    const q = near(6.5, 34); if (!q) continue;
    const r = rnd();
    const sp = r < 0.20 ? P.cedar : r < 0.26 ? P.cedar3 : r < 0.31 ? P.cedar2 : r < 0.55 ? P.fir
             : r < 0.84 ? P.hemlock : r < 0.90 ? P.snag : P.maple;
    put(sp, q.x, q.z, H(q, -0.25), 0.62, 1.25);
  }
  for (let i = 0; i < Math.round(620 * F); i++){ const q = far(); if (q) put(rnd() < 0.55 ? P.fir : P.hemlock, q.x, q.z, H(q, -0.3), 0.7, 1.4); }
  for (let i = 0; i < Math.round(900 * F); i++){ const q = near(2.0, 5.5); if (q) put(P.fern, q.x, q.z, H(q, -0.02), 0.75, 1.5); }
  for (let i = 0; i < Math.round(520 * F); i++){ const q = near(2.3, 8.0); if (q) put(P.salal, q.x, q.z, H(q, -0.03), 0.8, 1.6); }
  for (let i = 0; i < Math.round(180 * F); i++){ const q = near(2.4, 7.0); if (q) put(P.foxglove, q.x, q.z, H(q, -0.02), 0.7, 1.3); }
  for (let i = 0; i < Math.round(120 * F); i++){ const q = near(3.0, 14); if (q) put(P.stump, q.x, q.z, H(q, -0.05), 0.8, 1.6); }
  for (let i = 0; i < Math.round(150 * F); i++){ const q = near(3.4, 16); if (q) put(P.nurselog, q.x, q.z, H(q, -0.04), 0.8, 1.7); }
  for (let i = 0; i < Math.round(240 * F); i++){ const q = near(1.9, 6.0); if (q) put(P.sticks, q.x, q.z, H(q, -0.01), 0.6, 1.2); }
  /* boulders: dense where the course says the ground is rock, sparse everywhere else */
  for (let i = 0; i < Math.round(420 * F); i++){
    const s = rnd() * COURSE_LEN, rock = groundType(s) === 'rock';
    if (!rock && rnd() > 0.35) continue;
    const Pp = pathAt(s), l = (rock ? 2.1 : 3.2) + rnd() * (rock ? 6 : 22);
    const sgn = rnd() < 0.5 ? -1 : 1;
    const x = Pp.x - Math.sin(Pp.theta) * l * sgn, z = Pp.z + Math.cos(Pp.theta) * l * sgn;
    const ti = trailInfo(x, z); if (ti.d < 1.9) continue;
    put(P.boulder, x, z, worldHeight(x, z, ti) - 0.08, rock ? 0.7 : 0.55, rock ? 2.6 : 1.9);
  }
  for (let i = 0; i < Math.round(300 * F); i++){                                  // armouring stones on the trail edge
    const s = rnd() * COURSE_LEN, Pp = pathAt(s), sgn = rnd() < 0.5 ? -1 : 1, l = (1.5 + rnd() * 0.9) * sgn;
    P.rockedge.push({ x: Pp.x - Math.sin(Pp.theta) * l, y: LOOP.terrainAt(s) + LOOP.crossAt(s, l) - 0.06,
                      z: Pp.z + Math.cos(Pp.theta) * l, ry: rnd() * 6.28, s: 0.5 + rnd() * 0.7 });
  }
  window.PNW_PLACEMENTS = P;
  const WIND = { cedar: 1.0, cedar2: 1.0, cedar3: 1.0, fir: 0.8, hemlock: 0.9, maple: 1.6, snag: 0,
                 fern: 3.2, salal: 2.0, foxglove: 3.6, boulder: 0, stump: 0, nurselog: 0, sticks: 0, rockedge: 0 };
  for (const k of Object.keys(P)) if (P[k].length) PNW.instanced(scene, k, P[k], WIND[k]);
  PNW.sky(scene, WCX, WCZ, WSIZE * 1.05);
  if (QNAME !== 'low') window.PNW_RAVENS = PNW.ravens(scene, WCX, 34, WCZ, WSIZE * 0.26);
  /* mist in the three lowest points of the loop */
  const low = [];
  for (let s = 0; s < COURSE_LEN; s += 12) low.push({ s, y: LOOP.terrainAt(s) });
  low.sort((a, b) => a.y - b.y);
  const picked = [];
  for (const q of low){ if (picked.every(p => Math.abs(p - q.s) > 180)) picked.push(q.s); if (picked.length === 3) break; }
  if (QNAME !== 'low') for (const s of picked){ const q = pathAt(s); PNW.mist(scene, q.x + 8, LOOP.terrainAt(s) + 1.4, q.z - 6, 34, 18, 0.22); }
});

/* -- leaves in the air: one instanced draw call, integrated entirely in the vertex shader -- */
buildStep('leaves', () => {
  const N = Q.leaves;
  const card = new THREE.PlaneGeometry(0.11, 0.075, 1, 1);
  const m = new THREE.MeshStandardMaterial({ color: 0xB2803A, roughness: 0.85, side: THREE.DoubleSide });
  const uT = { value: 0 };
  m.onBeforeCompile = sh => {
    sh.uniforms.uT = uT;
    sh.vertexShader = ('uniform float uT;\n' + sh.vertexShader).replace('#include <project_vertex>', [
      'vec3 sd = vec3(instanceMatrix[3][0], instanceMatrix[3][1], instanceMatrix[3][2]);',
      'float ph = sd.x * 13.7 + sd.z * 7.3;',
      /* drift downwind, fall, and respawn upwind — the modulo is the respawn, so nothing is ever allocated */
      'float dr = mod(sd.x * 91.0 + uT * (1.6 + sd.y * 1.4), 160.0);',
      'float fall = mod(sd.z * 77.0 + uT * (0.35 + sd.y * 0.3), 9.0);',
      'vec3 wp = vec3(dr - 80.0 + sin(uT * 0.7 + ph) * 1.4, 9.0 - fall + sin(uT * 1.9 + ph) * 0.35, sd.z * 160.0 - 80.0 + cos(uT * 0.55 + ph) * 1.9);',
      /* tumble: a cheap axis-angle about a per-leaf axis */
      'float a = uT * (2.1 + sd.y * 2.4) + ph; float ca = cos(a), sa = sin(a);',
      'vec3 ax = normalize(vec3(sd.y - 0.5, 0.6, sd.x - 0.5));',
      'vec3 p = position; p = p * ca + cross(ax, p) * sa + ax * dot(ax, p) * (1.0 - ca);',
      'transformed = p + wp + uOrigin;',
      '#include <project_vertex>'].join('\n'))
      .replace('void main() {', 'uniform vec3 uOrigin;\nvoid main() {');
    sh.uniforms.uOrigin = LEAF_ORIGIN;
  };
  const im = new THREE.InstancedMesh(card, m, N);
  const M = new THREE.Matrix4();
  for (let i = 0; i < N; i++){                                                    // the matrix carries the seed, not a position
    M.identity(); M.elements[12] = hash(i * 1.7); M.elements[13] = hash(i * 3.3); M.elements[14] = hash(i * 5.9);
    im.setMatrixAt(i, M);
  }
  im.instanceMatrix.needsUpdate = true;
  im.frustumCulled = false;
  scene.add(im); WORLD.leaves = { mesh: im, uT };
});
const LEAF_ORIGIN = { value: new THREE.Vector3() };

/* -- the tyre track the rider leaves behind: one strip, rewritten in place -- */
const TRK_N = 260;
buildStep('tracks', () => {
  const pos = new Float32Array(TRK_N * 2 * 3), col = new Float32Array(TRK_N * 2 * 3), idx = [];
  for (let i = 0; i + 1 < TRK_N; i++){ const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setIndex(idx);
  const m = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55, depthWrite: false });
  const mesh = new THREE.Mesh(g, m);
  mesh.renderOrder = 2; mesh.frustumCulled = false; scene.add(mesh);
  mesh.geometry.setDrawRange(0, 0);
  WORLD.tracks = { mesh, pos, col, head: 0, count: 0, lastS: -1e9 };
});
function seedTrack(s, line){                                                       // collapse the strip to a point
  const T = WORLD.tracks; if (!T) return;
  const P = pathAt(s), rx = -Math.sin(P.theta), rz = Math.cos(P.theta);
  for (let n = 0; n < TRK_N; n++) for (let k = 0; k < 2; k++){
    const l = line + (k ? 0.055 : -0.055), o = (n * 2 + k) * 3;
    T.pos[o] = P.x + rx * l; T.pos[o + 1] = LOOP.groundAt(s, l) + 0.035; T.pos[o + 2] = P.z + rz * l;
  }
  T.head = 0; T.count = 0; T.lastS = s;
  T.mesh.geometry.attributes.position.needsUpdate = true;
  T.mesh.geometry.setDrawRange(0, 0);
}
function pushTrack(s, line){
  const T = WORLD.tracks; if (!T) return;
  /* A fresh strip is all zeros and a teleport moves the rider hundreds of metres, either of which draws one very
     long triangle from wherever the strip last was. Re-seed instead of stretching. */
  if (Math.abs(s - T.lastS) > 8){ seedTrack(s, line); return; }
  if (s - T.lastS < 0.35 && s > T.lastS) return;
  T.lastS = s;
  const P = pathAt(s), rx = -Math.sin(P.theta), rz = Math.cos(P.theta);
  const i = T.head * 2;
  for (const [k, off] of [[0, -0.055], [1, 0.055]]){
    const l = line + off, o = (i + k) * 3;
    T.pos[o] = P.x + rx * l; T.pos[o + 1] = LOOP.groundAt(s, l) + 0.035; T.pos[o + 2] = P.z + rz * l;
  }
  T.head = (T.head + 1) % TRK_N; T.count = Math.min(T.count + 1, TRK_N);
  /* fade by age: the newest row is opaque, the oldest transparent, which is one attribute rewrite per frame */
  for (let n = 0; n < TRK_N; n++){
    const age = ((T.head - 1 - n) + TRK_N * 2) % TRK_N;
    const f = 1 - age / TRK_N;
    for (let k = 0; k < 2; k++){ const o = (n * 2 + k) * 3; T.col[o] = 0.13 * f; T.col[o + 1] = 0.10 * f; T.col[o + 2] = 0.07 * f; }
  }
  T.mesh.geometry.attributes.position.needsUpdate = true;
  T.mesh.geometry.attributes.color.needsUpdate = true;
  T.mesh.geometry.setDrawRange(0, Math.max(0, (T.count - 1) * 6));
}

/* ---------------- post-processing ---------------- */
let composer = null;
function buildComposer(){
  if (composer){ composer = null; }
  if (!Q.ssao && !Q.bloom && !Q.smaa) return;
  if (typeof THREE.EffectComposer !== 'function') return;
  const w = renderer.domElement.width, h = renderer.domElement.height;
  composer = new THREE.EffectComposer(renderer);
  composer.addPass(new THREE.RenderPass(scene, camera));
  if (Q.ssao && typeof THREE.SSAOPass === 'function'){
    const p = new THREE.SSAOPass(scene, camera, w, h);
    p.kernelRadius = 7; p.minDistance = 0.0016; p.maxDistance = 0.09; composer.addPass(p);
  }
  if (Q.bloom > 0 && typeof THREE.UnrealBloomPass === 'function')
    composer.addPass(new THREE.UnrealBloomPass(new THREE.Vector2(w, h), Q.bloom, 0.55, 0.88));
  if (Q.smaa && typeof THREE.SMAAPass === 'function') composer.addPass(new THREE.SMAAPass(w, h));
  composer.setSize(w, h);
}

/* ---------------- sizing: the labs hardcode a canvas and never resize; this one follows the stage ---------------- */
function resizeRenderer(){
  const w = Math.max(320, stage.clientWidth), h = Math.round(w * 9 / 16);
  renderer.setPixelRatio(Math.min(Q.dpr, window.devicePixelRatio || 1) * Q.scale);
  renderer.setSize(w, h, false);
  canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
  camera.aspect = w / h; camera.updateProjectionMatrix();
  if (composer) composer.setSize(renderer.domElement.width, renderer.domElement.height);
}

/* ---------------- run the build ---------------- */
function buildWorld(onProgress, onDone){
  let i = 0;
  const next = () => {
    if (i >= STEPS.length){
      buildComposer(); resizeRenderer();
      WORLD.ready = true;
      window.WORLD_BUILD_MS = Object.values(WORLD.times).reduce((a, b) => a + b, 0);   // work, not the frames waited between steps
      window.WORLD_WALL_MS = performance.now() - _tBuild;
      onDone(); return;
    }
    onProgress(i / STEPS.length, STEPS[i].label);
    /* Run whole steps until the frame budget is spent, then yield. One step per frame reads better on the
       progress bar but takes one frame each, and a backgrounded tab throttles rAF to about 1 Hz — or suspends it
       outright — which turned a 270 ms build into never finishing. Budgeting keeps the bar moving and costs
       three or four frames; the setTimeout fallback keeps a hidden tab building. */
    const yieldTo = document.hidden ? (fn => setTimeout(fn, 0)) : requestAnimationFrame;
    yieldTo(() => {
      const budget = performance.now() + 30;
      do {
        const st = STEPS[i];
        const t0 = performance.now(); st.fn();
        WORLD.times[st.label] = +(performance.now() - t0).toFixed(1);
        i++;
      } while (i < STEPS.length && performance.now() < budget);
      next();
    });
  };
  next();
}

function worldTick(t){
  PNW.tick(t);
  if (WORLD.leaves) WORLD.leaves.uT.value = t;
  if (WORLD.waterMat) for (const rm of WORLD.waterMat) rm.uniforms.uT.value = t;
  LEAF_ORIGIN.value.set(Math.round(camLook.x / 160) * 160, Math.max(0, camLook.y - 1.5), Math.round(camLook.z / 160) * 160);
  if (window.PNW_RAVENS) window.PNW_RAVENS(t);
  sun.position.set(camLook.x - 18, camLook.y + 42, camLook.z + 30);
  sun.target.position.copy(camLook);
}
