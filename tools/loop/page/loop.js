/* =============== modes, input, HUD and the frame loop =============== */

/* ---- the readouts ---- */
const mm = $('mm'), mmc = mm.getContext('2d');
const MPH = 2.23694;
let hudT = 0, calls = 0, callsMax = 0, frameMax = 0, frameMs = 16, airStart = -1, airBest = 0, lastAir = 0;

function drawMinimap(){
  const W = mm.width, H = mm.height;
  const scale = Math.min(W, H) * 0.9 / Math.max(bx1 - bx0, bz1 - bz0);
  const tx = x => W / 2 + (x - WCX) * scale, tz = z => H / 2 + (z - WCZ) * scale;
  mmc.clearRect(0, 0, W, H);
  mmc.fillStyle = 'rgba(18,21,14,0.62)'; mmc.fillRect(0, 0, W, H);
  /* the descent in warm ochre, the fire-road climb in cool grey — the loop reads as two halves at a glance */
  mmc.lineWidth = 2.4; mmc.lineCap = 'round';
  let prevClimb = null;
  mmc.beginPath();
  for (let i = 0; i < PATH.n; i += 2){
    const s = i * PATH.ds, climb = segAt(s)[0].zone === 'MILL GRADE';
    if (climb !== prevClimb){
      if (prevClimb !== null){ mmc.strokeStyle = prevClimb ? '#6E7A72' : '#D9A441'; mmc.stroke(); }
      mmc.beginPath(); mmc.moveTo(tx(PATH.x[i]), tz(PATH.z[i])); prevClimb = climb;
    } else mmc.lineTo(tx(PATH.x[i]), tz(PATH.z[i]));
  }
  mmc.strokeStyle = prevClimb ? '#6E7A72' : '#D9A441'; mmc.stroke();
  const P = pathAt(scroll);
  mmc.fillStyle = '#EFE8D6';
  mmc.beginPath(); mmc.arc(tx(P.x), tz(P.z), 3.4, 0, 7); mmc.fill();
  mmc.strokeStyle = '#EFE8D6'; mmc.lineWidth = 1.6;
  mmc.beginPath(); mmc.moveTo(tx(P.x), tz(P.z));
  mmc.lineTo(tx(P.x) + Math.cos(P.theta) * 10, tz(P.z) + Math.sin(P.theta) * 10); mmc.stroke();
}

const STATE_LABEL = { seated: 'SEATED', attack: 'ATTACK', preload: 'PRELOAD', pop: 'POP', air: 'AIRBORNE',
                      land: 'LANDING', huck: 'HUCK', pump: 'PUMPING' };
function updateHud(){
  const [g, t] = segAt(scroll);
  const airborne = poseState === 'air' || poseState === 'huck';
  if (airborne && airStart < 0) airStart = performance.now();
  if (!airborne && airStart > 0){ lastAir = (performance.now() - airStart) / 1000; airBest = Math.max(airBest, lastAir); airStart = -1; }
  $('hudZone').textContent = g.zone || g.name;
  $('hudSpd').textContent = (v * MPH).toFixed(1) + ' mph';
  $('hudGrade').textContent = (baseGrade(scroll) * 100).toFixed(0) + '%';
  $('hudState').textContent = STATE_LABEL[poseState] || poseState.toUpperCase();
  $('hudExtra').textContent = g.name + '  ' + t.toFixed(0) + '/' + g.len.toFixed(0) + ' m';
  $('zoneName').textContent = g.zone || g.name;
  $('zoneInfo').innerHTML = 'lap ' + lap + ' &middot; ' + scroll.toFixed(0) + ' / ' + COURSE_LEN.toFixed(0) + ' m';
  $('cSpeed').textContent = (v * MPH).toFixed(1) + ' mph';
  $('cDist').textContent = (scroll / 1000).toFixed(2) + ' km';
  $('cTravel').textContent = (wheelF.s * 1000).toFixed(0) + ' / ' + (wheelR.t * 1000).toFixed(0) + ' mm';
  const air = $('cAir');
  air.textContent = (airborne ? ((performance.now() - airStart) / 1000).toFixed(2) : lastAir.toFixed(2)) + ' s'
                  + (airBest > 0 ? '  (best ' + airBest.toFixed(2) + ')' : '');
  air.className = 'v' + (airborne ? ' good' : '');
  const lim = lineLimit(scroll);
  $('cLine').textContent = (RIDE_LINE >= 0 ? '+' : '') + RIDE_LINE.toFixed(2) + ' m'
                         + (lim[1] > 1.5 ? '  berm' : '');
  const gr = $('cCalls');
  gr.textContent = calls; gr.className = 'v' + (calls > Q.draw ? ' warn' : ' good');
  const fr = $('cFrame');
  fr.textContent = frameMs.toFixed(1) + ' ms  ' + (1000 / frameMs).toFixed(0) + ' fps';
  fr.className = 'v' + (frameMs > 22 ? ' warn' : ' good');
}

