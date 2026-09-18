/* ---- one draw call for the bike and rider ----
   The rig arrives from suspension-lab.html as 72 meshes: every tube, stay, spoke, limb and lever is its own draw
   call. That was free against 75 m of lab trail; here it was two thirds of the low tier's budget. Nothing in
   pose() needs the parts to be meshes — it only sets positions, scales and quaternions through aimLimb — so each
   part keeps its Object3D, is hidden, and after every pose() its world matrix is baked into one shared geometry
   with the part's colour carried per vertex. About two thousand vertices transformed on the CPU per frame, for
   seventy-one draw calls saved. pose() and the rig itself are untouched. */
const RIG_MERGE = (() => {
  const parts = [];
  rig.updateMatrixWorld(true);
  rig.traverse(o => { if (o.isMesh) parts.push(o); });
  let nV = 0, nI = 0;
  for (const p of parts){ const g = p.geometry; nV += g.attributes.position.count; nI += g.index ? g.index.count : g.attributes.position.count; }
  const pos = new Float32Array(nV * 3), nor = new Float32Array(nV * 3), col = new Float32Array(nV * 3);
  const idx = nV > 65535 ? new Uint32Array(nI) : new Uint16Array(nI);
  let v0 = 0, i0 = 0;
  for (const p of parts){
    const g = p.geometry, n = g.attributes.position.count, c = p.material.color;
    p.userData.v0 = v0;
    for (let i = 0; i < n; i++){ col[(v0 + i) * 3] = c.r; col[(v0 + i) * 3 + 1] = c.g; col[(v0 + i) * 3 + 2] = c.b; }
    if (g.index){ const ia = g.index.array; for (let i = 0; i < ia.length; i++) idx[i0 + i] = ia[i] + v0; i0 += ia.length; }
    else { for (let i = 0; i < n; i++) idx[i0 + i] = v0 + i; i0 += n; }
    v0 += n;
    p.visible = false;                       // still posed and still in the hierarchy; just never drawn on its own
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.88, metalness: 0 }));
  mesh.name = 'rig-merged';
  mesh.frustumCulled = false; mesh.matrixAutoUpdate = false;     // world-space vertices; the bike is always on screen
  mesh.castShadow = Q.shadow > 0;                                 // the one shadow caster the plan asked for
  scene.add(mesh);
  const _m3 = new THREE.Matrix3(), _v = new THREE.Vector3();
  function update(){
    rig.updateMatrixWorld(true);
    for (const p of parts){
      const g = p.geometry, pa = g.attributes.position.array, na = g.attributes.normal.array, n = g.attributes.position.count;
      const m = p.matrixWorld; _m3.getNormalMatrix(m);
      let o = p.userData.v0 * 3;
      for (let i = 0, k = 0; i < n; i++, o += 3, k += 3){
        _v.set(pa[k], pa[k + 1], pa[k + 2]).applyMatrix4(m); pos[o] = _v.x; pos[o + 1] = _v.y; pos[o + 2] = _v.z;
        _v.set(na[k], na[k + 1], na[k + 2]).applyMatrix3(_m3).normalize(); nor[o] = _v.x; nor[o + 1] = _v.y; nor[o + 2] = _v.z;
      }
    }
    geo.attributes.position.needsUpdate = true; geo.attributes.normal.needsUpdate = true;
    mesh.visible = rig.visible;
  }
  update();
  return { mesh, parts, update, verts: nV, tris: nI / 3 };
})();
