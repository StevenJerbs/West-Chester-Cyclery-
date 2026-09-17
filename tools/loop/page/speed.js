/* ---- speed you can feel: the camera, the frame edges, and the sound ----
   Three things a chase camera on a fixed lens never gives you. The lens widens with speed and the camera drops toward
   the ground, so the trail streams past; the edges of the frame streak; and the trackside recording from the Pump Lab
   plays underneath, driven by the same physics: the tyre roar rises with speed and brightens with the suspension's
   work, the freehub buzzes when the rider stops pedalling, the wind takes over in the air, and every landing and
   bottom-out is a hit scaled by how hard it was. Sound is off until the SOUND button is pressed (browsers require it). */

/* -- camera: field of view and height follow speed, with a little shake through the rough -- */
const SPEED_FX = { fov: 46, streak: 0, shake: 0 };
const streakCv = document.createElement('canvas'); streakCv.className = 'streaks'; stage.appendChild(streakCv);
const streakCx = streakCv.getContext('2d');
function speedTick(dt){
  const sp = clamp((v - 4) / 13, 0, 1);                                            // 0 at 9 mph, 1 at 38 mph
  const air = poseState === 'air';
  const fovT = 46 + 24 * sp * sp + (air ? 4 : 0);
  SPEED_FX.fov += (fovT - SPEED_FX.fov) * Math.min(1, dt * 3);
  if (MODE === 'ride' && Math.abs(camera.fov - SPEED_FX.fov) > 0.05){ camera.fov = SPEED_FX.fov; camera.updateProjectionMatrix(); }
  /* the rough: fork velocity shakes the camera a touch; in the air it goes still */
  const rough = air ? 0 : Math.min(1, Math.abs(wheelF.sv) / 2.5) * sp;
  SPEED_FX.shake += (rough - SPEED_FX.shake) * Math.min(1, dt * 8);
  if (MODE === 'ride' && SPEED_FX.shake > 0.01){ const a = SPEED_FX.shake * 0.05; camera.position.x += (Math.random() - 0.5) * a; camera.position.y += (Math.random() - 0.5) * a; }
  /* the streaks: radial lines from the centre, only at speed, denser in the air */
  const want = sp > 0.35 ? (sp - 0.35) / 0.65 * (air ? 1.0 : 0.7) : 0;
  SPEED_FX.streak += (want - SPEED_FX.streak) * Math.min(1, dt * 4);
  const W = streakCv.width = canvas.clientWidth || 1280, H = streakCv.height = canvas.clientHeight || 600;
  streakCx.clearRect(0, 0, W, H);
  if (SPEED_FX.streak > 0.02 && MODE !== 'fly'){
    const n = Math.round(10 + 70 * SPEED_FX.streak), cx = W * 0.5, cy = H * 0.46;
    streakCx.strokeStyle = 'rgba(255,248,230,' + (0.05 + 0.20 * SPEED_FX.streak).toFixed(3) + ')';
    streakCx.lineWidth = 1.2;
    const t = performance.now() * 0.002;
    for (let i = 0; i < n; i++){
      const a = (i / n) * Math.PI * 2 + Math.sin(i * 12.9898 + t) * 0.03;
      const r0 = Math.min(W, H) * (0.34 + 0.16 * hash01(i * 7.13 + Math.floor(t * 6))), r1 = r0 + Math.min(W, H) * (0.10 + 0.35 * SPEED_FX.streak);
      streakCx.beginPath(); streakCx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0); streakCx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); streakCx.stroke();
    }
  }
}
function hash01(x){ const s = Math.sin(x) * 43758.5453; return s - Math.floor(s); }