/* ---- input ---- */
const INPUT = { brake: 0, pedal: 0, lean: 0, fly: { f: 0, r: 0, u: 0 } };
const KEY = {};
const VCAP_BASE = 30 * 0.447;
let MODE = 'ride', paused = false;

addEventListener('keydown', e => {
  KEY[e.code] = true;
  if (e.code === 'Space' && MODE !== 'fly'){ e.preventDefault(); togglePause(); }   // in free cam, space is "up"
  if (e.code === 'KeyR') restart();
});
addEventListener('keyup', e => { KEY[e.code] = false; });

let dragging = false, dragPx = 0, dragPy = 0, dragMoved = false, touchZone = 0;
const stagePos = e => { const r = canvas.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; };
canvas.addEventListener('pointerdown', e => {
  canvas.setPointerCapture(e.pointerId);
  dragging = true; dragMoved = false; dragPx = e.clientX; dragPy = e.clientY;
  if (e.pointerType === 'touch'){ touchZone = stagePos(e).x < 0.5 ? -1 : 1; }
});
canvas.addEventListener('pointermove', e => {
  if (!dragging) return;
  const dx = e.clientX - dragPx, dy = e.clientY - dragPy;
  if (Math.abs(dx) + Math.abs(dy) > 6) dragMoved = true;
  camAz += dx * 0.006; camEl = clamp(camEl + dy * 0.004, -0.35, 0.95);
  dragPx = e.clientX; dragPy = e.clientY;
});
const endDrag = e => { dragging = false; touchZone = 0; if (e && e.pointerId !== undefined && canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId); };
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);
canvas.addEventListener('wheel', e => { e.preventDefault(); camEl = clamp(camEl + e.deltaY * 0.0006, -0.35, 0.95); }, { passive: false });

function readInput(dt){
  const kb = KEY.ArrowDown || KEY.KeyS || KEY.ShiftLeft ? 1 : 0;
  const kp = KEY.ArrowUp || KEY.KeyW ? 1 : 0;
  const tb = touchZone === -1 && !dragMoved ? 1 : 0, tp = touchZone === 1 && !dragMoved ? 1 : 0;
  const wantB = Math.max(kb, tb), wantP = Math.max(kp, tp);
  INPUT.brake += (wantB - INPUT.brake) * Math.min(1, dt * 9);
  INPUT.pedal += (wantP - INPUT.pedal) * Math.min(1, dt * 6);
  const kl = (KEY.ArrowLeft || KEY.KeyA ? -1 : 0) + (KEY.ArrowRight || KEY.KeyD ? 1 : 0);
  INPUT.lean += (kl - INPUT.lean) * Math.min(1, dt * 5);
  /* Speed is not a throttle on a DH bike: the brakes set it. Pedalling adds a little on the flat and the climb;
     the brake takes a lot away everywhere. The physics reads only vCap and effortW, so nothing here reaches
     around the solver. */
  vCap = VCAP_BASE * (INPUT.brake > 0.02 ? lerp(1, 0.22, INPUT.brake) : lerp(0.86, 1.16, INPUT.pedal));
  effortW = lerp(190, 420, INPUT.pedal);
  /* the line: A/D pick a line across the tread, and the berms open up a high line on the wall */
  const lim = lineLimit(scroll);
  const want = INPUT.lean < 0 ? -INPUT.lean * lim[0] : INPUT.lean * lim[1];
  RIDE_LINE += (clamp(want, lim[0], lim[1]) - RIDE_LINE) * Math.min(1, dt * 3.2);
  RIDE_LINE = clamp(RIDE_LINE, lim[0], lim[1]);
}

