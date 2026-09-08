"""Sent to live Blender: sculpt the Pump Lab track (same profile as the lab's yS: rollers, drop-in, doubles) with crown,
tyre ruts, packed lips and duff shoulders, plus a hero western redcedar; bake per-vertex AO; export v4 JSON (Y-up).
Track mesh keeps its indices (smooth-shaded in the lab); the cedar is faceted like the rest of the library."""
import bpy, bmesh, math, random, json
from mathutils import Vector, noise
from mathutils.bvhtree import BVHTree

OUT = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw\pnw_assets_v4.json"
random.seed(83)
# ---- the lab's track profile (must match pump-lab.html) ----
LAM, AMP, N_ROLL, X0 = 8.0, 0.55, 5, 8.0
XEND = X0 + N_ROLL * LAM
X1 = XEND + 7
TB = dict(H=0.70, lipDeg=22, R=3.5, deck=2.7, landDeg=24)
TB_TH = math.radians(TB["lipDeg"]); TB_XA = TB["R"] * math.sin(TB_TH); TB_YA = TB["R"] * (1 - math.cos(TB_TH))
TB_LIP = TB_XA + (TB["H"] - TB_YA) / math.tan(TB_TH); TB_LAND = TB["H"] / math.tan(math.radians(TB["landDeg"])) + 2.2
X_LIP = X1 + TB_LIP; X_DECK = X_LIP + TB["deck"]; XEND2 = X_DECK + TB_LAND; TRACK_END = XEND2 + 10
def tableH(t):
    if t < 0: return 0.0
    if t < TB_XA: return TB["R"] - math.sqrt(max(0.0, TB["R"] ** 2 - t * t))
    if t < TB_LIP: return TB_YA + (t - TB_XA) * math.tan(TB_TH)
    if t < TB_LIP + TB["deck"]: return TB["H"]
    if t < TB_LIP + TB["deck"] + TB_LAND:
        u = (t - TB_LIP - TB["deck"]) / TB_LAND; return TB["H"] * (1 - u * u * (3 - 2 * u))
    return 0.0
def yS(x):
    if x < X0: return AMP
    if x <= XEND: return AMP * (1 + math.cos(2 * math.pi * (x - X0) / LAM)) / 2
    if x < X1: return AMP
    if x <= XEND2: return AMP + tableH(x - X1)
    return AMP
def smooth(t): t = max(0.0, min(1.0, t)); return t * t * (3 - 2 * t)
def hsl(h, s, l):
    c = (1 - abs(2 * l - 1)) * s; x = c * (1 - abs((h * 6) % 2 - 1)); m = l - c / 2
    i = int(h * 6) % 6
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][i]
    return (r + m, g + m, b + m)

# ---------------------------------------------------------------- track
def build_track():
    bm = bmesh.new()
    DX = 0.10; xs = []; x = -6.0
    while x <= TRACK_END + 8: xs.append(x); x += DX
    lanes = [-2.3, -2.0, -1.75, -1.5, -1.2, -0.9, -0.62, -0.45, -0.3, -0.12, 0, 0.12, 0.3, 0.45, 0.62, 0.9, 1.2, 1.5, 1.75, 2.0, 2.3]
    rows = []; cols = []
    doubles = lambda x: X1 - 0.5 < x < XEND2 + 0.8      # the built table: packed, darker
    for x in xs:
        y0 = yS(x); row = []
        slope = (yS(x + 0.05) - yS(x - 0.05)) / 0.1
        for l in lanes:
            al = abs(l)
            wander = 0.06 * noise.noise(Vector((x * 0.21, 3.1, 0.0)))                    # ruts drift a little along the track
            rut = 0.0
            for rc in (-0.45, 0.45):
                d = abs(l - (rc + wander)) / 0.17
                if d < 1: rut += 0.032 * (1 - d * d) ** 2 * (0.7 + 0.3 * noise.noise(Vector((x * 0.9, rc, 1.0))))
            crown = -0.022 * l * l
            shoulder = -0.06 * smooth((al - 1.75) / 0.55)
            bumps = 0.006 * noise.noise(Vector((x * 2.7, l * 2.3, 5.0))) + 0.003 * noise.noise(Vector((x * 9.0, l * 7.0, 9.0)))
            lip = 0.0
            if doubles(x) and slope > 0.25 and al < 1.5: lip = 0.012 * smooth((slope - 0.25) / 0.3) * (1 - al / 1.5)   # packed, slightly built-up faces on the doubles
            y = y0 + crown - rut + shoulder + bumps + lip
            v = bm.verts.new((x, -l, y)); row.append(v)
            # colour
            n1 = noise.noise(Vector((x * 0.6, l * 1.7, 2.0))); n2 = noise.noise(Vector((x * 3.1, l * 3.1, 7.0)))
            lit = 0.30 + 0.05 * n1 + 0.025 * n2
            if doubles(x): lit -= 0.06
            if rut > 0.008: lit -= 0.07 * min(1, rut / 0.03)
            if al < 0.12: lit += 0.02
            c = hsl(0.07 + 0.008 * n1, 0.30 + 0.05 * n1, lit)
            duff = smooth((al - 1.55) / 0.5)
            if duff > 0:
                dc = hsl(0.075 + 0.02 * n2, 0.24, 0.13 + 0.03 * n2) if n1 > -0.1 else hsl(0.28, 0.22, 0.12 + 0.03 * n2)
                c = tuple(c[i] * (1 - duff) + dc[i] * duff for i in range(3))
            cols.append(c)
        rows.append(row)
    for i in range(len(rows) - 1):
        for j in range(len(lanes) - 1):
            a, b, c2, d = rows[i][j], rows[i][j + 1], rows[i + 1][j + 1], rows[i + 1][j]
            bm.faces.new((a, d, c2, b))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    if sum(1 for f in bm.faces if f.normal.z < 0) > len(bm.faces) / 2: bmesh.ops.reverse_faces(bm, faces=bm.faces)
    return bm, cols

