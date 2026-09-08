"""Sent to live Blender: author three new PNW assets for the Pump Lab (foxglove, nurse log, trail sign),
bake per-vertex AO the same way as v2, export as v3 JSON (Y-up, per-vertex colours)."""
import bpy, bmesh, math, random, json
from mathutils import Vector, noise
from mathutils.bvhtree import BVHTree

OUT = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw\pnw_assets_v3.json"
random.seed(47)
PAL = {
    "foxglove": ["4E7A3E", "B8477E", "D98AB0", "F0D3E0"],                       # stem+leaves, bell shade, bell lit, bell mouth
    "nurselog": ["5A4232", "6A5040", "5E7A4C", "6E8A56", "3A5C3A", "C9B48A"],   # bark, bark lit, moss, moss lit, seedling, shelf fungus
    "sign":     ["6E5240", "E8E4D8", "1E1E22"],                                 # post, board, black diamonds
}
Z = Vector((0, 0, 1)); X = Vector((1, 0, 0)); Y = Vector((0, 1, 0))

def ring(bm, c, u, v, r, n, jit=0.0):
    out = []
    for i in range(n):
        a = i / n * 2 * math.pi
        rr = r * (1 + jit * (random.random() - 0.5))
        out.append(bm.verts.new(c + u * (math.cos(a) * rr) + v * (math.sin(a) * rr)))
    return out

def bridge(bm, ra, rb, mat):
    n = len(ra)
    for i in range(n):
        f = bm.faces.new((ra[i], ra[(i + 1) % n], rb[(i + 1) % n], rb[i])); f.material_index = mat

def fan(bm, rg, c, mat):
    cv = bm.verts.new(c); n = len(rg)
    for i in range(n):
        f = bm.faces.new((rg[i], rg[(i + 1) % n], cv)); f.material_index = mat

def merge(bm, part):
    me = bpy.data.meshes.new("tmp"); part.to_mesh(me); part.free(); bm.from_mesh(me); bpy.data.meshes.remove(me)

def face_up(bm, faces, want):
    """flip single-sided faces so their normal points along `want`"""
    bm.normal_update()
    bad = [f for f in faces if f.normal.dot(want) < 0]
    if bad: bmesh.ops.reverse_faces(bm, faces=bad)

