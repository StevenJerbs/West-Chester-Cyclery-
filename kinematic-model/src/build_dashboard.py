"""Build the joint-angle dashboard HTML from analysis.json.

Usage: python build_dashboard.py <analysis.json> <out.html>
Charts are small multiples — one panel per joint, a single smoothed series
over its coaching reference band — plus full-width vision-path and
attack-position strips and a run-comparison table.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PANELS = [
    ("neck_angle", "Neck", "nose–shoulder–hip"),
    ("shoulder_angle", "Shoulders", "elbow–shoulder–hip"),
    ("elbow_angle", "Elbows", "shoulder–elbow–wrist"),
    ("wrist_angle", "Wrists", "forearm slope (no hand keypoint)"),
    ("hip_angle", "Hips", "shoulder–hip–knee"),
    ("knee_angle", "Knees", "hip–knee–ankle"),
    ("ankle_angle", "Ankles", "shank vs vertical (no toe keypoint)"),
    ("torso_angle", "Torso", "hip–shoulder line vs horizontal"),
]


def build(analysis_path: str | Path, out_path: str | Path,
          compare_rows: list[dict] | None = None):
    a = json.loads(Path(analysis_path).read_text())
    payload = json.dumps({
        "times": a["times"],
        "joints": a["joints"],
        "attack": a["attack_score"],
        "panels": [[k, t, d] for k, t, d in PANELS if k in a["joints"]],
        "compare": compare_rows or [],
    }, separators=(",", ":"))

    attack_pct = round(100 * (a.get("attack_score_mean") or 0))
    look_pct = a.get("gaze_lookahead_pct") or 0
    joints_n = len([1 for k, *_ in PANELS if k in a["joints"]])
    cov = round(100 * max((s["coverage"] for s in a["joints"].values()), default=0))

    html = HTML_TEMPLATE
    for key, val in {
        "__PAYLOAD__": payload,
        "__ATTACK__": str(attack_pct),
        "__LOOK__": str(round(look_pct)),
        "__JOINTS_N__": str(joints_n),
        "__COV__": str(cov),
        "__VIDEO__": Path(a.get("video", "run")).stem,
    }.items():
        html = html.replace(key, val)
    Path(out_path).write_text(html)
    return out_path


HTML_TEMPLATE = r"""<title>Rider Kinematics Board</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Barlow:wght@400;500;600&display=swap">
<style>
:root{
  color-scheme:light;
  --surface:#fcfcfb; --card:#ffffff; --line:#e4e2dc;
  --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#8a8880;
  --series:#2a78d6; --vision:#4a3aa7; --score:#eb6834;
  --band:rgba(11,11,11,.055); --grid:rgba(11,11,11,.08);
  --chip-ok:#e7f2e7; --chip-ok-ink:#1c5f1c;
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --surface:#1a1a19; --card:#222220; --line:#35342f;
    --ink:#ffffff; --ink-2:#c3c2b7; --ink-3:#8a897f;
    --series:#3987e5; --vision:#9085e9; --score:#d95926;
    --band:rgba(255,255,255,.07); --grid:rgba(255,255,255,.09);
    --chip-ok:#1e3320; --chip-ok-ink:#8ed48e;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --surface:#1a1a19; --card:#222220; --line:#35342f;
  --ink:#ffffff; --ink-2:#c3c2b7; --ink-3:#8a897f;
  --series:#3987e5; --vision:#9085e9; --score:#d95926;
  --band:rgba(255,255,255,.07); --grid:rgba(255,255,255,.09);
  --chip-ok:#1e3320; --chip-ok-ink:#8ed48e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--ink);
  font:400 15px/1.55 Barlow,system-ui,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:28px 20px 60px}
header h1{font:700 40px/1.05 "Barlow Condensed",system-ui,sans-serif;
  margin:0;letter-spacing:.01em;text-wrap:balance}
