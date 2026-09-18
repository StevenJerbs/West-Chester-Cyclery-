"""Sent to live Blender over the socket: rebuild low-detail assets at higher detail,
bake per-vertex AO (BVH hemisphere rays + cavity), export all assets as v2 JSON with
per-vertex colours."""
import bpy, bmesh, sys, math, random, json
from mathutils import Vector, noise
from mathutils.bvhtree import BVHTree

SRC = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw\build_assets.py"
OUT = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw\pnw_assets_v2.json"
src = open(SRC, encoding="utf-8").read()
src = src[:src.index("out = {}")]
mod = type(sys)("pnw_assets"); exec(compile(src, "pnw_assets", "exec"), mod.__dict__)
random.seed(31)

# ---- higher-detail rebuilds ----------------------------------------------
def build_boulder2():
    bm = mod.new_bm()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.75)
    for v in bm.verts:
        n1 = noise.noise(v.co * 1.6 + Vector((3, 1, 7)))
        n2 = noise.noise(v.co * 4.2 + Vector((11, 5, 2)))
        v.co *= 1 + 0.30 * n1 + 0.10 * n2
        v.co.z = v.co.z * 0.72 + 0.45
    for f in bm.faces:
        up = f.normal.z
        c = f.calc_center_median()
        mossy = up > 0.28 and noise.noise(c * 2.0) > -0.25
        f.material_index = (2 if noise.noise(c * 5) < 0.2 else 3) if mossy else (0 if up < 0.7 else 1)
    return bm

def build_salal2():
    bm = mod.new_bm()
    for cx, cy, r, m in [(0, 0, 0.36, 0), (0.30, 0.14, 0.26, 1), (-0.27, 0.19, 0.22, 2), (0.06, -0.30, 0.24, 1), (-0.1, -0.05, 0.3, 0)]:
        mesh = bpy.data.meshes.new("t"); b2 = bmesh.new()
        bmesh.ops.create_icosphere(b2, subdivisions=2, radius=r)
        for v in b2.verts:
            v.co.z *= 0.6
            v.co += Vector((cx, cy, r * 0.5))
            v.co += Vector((noise.noise(v.co * 3.4) * 0.06,) * 3)
        for f in b2.faces:
            f.material_index = m if noise.noise(f.calc_center_median() * 6) < 0.4 else (m + 1) % 3
        b2.to_mesh(mesh); b2.free(); bm.from_mesh(mesh); bpy.data.meshes.remove(mesh)
    return bm

def build_fern2():
    bm = mod.new_bm()
    n = 13
    for i in range(n):
        a = i / n * 2 * math.pi + random.random() * 0.35
        ln = 0.5 + random.random() * 0.38
        seg = 6
        w0 = 0.10
        pts = []
        for sgi in range(seg + 1):
            t = sgi / seg
            r = ln * t
            z = 0.10 + 0.66 * math.sin(t * 1.95) * (1 - 0.38 * t)
            pts.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
        left, right = [], []
        for sgi, p in enumerate(pts):
            w = w0 * (1 - 0.9 * (sgi / seg)) * (0.5 + 0.5 * math.sin(min(sgi / seg, 0.5) * math.pi))
            side = Vector((-math.sin(a), math.cos(a), 0)) * max(w, 0.008)
            left.append(bm.verts.new(p + side)); right.append(bm.verts.new(p - side))
        mcol = random.choice([0, 1, 1, 2])
        for sgi in range(seg):
            f = bm.faces.new((left[sgi], right[sgi], right[sgi + 1], left[sgi + 1]))
            f.material_index = mcol
    return bm

col = bpy.data.collections["PNW"]
for name, fn in [("boulder", build_boulder2), ("salal", build_salal2), ("fern", build_fern2)]:
    old = bpy.data.objects.get(name)
    loc = old.location.copy() if old else Vector((0, 0, 0))
    mats = [m for m in (old.data.materials if old else [])]
    if old: bpy.data.objects.remove(old, do_unlink=True)
    bm = fn(); bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    for m in mats: ob.data.materials.append(m)
    ob.location = loc; col.objects.link(ob)

# ---- AO bake + v2 export --------------------------------------------------
def fib_hemisphere(k):
    pts = []
    for i in range(k):
        z = (i + 0.5) / k
        r = math.sqrt(1 - z * z)
        a = i * 2.399963
        pts.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
    return pts

RAYS = fib_hemisphere(20)
ASSETS = ["cedar", "fir", "snag", "fern", "salal", "boulder", "stump", "raven", "cedar3", "hemlock", "maple"]
outj = {}
for name in ASSETS:
    ob = bpy.data.objects.get(name)
    if ob is None: continue
    me = ob.data
    me.calc_loop_triangles()
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    # per-vertex normal from mesh
    verts = me.vertices
    ao = [0.0] * len(verts)
    for vi, v in enumerate(verts):
        nrm = v.normal.normalized() if v.normal.length > 1e-6 else Vector((0, 0, 1))
        # build tangent frame around the normal
        up = Vector((0, 0, 1)) if abs(nrm.z) < 0.95 else Vector((1, 0, 0))
        tx = nrm.cross(up).normalized(); ty = nrm.cross(tx)
        occ = 0
        for d in RAYS:
            wd = (tx * d.x + ty * d.y + nrm * d.z).normalized()
            hit = bvh.ray_cast(v.co + nrm * 0.02, wd, 6.0)
            if hit[0] is not None: occ += 1
        ao[vi] = 1.0 - occ / len(RAYS)
    # ground shading: darken toward the base for tall assets
    zs = [v.co.z for v in verts]
    zmin, zmax = min(zs), max(zs)
    span = max(zmax - zmin, 1e-3)
    pal = mod.PAL[name] if name in mod.PAL else None
    # material palettes stored on the object in build order
    hexes = [m.name.split("_")[-1] for m in ob.data.materials] if ob.data.materials else (pal or ["888888"])
    V, T, C = [], [], []
    for v in verts:
        # export Y-up
        V += [round(v.co.x, 3), round(v.co.z, 3), round(-v.co.y, 3)]
    cols = [None] * len(verts)
    for tri in me.loop_triangles:
        mi = min(tri.material_index, len(hexes) - 1)
        h = hexes[mi]
        base = (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
        T += list(tri.vertices)
        for vi in tri.vertices:
            if cols[vi] is None:
                a = 0.45 + 0.55 * ao[vi]
                g = 1.0 if span < 1.5 else (0.82 + 0.18 * ((verts[vi].co.z - zmin) / span) ** 0.5)
                cols[vi] = tuple(min(1, ch * a * g) for ch in base)
    for c in cols:
        c = c or (0.5, 0.5, 0.5)
        C.append("%02x%02x%02x" % tuple(int(ch * 255) for ch in c))
    outj[name] = {"v": V, "t": T, "c": C}

with open(OUT, "w") as f:
    json.dump(outj, f, separators=(",", ":"))
result = "v2 export: " + ", ".join(f"{k}:{len(v['v'])//3}v/{len(v['t'])//3}t" for k, v in outj.items())