/* -- sound: the Pump Lab's engine, on this physics -- */
const SFX = (() => {
  let ctx = null, master = null, on = false, ready = false, booting = false, vc = null;
  const buf = {};
  const clamp01 = x => Math.max(0, Math.min(1, x));
  const bytes = uri => { const b = atob(uri.slice(uri.indexOf(',') + 1)); const a = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) a[i] = b.charCodeAt(i); return a.buffer; };
  const set = (param, val, tc) => param.setTargetAtTime(val, ctx.currentTime, tc || 0.05);
  function chain(src, cutoff, gain){
    const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = cutoff;
    const g = ctx.createGain(); g.gain.value = gain; src.connect(f); f.connect(g); g.connect(master); return { src, f, g };
  }
  function loop(name, cutoff){ const src = ctx.createBufferSource(); src.buffer = buf[name]; src.loop = true; const c = chain(src, cutoff, 0); src.start(); return c; }
  function shot(name, gain, rate, cutoff){
    if (!ready || gain <= 0.001) return;
    const src = ctx.createBufferSource(); src.buffer = buf[name]; src.playbackRate.value = rate;
    const c = chain(src, cutoff, gain); src.onended = () => { c.g.disconnect(); }; src.start();
  }
  async function boot(){
    booting = true;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const comp = ctx.createDynamicsCompressor(); comp.threshold.value = -14; comp.ratio.value = 4;
    master = ctx.createGain(); master.gain.value = 0; master.connect(comp); comp.connect(ctx.destination);
    await Promise.all(Object.keys(SFX_DATA).map(n => new Promise((res, rej) => ctx.decodeAudioData(bytes(SFX_DATA[n]), b => { buf[n] = b; res(); }, rej))));
    const amb = loop('amb', 8000); amb.g.gain.value = LOOP.biome === 'desert' ? 0.22 : 0.45;
    vc = { roll: loop('roll', 3000), rough: loop('rough', 4000), buzz: loop('buzz', 4200), wind: loop('wind', 6000), roughT: 0, cool: 0, lastU: 0 };
    ready = true; booting = false;
  }
  function update(dt){
    if (!on || !ready) return;
    const air = poseState === 'air', ground = !air && riding && crashed <= 0;
    const sp = clamp01((v - 1.5) / 14), work = Math.min(1, Math.abs(wheelF.sv) / 1.6);
    set(vc.roll.g.gain, ground ? 0.12 + 0.62 * Math.pow(sp, 0.8) : 0, 0.06);
    set(vc.roll.f.frequency, 900 + 3600 * sp + 2500 * work, 0.08);
    set(vc.roll.src.playbackRate, 0.72 + 0.55 * sp, 0.1);
    vc.roughT = Math.max(0, vc.roughT - dt);
    set(vc.rough.g.gain, ground ? (0.55 * work + (vc.roughT > 0 ? 0.5 : 0)) * (0.3 + 0.7 * sp) : 0, 0.05);
    set(vc.rough.src.playbackRate, 0.8 + 0.4 * sp, 0.1);
    set(vc.buzz.g.gain, ground && !pedaling ? 0.11 * clamp01(v / 6) * (0.55 + 0.45 * sp) : 0, 0.04);
    set(vc.buzz.src.playbackRate, Math.max(0.3, v / 7.5), 0.06);
    const w = clamp01(v / 16), wg = (air ? 0.7 : 0.16) * w * w * (riding ? 1 : 0);
    set(vc.wind.g.gain, wg, 0.08); set(vc.wind.src.playbackRate, 0.8 + 0.5 * w, 0.1);
    /* bottom-outs: the bumper */
    const bo = (wheelF.s > GEO.forkTravel - 0.004) || (wheelR.t > GEO.travelR - 0.004);
    if (bo && vc.cool <= 0){ shot('hit3', 0.5, 1.35, 7000); vc.cool = 0.4; }
    vc.cool = Math.max(0, vc.cool - dt);
  }
  function event(e){
    if (!on || !ready) return;
    if (e.type === 'takeoff') shot('whoosh', 0.22 * clamp01(e.v / 9), 0.9 + 0.3 * clamp01(e.v / 14), 5000);
    else if (e.type === 'land' || e.type === 'crash'){
      const hard = clamp01(e.vImpact / 6);
      shot(['hit1', 'hit2', 'hit3', 'hit4'][Math.floor(Math.random() * 4)], 0.35 + 0.65 * hard, 0.9 + 0.2 * Math.random(), 2500 + 5000 * hard);
      vc.roughT = 0.25 + 0.3 * hard;
      if (e.type === 'crash') shot('hit1', 0.9, 0.7, 2000);
    }
  }
  function setOn(val){
    on = val; try { localStorage.setItem('loop.sound', on ? '1' : '0'); } catch (e) {}
    if (on){ if (!ctx && !booting) boot().then(() => set(master.gain, 0.9, 0.2)); else if (ctx){ ctx.resume(); set(master.gain, 0.9, 0.2); } }
    else if (ctx) set(master.gain, 0, 0.15);
  }
  return { update, event, setOn, get on(){ return on; }, get ready(){ return ready; } };
})();
const sfxBtn = $('sfxBtn');
sfxBtn.addEventListener('click', () => { SFX.setOn(!SFX.on); sfxBtn.textContent = 'SOUND · ' + (SFX.on ? 'ON' : 'OFF'); });