# ---------------------------------------------------------------- foxglove
def build_foxglove():
    bm = bmesh.new()
    rings = []
    for k in range(6):
        t = k / 5; z = 1.22 * t; r = 0.014 * (1 - 0.55 * t)
        c = Vector((0.035 * t * t, 0.012 * t, z))
        rings.append(ring(bm, c, X, Y, r, 4))
    for k in range(5): bridge(bm, rings[k], rings[k + 1], 0)
    fan(bm, rings[-1], Vector((0.035, 0.012, 1.25)), 0)
    fan(bm, list(reversed(rings[0])), Vector((0, 0, 0)), 0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for i in range(17):                                             # bells spiral up the top 60%
        t = i / 16; z = 0.46 + 0.66 * t; a = i * 2.4 + 0.3
        d = Vector((math.cos(a), math.sin(a), -0.42)).normalized()
        st = Vector((0.035 * (z / 1.22) ** 2, 0.012 * z / 1.22, z))
        base = st + d * 0.012
        u = d.cross(Z).normalized(); v = d.cross(u)
        size = 1.0 - 0.5 * t
        r0, r1, L = 0.011 * size, 0.034 * size, 0.09 * size
        part = bmesh.new()
        rb = ring(part, base, u, v, r0, 6); rm = ring(part, base + d * L, u, v, r1, 6, jit=0.15)
        bridge(part, rb, rm, 1 if (i % 3 == 0) else 2)
        fan(part, list(reversed(rb)), base - d * 0.004, 1)
        fan(part, rm, base + d * L * 0.86, 3)                       # pale mouth, inset
        bmesh.ops.recalc_face_normals(part, faces=part.faces)
        merge(bm, part)
    for i in range(3):                                               # buds at the tip
        a = i * 2.1; z = 1.14 + i * 0.035
        d = Vector((math.cos(a) * 0.5, math.sin(a) * 0.5, 0.85)).normalized()
        base = Vector((0.035, 0.012, z)); u = d.cross(Z).normalized(); v = d.cross(u)
        part = bmesh.new(); rb = ring(part, base, u, v, 0.012, 5)
        fan(part, rb, base + d * 0.035, 2); fan(part, list(reversed(rb)), base, 2)
        bmesh.ops.recalc_face_normals(part, faces=part.faces); merge(bm, part)
    leaves = []
    for i in range(6):                                               # basal rosette of broad leaves
        a = i / 6 * 2 * math.pi + 0.35 * random.random(); ln = 0.24 + 0.08 * random.random()
        pts = []
        for s in range(4):
            tt = s / 3; r = ln * tt; z = 0.02 + 0.10 * math.sin(tt * 2.2)
            pts.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
        side = Vector((-math.sin(a), math.cos(a), 0))
        left = [bm.verts.new(p + side * (0.05 * math.sin(min(1, s / 2.2) * math.pi) + 0.006)) for s, p in enumerate(pts)]
        right = [bm.verts.new(p - side * (0.05 * math.sin(min(1, s / 2.2) * math.pi) + 0.006)) for s, p in enumerate(pts)]
        for s in range(3):
            f = bm.faces.new((left[s], right[s], right[s + 1], left[s + 1])); f.material_index = 0; leaves.append(f)
    face_up(bm, leaves, Z)
    return bm

# ---------------------------------------------------------------- nurse log
def build_nurselog():
    bm = bmesh.new(); L = 5.2; n = 11; m = 9
    rings = []
    for k in range(n + 1):
        t = k / n; x = -L / 2 + L * t; r = 0.47 - 0.17 * t
        c = Vector((x, 0.07 * math.sin(t * 3.7), r * 0.93 + 0.04 * math.sin(t * math.pi)))
        rr = []
        for i in range(m):
            a = i / m * 2 * math.pi
            p = c + Vector((0, math.cos(a) * r, math.sin(a) * r))
            p += Vector((0, math.cos(a), math.sin(a))) * (0.08 * r * noise.noise(p * 2.3 + Vector((5, 1, 9))))
            rr.append(bm.verts.new(p))
        rings.append(rr)
    for k in range(n): bridge(bm, rings[k], rings[k + 1], 0 if k % 2 else 1)
    fan(bm, list(reversed(rings[0])), Vector((-L / 2 - 0.04, 0, 0.45)), 0)
    fan(bm, rings[-1], Vector((L / 2 + 0.03, 0.02, 0.29)), 1)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    for f in bm.faces:                                               # moss on the upper surface, patchy
        c = f.calc_center_median()
        if f.normal.z > 0.25 and noise.noise(c * 1.6 + Vector((2, 7, 3))) > -0.3:
            f.material_index = 2 if noise.noise(c * 5.0) < 0.15 else 3
    for j in range(7):                                               # root wad at the butt end
        a = j / 7 * 2 * math.pi + 0.2
        d = Vector((-0.75, math.cos(a) * 0.9, math.sin(a) * 0.9 + 0.35)).normalized()
        base = Vector((-L / 2 + 0.05, math.cos(a) * 0.30, 0.45 + math.sin(a) * 0.30))
        u = d.cross(Z if abs(d.z) < 0.9 else X).normalized(); v = d.cross(u)
        part = bmesh.new(); rb = ring(part, base, u, v, 0.075, 4)
        fan(part, rb, base + d * (0.55 + 0.35 * random.random()), 0); fan(part, list(reversed(rb)), base - d * 0.02, 0)
        bmesh.ops.recalc_face_normals(part, faces=part.faces); merge(bm, part)
    for x in (-1.4, 0.2, 1.75):                                      # hemlock seedlings rooted in the moss
        t = (x + L / 2) / L; r = 0.47 - 0.17 * t; top = r * 0.93 + r + 0.02
        base = Vector((x, 0.07 * math.sin(t * 3.7) + 0.05, top - 0.03))
        part = bmesh.new()
        for tier, (zz, rr) in enumerate([(0.0, 0.17), (0.16, 0.13), (0.30, 0.08)]):
            rg = ring(part, base + Z * zz, X, Y, rr, 5, jit=0.3)
            fan(part, rg, base + Z * (zz + 0.20), 4); fan(part, list(reversed(rg)), base + Z * (zz + 0.02), 4)
        bmesh.ops.recalc_face_normals(part, faces=part.faces); merge(bm, part)
    fungi = []
    for x, zz in ((-0.6, 0.55), (0.1, 0.62), (0.45, 0.50), (1.3, 0.48)):   # shelf fungi on the camera side (-y)
        t = (x + L / 2) / L; r = 0.47 - 0.17 * t
        c = Vector((x, 0.07 * math.sin(t * 3.7) - r * 0.96, zz * (r / 0.45)))
        pts = [bm.verts.new(c)]
        for i in range(6):
            a = math.pi + i / 5 * math.pi
            pts.append(bm.verts.new(c + Vector((math.cos(a) * 0.16, math.sin(a) * 0.16 - 0.02, -0.02 * abs(math.sin(a))))))
        for i in range(1, 6):
            f = bm.faces.new((pts[0], pts[i], pts[i + 1])); f.material_index = 5; fungi.append(f)
    face_up(bm, fungi, Z)
    return bm

# ---------------------------------------------------------------- trail sign
def build_sign():
    bm = bmesh.new()
    def cube(sx, sy, sz, cx, cy, cz, mat):
        part = bmesh.new(); r = bmesh.ops.create_cube(part, size=1.0)
        bmesh.ops.scale(part, vec=(sx, sy, sz), verts=part.verts); bmesh.ops.translate(part, vec=(cx, cy, cz), verts=part.verts)
        for f in part.faces: f.material_index = mat
        merge(bm, part)
    cube(0.09, 0.09, 1.48, 0, 0, 0.74, 0)
    cube(0.64, 0.035, 0.36, 0, -0.062, 1.20, 1)
    dia = []
    for cx in (-0.155, 0.155):
        vs = [bm.verts.new(Vector(p)) for p in ((cx, -0.084, 1.20 + 0.115), (cx + 0.115, -0.084, 1.20), (cx, -0.084, 1.20 - 0.115), (cx - 0.115, -0.084, 1.20))]
        f = bm.faces.new(vs); f.material_index = 2; dia.append(f)
    face_up(bm, dia, -Y)
    return bm

# ---------------------------------------------------------------- build, link, bake, export
col = bpy.data.collections.get("PNW") or bpy.context.scene.collection
built = {}
for name, fn, loc in (("foxglove", build_foxglove, (40, 0, 0)), ("nurselog", build_nurselog, (46, 0, 0)), ("sign", build_sign, (54, 0, 0))):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    bm = fn(); bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    for h in PAL[name]:
        mname = name + "_" + h
        mt = bpy.data.materials.get(mname) or bpy.data.materials.new(mname)
        mt.diffuse_color = (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, 1)
        ob.data.materials.append(mt)
    ob.location = loc; col.objects.link(ob); built[name] = ob
bpy.context.view_layer.update()

def fib_hemisphere(k):
    pts = []
    for i in range(k):
        z = (i + 0.5) / k; r = math.sqrt(1 - z * z); a = i * 2.399963
        pts.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
    return pts
RAYS = fib_hemisphere(20)
outj = {}
for name, ob in built.items():
    me = ob.data; me.calc_loop_triangles()
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    verts = me.vertices; ao = [0.0] * len(verts)
    for vi, v in enumerate(verts):
        nrm = v.normal.normalized() if v.normal.length > 1e-6 else Vector((0, 0, 1))
        up = Vector((0, 0, 1)) if abs(nrm.z) < 0.95 else Vector((1, 0, 0))
        tx = nrm.cross(up).normalized(); ty = nrm.cross(tx); occ = 0
        for d in RAYS:
            wd = (tx * d.x + ty * d.y + nrm * d.z).normalized()
            if bvh.ray_cast(v.co + nrm * 0.015, wd, 6.0)[0] is not None: occ += 1
        ao[vi] = 1.0 - occ / len(RAYS)
    zs = [v.co.z for v in verts]; zmin, zmax = min(zs), max(zs); span = max(zmax - zmin, 1e-3)
    hexes = [m.name.split("_")[-1] for m in ob.data.materials]
    V, T, C = [], [], []
    for v in verts: V += [round(v.co.x, 3), round(v.co.z, 3), round(-v.co.y, 3)]
    cols = [None] * len(verts)
    for tri in me.loop_triangles:
        h = hexes[min(tri.material_index, len(hexes) - 1)]
        base = (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
        T += list(tri.vertices)
        for vi in tri.vertices:
            if cols[vi] is None:
                a = 0.45 + 0.55 * ao[vi]
                g = 1.0 if span < 1.5 else (0.82 + 0.18 * ((verts[vi].co.z - zmin) / span) ** 0.5)
                cols[vi] = tuple(min(1, ch * a * g) for ch in base)
    for c in cols:
        c = c or (0.5, 0.5, 0.5); C.append("%02x%02x%02x" % tuple(int(ch * 255) for ch in c))
    outj[name] = {"v": V, "t": T, "c": C}
with open(OUT, "w") as f: json.dump(outj, f, separators=(",", ":"))
print("v3 export: " + ", ".join(f"{k}:{len(v['v'])//3}v/{len(v['t'])//3}t" for k, v in outj.items()))
