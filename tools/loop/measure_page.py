"""The runtime gate: load trail-loop.html headlessly in the installed Chrome and read what the page reports.

    python tools/loop/measure_page.py [low|med|high] [screenshot-dir]

Teleports to a handful of features (LOOPSIM.goto), lets the loop run ~2 s at each, and prints draw calls, peak
draw calls, triangles and world build time. With a directory given, saves a screenshot at each stop.
"""
import json, pathlib, sys
from playwright.sync_api import sync_playwright

PAGE = pathlib.Path(__file__).resolve().parents[2] / 'trail-loop.html'
tier = sys.argv[1] if len(sys.argv) > 1 else 'low'
shots = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != '-' else None
course = sys.argv[3] if len(sys.argv) > 3 else 'loop'
if shots: shots.mkdir(parents=True, exist_ok=True)
SPOTS = [0, 150, 420, 700, 1000, 1400] if course == 'loop' else [0, 60, 130, 200, 290, 340]

with sync_playwright() as p:
    b = p.chromium.launch(channel='chrome', headless=True,
                          args=['--use-gl=angle', '--use-angle=d3d11', '--ignore-gpu-blocklist', '--enable-webgl'])
    pg = b.new_page(viewport={'width': 1280, 'height': 720})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.goto(PAGE.as_uri() + '?q=' + tier + '&course=' + course)
    pg.wait_for_function('window.WORLD_BUILD_MS !== undefined && window.LOOPSIM', timeout=180000)
    pg.wait_for_timeout(1500)
    rows = []
    for s in SPOTS:
        name = pg.evaluate('LOOPSIM.goto(%d, 9)' % s)
        pg.evaluate('LOOPSIM.resetPeaks()')
        pg.wait_for_timeout(2000)
        r = pg.evaluate('({calls: LOOPSIM.calls(), max: LOOPSIM.callsMax(), tris: LOOPSIM.tris(), '
                        'fms: +LOOPSIM.frameMs().toFixed(1), s: +LOOPSIM.scroll.toFixed(0)})')
        r['at'] = s; r['seg'] = name; rows.append(r)
        if shots: pg.screenshot(path=str(shots / ('%s_%s_%04d.png' % (course, tier, s))))
    out = {'tier': tier, 'build_ms': round(pg.evaluate('LOOPSIM.buildMs()')), 'rig': pg.evaluate(
        'typeof RIG_MERGE === "object" ? {verts: RIG_MERGE.verts, tris: RIG_MERGE.tris, parts: RIG_MERGE.parts.length} : null'),
        'rows': rows, 'errors': errs[:5]}
    b.close()
print(json.dumps(out))