/* ---- cinematic camera: a cut list keyed to arc length, not to wall-clock ---- */
const SHOTS = [
  { at: 0.00, kind: 'orbit',  r: 9,  h: 3.4, spin: 0.10 },
  { at: 0.06, kind: 'chase',  r: 7.5, h: 1.5, az: 0.0 },
  { at: 0.14, kind: 'side',   d: 11, h: 2.0 },
  { at: 0.22, kind: 'low',    r: 4.2, h: 0.55 },
  { at: 0.30, kind: 'ahead',  d: 16, h: 2.6 },
  { at: 0.40, kind: 'side',   d: 9,  h: 1.2 },
  { at: 0.48, kind: 'low',    r: 5.0, h: 0.5 },
  { at: 0.56, kind: 'orbit',  r: 8,  h: 2.4, spin: -0.14 },
  { at: 0.64, kind: 'chase',  r: 6.5, h: 1.9, az: 0.6 },
  { at: 0.72, kind: 'ahead',  d: 13, h: 1.8 },
  { at: 0.80, kind: 'side',   d: 14, h: 3.2 },
  { at: 0.90, kind: 'orbit',  r: 14, h: 6.0, spin: 0.06 }
];
const _cv = new THREE.Vector3(), _ct = new THREE.Vector3();
let shotIdx = -1, shotT = 0;
function cineCamera(dt){
  const f = scroll / COURSE_LEN;
  let idx = 0; for (let i = 0; i < SHOTS.length; i++) if (f >= SHOTS[i].at) idx = i;
  if (idx !== shotIdx){ shotIdx = idx; shotT = 0; }
  shotT += dt;
  const S = SHOTS[idx], P = pathAt(scroll), y = chassis.y;
  const fx = Math.cos(P.theta), fz = Math.sin(P.theta), rx = -fz, rz = fx;
  _ct.set(P.x, y + 0.6, P.z);
  if (S.kind === 'orbit'){
    const a = shotT * S.spin * Math.PI + P.theta + 2.2;
    _cv.set(P.x + Math.cos(a) * S.r, y + S.h, P.z + Math.sin(a) * S.r);
  } else if (S.kind === 'chase'){
    const a = (S.az || 0);
    _cv.set(P.x - (fx * Math.cos(a) - rx * Math.sin(a)) * S.r, y + S.h, P.z - (fz * Math.cos(a) - rz * Math.sin(a)) * S.r);
  } else if (S.kind === 'side'){
    const Q2 = pathAt(scroll + 6);
    _cv.set(Q2.x + rx * S.d, LOOP.terrainAt(scroll + 6) + S.h + 1.0, Q2.z + rz * S.d);
    _ct.set(P.x, y + 0.5, P.z);
  } else if (S.kind === 'low'){
    _cv.set(P.x - fx * S.r + rx * 1.1, LOOP.terrainAt(scroll - S.r) + S.h, P.z - fz * S.r + rz * 1.1);
    _ct.set(P.x, y + 0.75, P.z);
  } else {                                                                        // 'ahead': a static camera the rider comes at
    const Q2 = pathAt(scroll + S.d);
    _cv.set(Q2.x, LOOP.terrainAt(scroll + S.d) + S.h, Q2.z);
  }
  const k = shotT < 0.25 ? 1 : Math.min(1, dt * 3.4);                              // snap on the cut, then settle
  camPos.lerp(_cv, k); camLook.lerp(_ct, Math.min(1, dt * 6));
  camera.position.copy(camPos); camera.lookAt(camLook);
}

/* ---- free camera ---- */
const FLY = { pos: new THREE.Vector3(), yaw: 0, pitch: -0.2, speed: 18 };
let flyInit = false;
function flyCamera(dt){
  if (!flyInit){ FLY.pos.copy(camera.position); FLY.yaw = camAz; flyInit = true; }
  FLY.yaw = camAz; FLY.pitch = -camEl;
  const f = (KEY.KeyW || KEY.ArrowUp ? 1 : 0) - (KEY.KeyS || KEY.ArrowDown ? 1 : 0);
  const r = (KEY.KeyD || KEY.ArrowRight ? 1 : 0) - (KEY.KeyA || KEY.ArrowLeft ? 1 : 0);
  const u = (KEY.KeyE || KEY.Space ? 1 : 0) - (KEY.KeyQ ? 1 : 0);
  const sp = FLY.speed * (KEY.ShiftLeft ? 3.5 : 1) * dt;
  const cy = Math.cos(FLY.yaw), sy = Math.sin(FLY.yaw), cp = Math.cos(FLY.pitch);
  FLY.pos.x += (-sy * cp * f + cy * r) * sp;
  FLY.pos.z += (-cy * cp * f - sy * r) * sp;
  FLY.pos.y += (Math.sin(FLY.pitch) * f + u) * sp;
  camera.position.copy(FLY.pos);
  camLook.set(FLY.pos.x - sy * cp * 10, FLY.pos.y + Math.sin(FLY.pitch) * 10, FLY.pos.z - cy * cp * 10);
  camera.lookAt(camLook);
}