# ---------------------------------------------------------------- hero cedar
def ring(bm, c, r, n, jit=0.0, squash=1.0):
    out = []
    for i in range(n):
        a = i / n * 2 * math.pi; rr = r * (1 + jit * (random.random() - 0.5))
        out.append(bm.verts.new(c + Vector((math.cos(a) * rr, math.sin(a) * rr * squash, 0))))
    return out
def bridge(bm, ra, rb, mat):
    n = len(ra)
    for i in range(n):
        f = bm.faces.new((ra[i], ra[(i + 1) % n], rb[(i + 1) % n], rb[i])); f.material_index = mat
def build_cedar2():
    bm = bmesh.new(); faces_frond = []
    H = 14.5; tiers = 9; rings = []
    for t in range(tiers + 1):
        z = H * t / tiers; r = 0.36 + (0.10 - 0.36) * (t / tiers) + 0.55 * max(0.0, 1 - z / (H * 0.16)) ** 2
        rr = []
        for i in range(9):
            a = i / 9 * 2 * math.pi
            fl = 1 + 0.42 * math.sin(a * 3 + 0.7) * max(0.0, 1 - z / (H * 0.32)) + 0.06 * noise.noise(Vector((a * 2, z * 0.7, 1)))
            rr.append(bm.verts.new((math.cos(a) * r * fl, math.sin(a) * r * fl, z)))
        rings.append(rr)
    for t in range(tiers): bridge(bm, rings[t], rings[t + 1], 0 if t % 2 == 0 else 1)
    cap = bm.verts.new((0, 0, H + 0.2))
    for i in range(9):
        f = bm.faces.new((rings[-1][i], rings[-1][(i + 1) % 9], cap)); f.material_index = 0
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # foliage: whorls of drooping fronds, each a bent tapered strip, dense
    for k, (z, R, cnt) in enumerate([(4.4, 2.9, 14), (5.5, 2.8, 14), (6.6, 2.65, 13), (7.7, 2.45, 13), (8.8, 2.2, 12), (9.9, 1.95, 12), (10.9, 1.65, 11), (11.8, 1.35, 10), (12.6, 1.05, 9), (13.3, 0.75, 8), (13.9, 0.45, 6)]):
        for i in range(cnt):
            a = i / cnt * 2 * math.pi + random.random() * 0.5
            ln = R * (0.85 + 0.3 * random.random()); seg = 5; w0 = 0.34 + 0.08 * random.random()
            pts = []
            for sgi in range(seg + 1):
                tt = sgi / seg; rr = ln * tt
                zz = z + 0.18 * math.sin(tt * 1.4) - 0.95 * tt * tt * (0.8 + 0.4 * random.random())   # up a touch, then droop
                pts.append(Vector((math.cos(a) * rr, math.sin(a) * rr, zz)))
            side = Vector((-math.sin(a), math.cos(a), 0))
            L = []; Rr = []
            for sgi, p in enumerate(pts):
                w = w0 * math.sin(min(1.0, 0.25 + sgi / seg) * math.pi) * (1 - 0.15 * sgi / seg) + 0.02
                L.append(bm.verts.new(p + side * w)); Rr.append(bm.verts.new(p - side * w))
            mat = 2 if (i + k) % 3 else 3
            if random.random() < 0.15: mat = 4
            for sgi in range(seg):
                f = bm.faces.new((L[sgi], Rr[sgi], Rr[sgi + 1], L[sgi + 1])); f.material_index = mat; faces_frond.append(f)
    tip = bm.verts.new((0, 0, H + 1.3))
    top = ring(bm, Vector((0, 0, H - 0.1)), 0.32, 6, jit=0.3)
    for i in range(6):
        f = bm.faces.new((top[i], top[(i + 1) % 6], tip)); f.material_index = 4
    return bm, None

