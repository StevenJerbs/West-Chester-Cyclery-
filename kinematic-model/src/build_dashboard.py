"""Build the joint-angle dashboard HTML from one or more analysis.json runs.

Usage:
    python build_dashboard.py <analysis.json> [out.html]
    python build_dashboard.py --multi label1=a1.json label2=a2.json -o out.html

Single run: small multiples, one panel per joint, over its coaching
reference band. Multiple runs: the same panels become multi-series
overlays — one color per run/rider, a legend, shared reference bands —
plus a run-comparison table showing which joints and cues separate them.
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

# Validated categorical run colors (blue/orange, slots 1-2 of the reference
# palette) — all-pairs CVD + normal-vision + contrast checks pass in both
# light and dark. Color encodes run identity everywhere in the dashboard.
RUN_COLORS = [
    {"light": "#2a78d6", "dark": "#3987e5"},
    {"light": "#eb6834", "dark": "#d95926"},
    {"light": "#4a3aa7", "dark": "#9085e9"},
]


def _run_from_analysis(a: dict, label: str | None = None) -> dict:
    return {
        "label": label or Path(a.get("video", "run")).stem,
        "times": a["times"],
        "joints": a["joints"],
        "attack": a["attack_score"],
        "attack_mean": a.get("attack_score_mean"),
        "lookahead": a.get("gaze_lookahead_pct"),
    }


def build(analysis_path: str | Path, out_path: str | Path,
          compare_rows: list[dict] | None = None):
    """Single-run convenience wrapper around build_multi."""
    a = json.loads(Path(analysis_path).read_text())
    return build_multi([_run_from_analysis(a)], out_path, compare_rows)


def build_multi(runs: list[dict], out_path: str | Path,
                compare_rows: list[dict] | None = None):
    all_joint_keys = set()
    for r in runs:
        all_joint_keys |= set(r["joints"])
    panels = [[k, t, d] for k, t, d in PANELS if k in all_joint_keys]

    payload = json.dumps({
        "runs": [{"label": r["label"], "times": r["times"], "joints": r["joints"],
                  "attack": r["attack"]} for r in runs],
        "panels": panels,
        "compare": compare_rows or [],
        "colors": RUN_COLORS[:max(len(runs), 1)],
    }, separators=(",", ":"))

    n = len(runs)
    if n == 1:
        r = runs[0]
        attack_pct = round(100 * (r.get("attack_mean") or 0))
        look_pct = round(r.get("lookahead") or 0)
        headline = f"run {r['label']}"
        sub = ("Every major joint charted through the run, scored against the "
               "attack-position coaching envelopes, with the rider's vision "
               "path tracked from head orientation.")
    else:
        attack_pct = round(100 * sum((r.get("attack_mean") or 0) for r in runs) / n)
        look_pct = round(sum((r.get("lookahead") or 0) for r in runs) / n)
        headline = f"{n} runs compared"
        sub = ("Every major joint overlaid across runs, scored against the same "
               "attack-position envelopes, so the gap between riders shows up "
               "joint by joint instead of buried in an average.")

    joints_n = len(panels)
    cov = round(100 * max((s["coverage"] for r in runs for s in r["joints"].values()),
                          default=0))

    legend = "".join(
        f'<span class="lg-item"><span class="lg-sw" style="background:var(--r{i})"></span>{r["label"]}</span>'
        for i, r in enumerate(runs)) if n > 1 else ""

    html = HTML_TEMPLATE
    for key, val in {
        "__PAYLOAD__": payload,
        "__ATTACK__": str(attack_pct),
        "__LOOK__": str(look_pct),
        "__JOINTS_N__": str(joints_n),
        "__COV__": str(cov),
        "__HEADLINE__": headline,
        "__SUB__": sub,
        "__LEGEND__": legend,
        "__LEGEND_DISPLAY__": "flex" if n > 1 else "none",
        "__RUN_COLOR_VARS_LIGHT__": "".join(
            f"--r{i}:{c['light']};" for i, c in enumerate(RUN_COLORS[:max(n, 2)])),
        "__RUN_COLOR_VARS_DARK__": "".join(
            f"--r{i}:{c['dark']};" for i, c in enumerate(RUN_COLORS[:max(n, 2)])),
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
  --score:#eb6834;
  --band:rgba(11,11,11,.055); --grid:rgba(11,11,11,.08);
  --chip-ok:#e7f2e7; --chip-ok-ink:#1c5f1c;
  __RUN_COLOR_VARS_LIGHT__
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --surface:#1a1a19; --card:#222220; --line:#35342f;
    --ink:#ffffff; --ink-2:#c3c2b7; --ink-3:#8a897f;
    --score:#d95926;
    --band:rgba(255,255,255,.07); --grid:rgba(255,255,255,.09);
    --chip-ok:#1e3320; --chip-ok-ink:#8ed48e;
    __RUN_COLOR_VARS_DARK__
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --surface:#1a1a19; --card:#222220; --line:#35342f;
  --ink:#ffffff; --ink-2:#c3c2b7; --ink-3:#8a897f;
  --score:#d95926;
  --band:rgba(255,255,255,.07); --grid:rgba(255,255,255,.09);
  --chip-ok:#1e3320; --chip-ok-ink:#8ed48e;
  __RUN_COLOR_VARS_DARK__
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
.howto{color:var(--ink-2);font-size:13px;margin:10px 0 14px}
.howto .sw{display:inline-block;width:18px;height:3px;border-radius:2px;
  vertical-align:middle;margin:0 4px 2px 2px;background:var(--r0)}
.howto .bd{display:inline-block;width:18px;height:11px;border-radius:2px;
  background:var(--band);border:1px solid var(--line);
  vertical-align:middle;margin:0 4px 2px 2px}
.legend{display:__LEGEND_DISPLAY__;gap:16px;flex-wrap:wrap;margin:0 0 20px;
  font-size:13px;color:var(--ink-2)}
.lg-item{display:inline-flex;align-items:center;gap:6px}
.lg-sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:14px 14px 8px;position:relative}
.panel.wide{grid-column:1/-1}
.panel h3{font:600 20px/1.1 "Barlow Condensed",sans-serif;margin:0}
.panel .def{color:var(--ink-3);font-size:12px;margin:1px 0 2px}
.panel .cue{color:var(--ink-2);font-size:13px;font-style:italic;margin:0 0 6px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 4px}
.chip{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);
  color:var(--ink-2);font-variant-numeric:tabular-nums;display:inline-flex;
  align-items:center;gap:5px}
.chip .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.chip.ok{background:var(--chip-ok);color:var(--chip-ok-ink);border-color:transparent}
svg{display:block;width:100%;height:auto}
.gridline{stroke:var(--grid);stroke-width:1}
.axis-lbl{fill:var(--ink-3);font:11px Barlow,sans-serif}
.band{fill:var(--band)}
.ser{stroke-width:2;fill:none;stroke-linejoin:round}
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
  <p class="eyebrow">Downhill kinematic model · __HEADLINE__</p>
  <h1>Rider Kinematics Board</h1>
  <p class="sub">__SUB__</p>
</header>

<div class="tiles">
  <div class="tile"><div class="num">__ATTACK__%</div>
    <div class="lbl">time in attack position (visible joints inside envelope)</div></div>
  <div class="tile"><div class="num">__LOOK__%</div>
    <div class="lbl">vision path on the look-ahead cue</div></div>
  <div class="tile"><div class="num">__JOINTS_N__</div>
    <div class="lbl">joints tracked</div></div>
  <div class="tile"><div class="num">__COV__%</div>
    <div class="lbl">best joint coverage of frames</div></div>
</div>

<p class="howto"><span class="sw"></span>measured angle (smoothed, side-averaged) ·
<span class="bd"></span>coaching reference envelope · gaps are frames where the
joint wasn't confidently detected · hover any chart for values</p>
<div class="legend">__LEGEND__</div>

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
  norms. Camera angle (behind/above vs. pure side-on) skews absolute hip and
  torso readings between runs shot differently — treat cross-run deltas on
  those two with caution. Improvement tracking and good-vs-poor spreads
  sharpen as more labeled runs land in <code>data/riders.yaml</code>.</p>
</div>
</div>

<script>
const D = __PAYLOAD__;
const W=640, H=190, PL=42, PR=10, PT=12, PB=22;
const nRuns = D.runs.length;

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
function maxTime(){ return Math.max(...D.runs.map(r=>r.times[r.times.length-1])); }

// series: array of {label, times, values, color}; ref: {lo,hi,cue} or null
function drawPanel(host, title, def, series, ref, opts){
  opts = opts || {};
  const allVals = series.flatMap(s=>s.values);
  const [mn,mx] = extent(allVals, ref?ref.lo:Math.min(...allVals.filter(x=>x!=null)),
                                   ref?ref.hi:Math.max(...allVals.filter(x=>x!=null)));
  const tmax = maxTime();
  const X=t=>PL+(t/tmax)*(W-PL-PR);
  const Y=v=>PT+(mx-v)/(mx-mn)*(H-PT-PB);
  let g='';
  for(const tv of niceTicks(mn,mx,4))
    g+=`<line class="gridline" x1="${PL}" x2="${W-PR}" y1="${Y(tv)}" y2="${Y(tv)}"/>`+
       `<text class="axis-lbl" x="${PL-6}" y="${Y(tv)+4}" text-anchor="end">${tv}</text>`;
  for(let t=0;t<=tmax;t+=2)
    g+=`<text class="axis-lbl" x="${X(t)}" y="${H-6}" text-anchor="middle">${t}s</text>`;
  let band='';
  if(ref) band=`<rect class="band" x="${PL}" width="${W-PL-PR}"
    y="${Y(Math.min(ref.hi,mx))}" height="${Math.abs(Y(Math.max(ref.lo,mn))-Y(Math.min(ref.hi,mx)))}"/>`;
  let paths='';
  for(const s of series){
    let path='', pen=false;
    s.values.forEach((v,i)=>{ if(v==null){pen=false;return;}
      path+=(pen?'L':'M')+X(s.times[i]).toFixed(1)+' '+Y(v).toFixed(1); pen=true;});
    paths+=`<path class="ser ${opts.cls||''}" style="stroke:${s.color}" d="${path}"/>`;
  }
  const el=document.createElement('div');
  el.className='panel'+(opts.wide?' wide':'');
  const chips = opts.chips || series.map(s=>{
    const j = s.jointStat; if(!j) return '';
    return `<span class="chip ok"><span class="dot" style="background:${s.color}"></span>${j.in_form_pct}% in form</span>`+
      `<span class="chip">mean ${j.mean}${opts.unit||'°'}</span>`;
  }).join('');
  el.innerHTML=`<h3>${title}</h3><div class="def">${def}</div>
    ${opts.cue?`<p class="cue">“${opts.cue}”</p>`:''}
    <div class="chips">${chips}</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${title} over time">
      ${band}${g}${paths}
      <line class="xhair" y1="${PT}" y2="${H-PB}" x1="-9" x2="-9"/>
      <circle class="dotmark" r="4" cx="-9" cy="-9" style="stroke:${series[0]?.color||'var(--r0)'}"/>
    </svg><div class="tip"></div>`;
  host.appendChild(el);
  const svg=el.querySelector('svg'), tip=el.querySelector('.tip'),
        xh=el.querySelector('.xhair'), dot=el.querySelector('.dotmark');
  svg.addEventListener('mousemove',e=>{
    const r=svg.getBoundingClientRect();
    const t=((e.clientX-r.left)/r.width*W-PL)/(W-PL-PR)*tmax;
    // nearest point on the first series with data at this t
    let chosen=null;
    for(const s of series){
      let best=-1,bd=1e9;
      s.times.forEach((tt,i)=>{const d=Math.abs(tt-t); if(s.values[i]!=null&&d<bd){bd=d;best=i;}});
      if(best>=0 && (!chosen || bd<chosen.bd)) chosen={s,i:best,bd};
    }
    if(!chosen) return;
    const v=chosen.s.values[chosen.i], tt=chosen.s.times[chosen.i];
    xh.setAttribute('x1',X(tt)); xh.setAttribute('x2',X(tt));
    dot.setAttribute('cx',X(tt)); dot.setAttribute('cy',Y(v));
    dot.setAttribute('style',`stroke:${chosen.s.color}`);
    tip.style.display='block';
    tip.style.left=Math.min(e.clientX-r.left+14, r.width-150)+'px';
    tip.style.top=(e.clientY-r.top-34)+'px';
    tip.textContent=`${nRuns>1?chosen.s.label+' · ':''}${tt.toFixed(2)}s — ${v.toFixed(1)}${opts.unit||'°'}`;
  });
  svg.addEventListener('mouseleave',()=>{tip.style.display='none';
    xh.setAttribute('x1',-9);xh.setAttribute('x2',-9);
    dot.setAttribute('cx',-9);dot.setAttribute('cy',-9);});
}

const grid=document.getElementById('grid');
for(const [key,title,def] of D.panels){
  let ref=null, cue='';
  const series=[];
  D.runs.forEach((r,i)=>{
    const j=r.joints[key]; if(!j) return;
    ref = j.ref; cue = j.ref.cue;
    series.push({label:r.label, times:r.times, values:j.values,
                color:`var(--r${i})`, jointStat:j});
  });
  if(series.length) drawPanel(grid, title, def, series, ref, {cue});
}
{
  let ref=null, cue='';
  const series=[];
  D.runs.forEach((r,i)=>{
    const j=r.joints.gaze_angle; if(!j) return;
    ref=j.ref; cue=j.ref.cue;
    series.push({label:r.label, times:r.times, values:j.values,
                color:`var(--r${i})`, jointStat:j});
  });
  if(series.length) drawPanel(grid,'Vision path',
    'ear-to-nose sightline vs horizontal; positive = looking down',
    series, ref, {cue, wide:true,
      chips: series.map(s=>`<span class="chip ok"><span class="dot" style="background:${s.color}"></span>${s.jointStat.in_form_pct}% on the look-ahead cue</span>`).join('')});
}
{
  const series = D.runs.map((r,i)=>({label:r.label, times:r.times,
    values:r.attack.map(v=>v==null?null:v*100), color:`var(--r${i})`}));
  drawPanel(grid,'Attack-position score',
    'share of visible joints inside their envelope, per frame',
    series, null, {cls:'score', wide:true, unit:'%',
      chips: series.map(s=>`<span class="chip"><span class="dot" style="background:${s.color}"></span>${s.label}</span>`).join('')});
}

const cmp=document.getElementById('cmp');
if(D.compare.length){
  const cols=['run','attack_score','lookahead_pct','knee_angle_mean','hip_angle_mean','elbow_angle_mean','neck_angle_mean'];
  const names=['Run','Attack score','Look-ahead %','Knee mean°','Hip mean°','Elbow mean°','Neck mean°'];
  cmp.innerHTML='<tr>'+names.map(n=>`<th>${n}</th>`).join('')+'</tr>'+
    D.compare.map(r=>'<tr>'+cols.map(c=>`<td>${r[c]??'—'}</td>`).join('')+'</tr>').join('');
  document.getElementById('cmpnote').textContent =
    D.compare.length<2 ? 'One run analyzed so far. Label runs good or poor in data/riders.yaml and re-run the pipeline; this table then shows which joints and cues separate the fast riders from the rest.' : 'Sorted by attack-position score. Label runs good/poor in data/riders.yaml to turn this into a real fast-vs-slow contrast.';
}
</script>
"""


if __name__ == "__main__":
    from joint_analysis import compare

    args = sys.argv[1:]
    if args and args[0] == "--multi":
        pairs, out = [], "dashboard.html"
        i = 1
        while i < len(args):
            if args[i] == "-o":
                out = args[i + 1]; i += 2; continue
            label, path = args[i].split("=", 1)
            pairs.append((label, path))
            i += 1
        runs = [_run_from_analysis(json.loads(Path(p).read_text()), label)
                for label, p in pairs]
        rows = compare({r["label"]: {"attack_score_mean": r["attack_mean"],
                                     "gaze_lookahead_pct": r["lookahead"],
                                     "joints": r["joints"]} for r in runs})
        print("wrote", build_multi(runs, out, rows))
    else:
        src = args[0]
        dst = args[1] if len(args) > 1 else str(Path(src).parent / "dashboard.html")
        a = json.loads(Path(src).read_text())
        rows = compare({Path(a.get("video", "run")).stem + " [unlabeled]": a})
        print("wrote", build(src, dst, rows))