/* ---- controls ---- */
function segButtons(id, cb){
  const el = $(id); if (!el) return;
  el.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    el.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); cb(b.dataset.v);
  }));
}
segButtons('modeSeg', vv => {
  MODE = vv; snapCam = true; flyInit = false; shotIdx = -1;
  $('hint').textContent = vv === 'fly' ? 'W A S D to fly, Q / E for height, shift to sprint, drag to look'
    : vv === 'cine' ? 'the lap rides itself; the camera cuts by distance along the trail'
    : 'drag to look · hold the left half to brake, the right to pedal · A / D pick your line';
});
segButtons('riderSeg', vv => { riderMode = vv; M_RIDER = (vv === 'pro' ? 150 : 185) * 0.4536; applyTuning(); });
segButtons('qSeg', vv => { try { localStorage.setItem('loopQ', vv); } catch (e) {} location.search = '?q=' + vv; });
document.querySelectorAll('#qSeg button').forEach(b => b.classList.toggle('on', b.dataset.v === QNAME));

function togglePause(){ paused = !paused; riding = !paused; $('rideBtn').textContent = paused ? 'RIDE' : 'PAUSE'; }
function restart(){ reset(); RIDE_LINE = 0; airBest = 0; lastAir = 0; snapCam = true; shotIdx = -1; if (WORLD.tracks){ WORLD.tracks.count = 0; WORLD.tracks.head = 0; WORLD.tracks.lastS = -99; } }
$('rideBtn').addEventListener('click', togglePause);
$('restartBtn').addEventListener('click', restart);
addEventListener('resize', () => resizeRenderer());

/* ---- boot ---- */
applyTuning();
reset();
riding = false;                                                                   // the physics waits for the world

const load = $('load'), loadBar = $('loadBar'), loadWhat = $('loadWhat');
buildWorld(
  (f, label) => { loadBar.style.width = (f * 100).toFixed(0) + '%'; loadWhat.textContent = label; },
  () => {
    loadBar.style.width = '100%';
    load.style.display = 'none';
    riding = true; snapCam = true;
    console.log('world built in ' + window.WORLD_BUILD_MS.toFixed(0) + ' ms, tier ' + QNAME);
    requestAnimationFrame(tick);
  }
);

/* ---- the frame loop ---- */
let last = performance.now(), acc = 0, fps = 60;
function tick(now){
  requestAnimationFrame(tick);
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  frameMs = lerp(frameMs, dt * 1000, 0.08);

  if (MODE !== 'fly') readInput(dt);
  if (riding){
    acc += dt; let n = 0;
    while (acc >= Q.pdt && n < 90){ step(Q.pdt); acc -= Q.pdt; n++; }
    if (n >= 90) acc = 0;                                                         // a long stall must not become a spiral
    pushTrack(scroll - 0.6, RIDE_LINE);
  }
  pose(riding ? dt : 0);                                                          // pose() also drives the chase camera
  RIG_MERGE.update();                                                             // bake the posed parts into the one rig mesh
  if (MODE === 'cine') cineCamera(dt);
  else if (MODE === 'fly') flyCamera(dt);

  worldTick(now / 1000);
  hudT += dt;
  if (hudT > 0.1){ hudT = 0; updateHud(); drawMinimap(); }

  /* info.render resets on every renderer.render(), and a composer calls it once per pass — reading it afterwards
     reports the final fullscreen quad, not the scene. Reset once per frame instead and let the passes accumulate. */
  renderer.info.autoReset = false; renderer.info.reset();
  if (composer) composer.render(dt); else renderer.render(scene, camera);
  calls = renderer.info.render.calls;
  callsMax = Math.max(callsMax, calls); frameMax = Math.max(frameMax, dt * 1000);
}

window.LOOPSIM = {
  get v(){ return v; }, get scroll(){ return scroll; }, get state(){ return poseState; },
  get mode(){ return MODE; }, get line(){ return RIDE_LINE; },
  seg: () => segAt(scroll)[0].name, zone: () => segAt(scroll)[0].zone,
  /* Teleport to an arc length. reset() puts the rider at s = 0; shifting every height by the elevation
     difference puts him on the ground at s instead, rather than 70 m above it falling. For screenshots and
     for checking a single feature without riding the whole loop to it. */
  goto: (s, speed) => { reset(); const dy = LOOP.groundAt(s, 0) - LOOP.groundAt(0, 0);
    scroll = s; v = speed || 9; RIDE_LINE = 0;
    chassis.y += dy; wheelF.y += dy; wheelR.y += dy; rider.y += dy; snapCam = true; shotIdx = -1;
    airStart = -1; airBest = 0; lastAir = 0;
    return segAt(s)[0].name; },
  calls: () => calls, callsMax: () => callsMax, frameMs: () => frameMs, frameMax: () => frameMax,
  tris: () => renderer.info.render.triangles, times: () => WORLD.times,
  resetPeaks: () => { callsMax = 0; frameMax = 0; },
  buildMs: () => window.WORLD_BUILD_MS, wallMs: () => window.WORLD_WALL_MS, quality: QNAME,
  chassis, wheelF, wheelR, COURSE_LEN, PATH, LOOP
};