PAL = {"track": None, "cedar2": ["5E4234", "6E5040", "2A4A2E", "365A38", "244228"]}
col = bpy.data.collections.get("PNW") or bpy.context.scene.collection
built = {}
for name, fn, loc in (("track", build_track, (0, 30, 0)), ("cedar2", build_cedar2, (62, 0, 0))):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    bm, vcols = fn()
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    if PAL[name]:
        for h in PAL[name]:
            mt = bpy.data.materials.get(name + "_" + h) or bpy.data.materials.new(name + "_" + h)
            mt.diffuse_color = (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, 1); ob.data.materials.append(mt)
    ob.location = loc; col.objects.link(ob); built[name] = (ob, vcols)
bpy.context.view_layer.update()

def fib_hemisphere(k):
    pts = []
    for i in range(k):
        z = (i + 0.5) / k; r = math.sqrt(1 - z * z); a = i * 2.399963
        pts.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
    return pts
RAYS = fib_hemisphere(16)
outj = {}
for name, (ob, vcols) in built.items():
    me = ob.data; me.calc_loop_triangles()
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    verts = me.vertices; ao = [1.0] * len(verts)
    for vi, v in enumerate(verts):
        nrm = v.normal.normalized() if v.normal.length > 1e-6 else Vector((0, 0, 1))
        up = Vector((0, 0, 1)) if abs(nrm.z) < 0.95 else Vector((1, 0, 0))
        tx = nrm.cross(up).normalized(); ty = nrm.cross(tx); occ = 0
        for d in RAYS:
            wd = (tx * d.x + ty * d.y + nrm * d.z).normalized()
            if bvh.ray_cast(v.co + nrm * 0.015, wd, 4.0 if name == "track" else 6.0)[0] is not None: occ += 1
        ao[vi] = 1.0 - occ / len(RAYS)
    zs = [v.co.z for v in verts]; zmin, zmax = min(zs), max(zs); span = max(zmax - zmin, 1e-3)
    hexes = [m.name.split("_")[-1] for m in ob.data.materials]
    V, T, C = [], [], []
    for v in verts: V += [round(v.co.x, 3), round(v.co.z, 3), round(-v.co.y, 3)]
    cols = [None] * len(verts)
    for tri in me.loop_triangles:
        T += list(tri.vertices)
        for vi in tri.vertices:
            if cols[vi] is None:
                if vcols is not None: base = vcols[vi]; a = 0.55 + 0.45 * ao[vi]; g = 1.0
                else:
                    h = hexes[min(tri.material_index, len(hexes) - 1)]
                    base = (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
                    a = 0.45 + 0.55 * ao[vi]; g = 1.0 if span < 1.5 else (0.82 + 0.18 * ((verts[vi].co.z - zmin) / span) ** 0.5)
                cols[vi] = tuple(min(1, ch * a * g) for ch in base)
    for c in cols:
        c = c or (0.5, 0.5, 0.5); C.append("%02x%02x%02x" % tuple(int(ch * 255) for ch in c))
    outj[name] = {"v": V, "t": T, "c": C, "smooth": name == "track"}
with open(OUT, "w") as f: json.dump(outj, f, separators=(",", ":"))
print("v4 export: " + ", ".join(f"{k}:{len(v['v'])//3}v/{len(v['t'])//3}t" for k, v in outj.items()))