header .sub{color:var(--ink-2);margin:6px 0 0;max-width:65ch}
.eyebrow{font:600 12px/1 "Barlow Condensed",sans-serif;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:12px;margin:26px 0 8px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:14px 16px}
.tile .num{font:600 34px/1 "Barlow Condensed",sans-serif;
  font-variant-numeric:tabular-nums}
.tile .lbl{color:var(--ink-2);font-size:13px;margin-top:4px}
.howto{color:var(--ink-2);font-size:13px;margin:10px 0 22px}
.howto .sw{display:inline-block;width:18px;height:3px;border-radius:2px;
  vertical-align:middle;margin:0 4px 2px 2px}
.howto .bd{display:inline-block;width:18px;height:11px;border-radius:2px;
  background:var(--band);border:1px solid var(--line);
  vertical-align:middle;margin:0 4px 2px 2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:14px 14px 8px;position:relative}
.panel.wide{grid-column:1/-1}
.panel h3{font:600 20px/1.1 "Barlow Condensed",sans-serif;margin:0}
.panel .def{color:var(--ink-3);font-size:12px;margin:1px 0 2px}
.panel .cue{color:var(--ink-2);font-size:13px;font-style:italic;margin:0 0 6px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 4px}
.chip{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);
  color:var(--ink-2);font-variant-numeric:tabular-nums}
.chip.ok{background:var(--chip-ok);color:var(--chip-ok-ink);border-color:transparent}
svg{display:block;width:100%;height:auto}
.gridline{stroke:var(--grid);stroke-width:1}
.axis-lbl{fill:var(--ink-3);font:11px Barlow,sans-serif}
.band{fill:var(--band)}
.ser{stroke:var(--series);stroke-width:2;fill:none;stroke-linejoin:round}
.ser.vision{stroke:var(--vision)}
.ser.score{stroke:var(--score)}
.xhair{stroke:var(--ink-3);stroke-width:1;stroke-dasharray:3 3}
.dotmark{fill:var(--card);stroke-width:2}
.tip{position:absolute;pointer-events:none;background:var(--card);
  border:1px solid var(--line);border-radius:6px;padding:5px 9px;font-size:12px;
  color:var(--ink);box-shadow:0 2px 8px rgba(0,0,0,.12);white-space:nowrap;
  font-variant-numeric:tabular-nums;display:none;z-index:3}
.section{margin-top:34px}
table{border-collapse:collapse;width:100%;background:var(--card);
  border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:14px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums}
th{font:600 13px/1 "Barlow Condensed",sans-serif;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-2)}
tr:last-child td{border-bottom:none}
.note{color:var(--ink-2);font-size:13px;max-width:75ch}
.tablewrap{overflow-x:auto}
@media (prefers-reduced-motion: no-preference){
  .panel{transition:border-color .15s}
  .panel:hover{border-color:var(--ink-3)}
}
</style>
<div class="wrap">
<header>
  <p class="eyebrow">Downhill kinematic model · run __VIDEO__</p>
  <h1>Rider Kinematics Board</h1>
  <p class="sub">Every major joint charted through the run, scored against the
  attack-position coaching envelopes, with the rider's vision path tracked
  from head orientation.</p>
</header>

<div class="tiles">
  <div class="tile"><div class="num">__ATTACK__%</div>
    <div class="lbl">time in attack position (visible joints inside envelope)</div></div>
  <div class="tile"><div class="num">__LOOK__%</div>
    <div class="lbl">vision path on the look-ahead cue</div></div>
  <div class="tile"><div class="num">__JOINTS_N__</div>
    <div class="lbl">joints tracked this run</div></div>
  <div class="tile"><div class="num">__COV__%</div>
    <div class="lbl">best joint coverage of frames</div></div>
</div>

<p class="howto"><span class="sw" style="background:var(--series)"></span>measured
angle (smoothed, side-averaged) · <span class="bd"></span>coaching reference
envelope · gaps are frames where the joint wasn't confidently detected ·
hover any chart for values</p>

