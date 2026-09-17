/* The setup the physics reads. suspension-lab.html drives its solver from slider elements; rather than fork the
   solver, give it the same shape backed by plain values, so the physics below is byte-identical to the lab's. */
const $ = id => document.getElementById(id);
/* The bike: the Starling Murmur, the full-suspension bike the mtbkin keypoint model tracks most tightly. The lab's
   physics reads BIKE before it builds its geometry and linkage table; RIG_STYLE swaps the full-face for a half shell. */
const BIKE = COURSE_ID === 'rampage' ? 'v10' : 'murmur', RIG_STYLE = COURSE_ID === 'rampage' ? 'dh' : 'enduro';   // Rampage: the V10 and a full-face
/* tricks: the page writes these every frame, the physics reads them (suspension-lab.html: tricks) */
const TRICK = { flip: 0, tuck: 0, hands: 1, grab: 0, onEvent: null };
/* Set up firm for a 140 mm bike on a DH-scale course, found by sweeping the rideability gate: 450 lb/in on the TTX
   coil with the rebound slowed (10 / 6 clicks) so the rear does not kick the bike nose-up off the big rollers, and
   92 psi with three tokens in the 150 mm fork for the jump line. Softer bottoms out in the Gallery; stiffer (500)
   kicks the pro rider into a loop-out on Cedar Speedway; slower rebound packs down. */
const SETUP = COURSE_ID === 'rampage'
  ? { rlb: 150, effort: 300, vcap: 34, rSpring: 475, rLsc: 8, rHsc: 4, rLsr: 8, rHsr: 4, fSpring: 72, fVol: 3, fLsc: 5, fHsc: 3, fLsr: 6, fHsr: 4 }   // the V10 on its lab setup, freeride speed cap
  : { rlb: 150, effort: 300, vcap: 30, rSpring: 450, rLsc: 7, rHsc: 5, rLsr: 10, rHsr: 6, fSpring: 92, fVol: 3, fLsc: 5, fHsc: 3, fLsr: 6, fHsr: 4 };
const ui = new Proxy({}, { get: (t, k) => t[k] || (t[k] = { value: SETUP[k] !== undefined ? SETUP[k] : 0, textContent: '', style: {} }) });

/* quality tiers. The physics step is 1/600 s on every tier: at 1/300 the Murmur's lighter wheels on the firm setup
   put the tyre spring past what the integrator holds and the bike pitched over in its first metre. The step is cheap;
   the frame loop caps substeps at 90.
   The bake carries the sun's shadows, so switching shadow maps off on mobile costs almost nothing
   visually and is the single biggest win — a 2048 PCF-soft map is most of the frame on a phone. */
const IS_TOUCH = (navigator.maxTouchPoints || 0) > 0 || /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
const QUALITY = {
  low:  { dpr: 1.4, scale: 0.82, aa: false, shadow: 0,    ssao: false, bloom: 0,    smaa: false, fog: 0.0062, draw: 120, flora: 0.5,  leaves: 150, reflect: false, pdt: 1 / 600, sun: 0.78, hemi: 0.40, exp: 0.92, chunks: 6, ambient: true },
  med:  { dpr: 1.7, scale: 1.0,  aa: true,  shadow: 1024, ssao: false, bloom: 0.08, smaa: false, fog: 0.0048, draw: 210, flora: 0.78, leaves: 300, reflect: true,  pdt: 1 / 600, sun: 0.92, hemi: 0.50, exp: 1.00, chunks: 9, ambient: true },
  high: { dpr: 2.0, scale: 1.0,  aa: true,  shadow: 2048, ssao: true,  bloom: 0.11, smaa: true,  fog: 0.0037, draw: 270, flora: 1.0,  leaves: 450, reflect: true,  pdt: 1 / 600, sun: 1.05, hemi: 0.62, exp: 1.06, chunks: 12, ambient: false }
};
const qParam = new URLSearchParams(location.search).get('q');
if (COURSE_ID === 'rampage'){ QUALITY.low.leaves = 0; QUALITY.med.leaves = 0; QUALITY.high.leaves = 0; }   // no leaves blow through a desert
let QNAME = qParam && QUALITY[qParam] ? qParam : (IS_TOUCH ? 'low' : 'high');
let Q = QUALITY[QNAME];
const DEBUG = new URLSearchParams(location.search).has('debug');