<div class="grid" id="grid"></div>

<div class="section">
  <p class="eyebrow">Run comparison · good vs poor</p>
  <div class="tablewrap"><table id="cmp"></table></div>
  <p class="note" id="cmpnote"></p>
</div>

<div class="section">
  <p class="eyebrow">Method &amp; caveats</p>
  <p class="note">Angles are 2D side-view estimates from the YOLOv8-pose
  skeleton, left/right side-averaged; wrist and ankle are segment
  inclinations because COCO has no hand or toe keypoints. The vision path is
  the ear-to-nose sightline — head orientation, a proxy for gaze. Envelopes
  are broad coaching ranges for the descending attack position, not medical
  norms. Improvement tracking and good-vs-poor spreads populate as more
  labeled runs land in <code>data/riders.yaml</code>.</p>
</div>
</div>

<script>
const D = __PAYLOAD__;
const W=640, H=190, PL=42, PR=10, PT=12, PB=22;

function extent(vals, lo, hi){
  const v = vals.filter(x=>x!=null);
  let mn = Math.min(...v, lo), mx = Math.max(...v, hi);
  const pad = (mx-mn)*0.08 || 5; return [mn-pad, mx+pad];
}
function niceTicks(mn, mx, n){
  const span=(mx-mn)/n, mag=Math.pow(10,Math.floor(Math.log10(span)));
  const step=[1,2,5,10].map(m=>m*mag).find(s=>span<=s)||10*mag;
  const t=[]; for(let v=Math.ceil(mn/step)*step; v<=mx; v+=step) t.push(v);
  return t;
}
function drawPanel(host, key, title, def, cfg){
  const s = cfg.series, ref = cfg.ref;
  const [mn,mx] = extent(s, ref?ref.lo:Math.min(...s.filter(x=>x!=null)),
                            ref?ref.hi:Math.max(...s.filter(x=>x!=null)));
  const X=t=>PL+(t-D.times[0])/(D.times[D.times.length-1]-D.times[0])*(W-PL-PR);
  const Y=v=>PT+(mx-v)/(mx-mn)*(H-PT-PB);
  let g='';
  for(const tv of niceTicks(mn,mx,4))
    g+=`<line class="gridline" x1="${PL}" x2="${W-PR}" y1="${Y(tv)}" y2="${Y(tv)}"/>`+
       `<text class="axis-lbl" x="${PL-6}" y="${Y(tv)+4}" text-anchor="end">${tv}</text>`;
  for(let t=0;t<=D.times[D.times.length-1];t+=2)
    g+=`<text class="axis-lbl" x="${X(t)}" y="${H-6}" text-anchor="middle">${t}s</text>`;
  let band='';
  if(ref) band=`<rect class="band" x="${PL}" width="${W-PL-PR}"
    y="${Y(Math.min(ref.hi,mx))}" height="${Math.abs(Y(Math.max(ref.lo,mn))-Y(Math.min(ref.hi,mx)))}"/>`;
  let path='', pen=false;
  s.forEach((v,i)=>{ if(v==null){pen=false;return;}
    path+=(pen?'L':'M')+X(D.times[i]).toFixed(1)+' '+Y(v).toFixed(1); pen=true;});
  const el=document.createElement('div');
  el.className='panel'+(cfg.wide?' wide':'');
  el.innerHTML=`<h3>${title}</h3><div class="def">${def}</div>
    ${cfg.cue?`<p class="cue">“${cfg.cue}”</p>`:''}
    ${cfg.chips||''}
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${title} over time">
      ${band}${g}<path class="ser ${cfg.cls||''}" d="${path}"/>
      <line class="xhair" y1="${PT}" y2="${H-PB}" x1="-9" x2="-9"/>
      <circle class="dotmark" r="4" cx="-9" cy="-9" style="stroke:var(--${cfg.tok||'series'})"/>
    </svg><div class="tip"></div>`;
  host.appendChild(el);
  const svg=el.querySelector('svg'), tip=el.querySelector('.tip'),
        xh=el.querySelector('.xhair'), dot=el.querySelector('.dotmark');
  svg.addEventListener('mousemove',e=>{
    const r=svg.getBoundingClientRect();
    const t=D.times[0]+((e.clientX-r.left)/r.width*W-PL)/(W-PL-PR)*(D.times[D.times.length-1]-D.times[0]);
    let best=0,bd=1e9;
    D.times.forEach((tt,i)=>{const d=Math.abs(tt-t); if(s[i]!=null&&d<bd){bd=d;best=i;}});
    const v=s[best]; if(v==null) return;
    xh.setAttribute('x1',X(D.times[best])); xh.setAttribute('x2',X(D.times[best]));
    dot.setAttribute('cx',X(D.times[best])); dot.setAttribute('cy',Y(v));
    tip.style.display='block';
    tip.style.left=Math.min(e.clientX-r.left+14, r.width-130)+'px';
    tip.style.top=(e.clientY-r.top-34)+'px';
    tip.textContent=`${D.times[best].toFixed(2)}s — ${v.toFixed(1)}${cfg.unit||'°'}`;
  });
  svg.addEventListener('mouseleave',()=>{tip.style.display='none';
    xh.setAttribute('x1',-9);xh.setAttribute('x2',-9);
    dot.setAttribute('cx',-9);dot.setAttribute('cy',-9);});
}
const grid=document.getElementById('grid');
for(const [key,title,def] of D.panels){
  const j=D.joints[key];
  const chips=`<div class="chips">
    <span class="chip ok">${j.in_form_pct}% in form</span>
    <span class="chip">mean ${j.mean}°</span>
    <span class="chip">range of motion ${j.rom}°</span>
    <span class="chip">${Math.round(j.coverage*100)}% of frames</span></div>`;
  drawPanel(grid, key, title, def, {series:j.values, ref:j.ref, cue:j.ref.cue, chips});
}
if(D.joints.gaze_angle){
  const j=D.joints.gaze_angle;
  drawPanel(grid,'gaze','Vision path','ear-to-nose sightline vs horizontal; positive = looking down',
    {series:j.values, ref:j.ref, cue:j.ref.cue, cls:'vision', tok:'vision', wide:true,
     chips:`<div class="chips"><span class="chip ok">${j.in_form_pct}% on the look-ahead cue</span>
       <span class="chip">mean ${j.mean}°</span>
       <span class="chip">${Math.round(j.coverage*100)}% of frames</span></div>`});
}
drawPanel(grid,'attack','Attack-position score','share of visible joints inside their envelope, per frame',
  {series:D.attack.map(v=>v==null?null:v*100), ref:null, cls:'score', tok:'score',
   wide:true, unit:'%'});

const cmp=document.getElementById('cmp');
if(D.compare.length){
  const cols=['run','attack_score','lookahead_pct','knee_angle_mean','hip_angle_mean','elbow_angle_mean','neck_angle_mean'];
  const names=['Run','Attack score','Look-ahead %','Knee mean°','Hip mean°','Elbow mean°','Neck mean°'];
  cmp.innerHTML='<tr>'+names.map(n=>`<th>${n}</th>`).join('')+'</tr>'+
    D.compare.map(r=>'<tr>'+cols.map(c=>`<td>${r[c]??'—'}</td>`).join('')+'</tr>').join('');
  document.getElementById('cmpnote').textContent =
    D.compare.length<2 ? 'One run analyzed so far. Label runs good or poor in data/riders.yaml and re-run the pipeline; this table then shows which joints and cues separate the fast riders from the rest.' : '';
}
</script>
"""


if __name__ == "__main__":
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else str(Path(src).parent / "dashboard.html")
    a = json.loads(Path(src).read_text())
    from joint_analysis import compare
    rows = compare({Path(a.get("video", "run")).stem + " [unlabeled]": a})
    print("wrote", build(src, dst, rows))
