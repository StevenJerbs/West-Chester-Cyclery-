"""Blender 4.4 headless: build a low-poly PNW flora/fauna asset library and export it as compact JSON.

Assets (all Y-up after export transform, metres, origin at ground):
  cedar   - western redcedar: flared fluted trunk, drooping foliage tiers, bare below ~4.5 m
  fir     - Douglas fir / hemlock: tall bare trunk, narrow high crown (bare below ~5 m)
  snag    - dead grey spar with broken top and branch stubs
  fern    - sword fern rosette, ~0.7 m
  salal   - low glossy shrub cluster, ~0.5 m
  boulder - moss-topped rock
  stump   - mossy cut stump (North Shore nurse stump)
  raven   - simple gliding bird, wings out

Export: per-face material palette (hex) + vertices + triangle indices + per-tri palette index.
Blender is Z-up; exported as (x, z, -y) -> three.js Y-up.
"""
import bpy, bmesh, json, math, random
from mathutils import Vector, noise

OUT = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw\pnw_assets.json"
random.seed(11)

# palette per asset: material_index -> hex colour
PAL = {
    "cedar":   ["6B4A38", "7A5540", "2E4A30", "3A5C3A", "27402B"],   # bark, bark-lit, foliage dark, foliage lit, foliage deep
    "fir":     ["5A4A3E", "665043", "2B4630", "365640"],
    "snag":    ["8A8178", "9C948A", "6E675F"],
    "fern":    ["4A7A3A", "5C8C44", "3C6630"],
    "salal":   ["355430", "426644", "2B4628"],
    "boulder": ["7C7F7A", "8B8E88", "5E7A4C", "6E8A56"],             # rock, rock-lit, moss, moss-lit
    "stump":   ["5E4534", "6E5240", "5E7A4C", "8A8178"],
    "raven":   ["1E1E22", "2E2E34"],
}

def new_bm():
    return bmesh.new()

def cone_ring(bm, z, r, n, jitter=0.0, squash=1.0):
    ring = []
    for i in range(n):
        a = i / n * 2 * math.pi
        rr = r * (1 + jitter * (random.random() - 0.5))
        ring.append(bm.verts.new((math.cos(a) * rr, math.sin(a) * rr * squash, z)))
    return ring

def bridge(bm, ra, rb, mat):
    n = len(ra)
    for i in range(n):
        f = bm.faces.new((ra[i], ra[(i + 1) % n], rb[(i + 1) % n], rb[i]))
        f.material_index = mat

def cap(bm, ring, z, mat, r=0.0):
    c = bm.verts.new((0, 0, z))
    n = len(ring)
    for i in range(n):
        f = bm.faces.new((ring[i], ring[(i + 1) % n], c))
        f.material_index = mat

def trunk(bm, h, r0, r1, n=7, flare=0.0, flutes=0.0, bark=0, bark_lit=1, tiers=5):
    rings = []
    for t in range(tiers + 1):
        z = h * t / tiers
        r = r0 + (r1 - r0) * (t / tiers) + flare * max(0.0, 1 - z / (h * 0.18)) ** 2
        ring = []
        for i in range(n):
            a = i / n * 2 * math.pi
            fl = 1 + flutes * 0.4 * math.sin(a * 3 + 0.7) * max(0.0, 1 - z / (h * 0.35))
            ring.append(bm.verts.new((math.cos(a) * r * fl, math.sin(a) * r * fl, z)))
        rings.append(ring)
    for t in range(tiers):
        bridge(bm, rings[t], rings[t + 1], bark if t % 2 == 0 else bark_lit)
    cap(bm, rings[-1], h, bark)
    return rings

def foliage_tier(bm, z, r, drop, n, mat, top_z=None):
    """One conifer tier: a shallow cone whose rim droops below its attach height."""
    rim = cone_ring(bm, z - drop, r, n, jitter=0.35)
    tip = bm.verts.new((0, 0, top_z if top_z is not None else z + r * 0.55))
    for i in range(n):
        f = bm.faces.new((rim[i], rim[(i + 1) % n], tip))
        f.material_index = mat
    under = bm.verts.new((0, 0, z - drop * 0.35))
    for i in range(n):
        f = bm.faces.new((rim[(i + 1) % n], rim[i], under))
        f.material_index = mat + (1 if mat + 1 < 5 else 0)

def build_cedar():
    bm = new_bm()
    trunk(bm, 13.0, 0.34, 0.10, n=7, flare=0.5, flutes=1.0, bark=0, bark_lit=1, tiers=5)
    zs = [4.6, 6.2, 7.8, 9.3, 10.7, 11.9]
    rs = [2.6, 2.4, 2.1, 1.7, 1.25, 0.8]
    for k, (z, r) in enumerate(zip(zs, rs)):
        foliage_tier(bm, z, r, drop=0.85, n=8, mat=2 if k % 2 == 0 else 3)
    foliage_tier(bm, 12.7, 0.45, drop=0.3, n=6, mat=4, top_z=13.6)
    return bm

def build_fir():
    bm = new_bm()
    trunk(bm, 16.0, 0.26, 0.07, n=6, flare=0.15, flutes=0.0, bark=0, bark_lit=1, tiers=4)
    zs = [5.4, 7.2, 9.0, 10.7, 12.3, 13.7, 15.0]
    rs = [1.7, 1.65, 1.5, 1.3, 1.05, 0.75, 0.45]
    for k, (z, r) in enumerate(zip(zs, rs)):
        foliage_tier(bm, z, r, drop=0.45, n=7, mat=2 if k % 2 == 0 else 3)
    foliage_tier(bm, 15.8, 0.3, drop=0.15, n=5, mat=2, top_z=16.7)
    return bm

def build_snag():
    bm = new_bm()
    rings = trunk(bm, 9.5, 0.28, 0.12, n=6, flare=0.3, flutes=0.6, bark=0, bark_lit=1, tiers=4)
    # jagged top: pull two rim verts up unevenly
    top = rings[-1]
    top[0].co.z += 1.1
    top[2].co.z += 0.4
    top[4].co.z -= 0.3
    # branch stubs
    for z, a, ln in [(4.2, 0.7, 0.9), (6.1, 2.6, 1.2), (7.6, 4.5, 0.7)]:
        d = Vector((math.cos(a), math.sin(a), 0.25)).normalized()
        base = Vector((math.cos(a) * 0.18, math.sin(a) * 0.18, z))
        ring = []
        for i in range(4):
            aa = i / 4 * 2 * math.pi
            off = Vector((math.cos(aa), math.sin(aa), 0)).cross(d) * 0.06 + Vector((0, 0, 0.06 * math.sin(aa)))
            ring.append(bm.verts.new(base + off))
        tipv = bm.verts.new(base + d * ln)
        for i in range(4):
            f = bm.faces.new((ring[i], ring[(i + 1) % 4], tipv))
            f.material_index = 2
    return bm

def frond(bm, a, ln, mat):
    """A sword-fern frond: a tapered strip bent up then over."""
    seg = 4
    w0 = 0.085
    pts = []
    for s in range(seg + 1):
        t = s / seg
        r = ln * t
        z = 0.12 + 0.62 * math.sin(t * 1.9) * (1 - 0.35 * t)
        pts.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
    left, right = [], []
    for s, p in enumerate(pts):
        w = w0 * (1 - 0.85 * (s / seg))
        side = Vector((-math.sin(a), math.cos(a), 0)) * w
        left.append(bm.verts.new(p + side))
        right.append(bm.verts.new(p - side))
    for s in range(seg):
        f = bm.faces.new((left[s], right[s], right[s + 1], left[s + 1]))
        f.material_index = mat
    return bm

def build_fern():
    bm = new_bm()
    n = 9
    for i in range(n):
        a = i / n * 2 * math.pi + random.random() * 0.4
        frond(bm, a, 0.55 + random.random() * 0.3, random.choice([0, 1, 1, 2]))
    return bm

def build_salal():
    bm = new_bm()
    for cx, cy, r, m in [(0, 0, 0.34, 0), (0.3, 0.12, 0.24, 1), (-0.26, 0.18, 0.2, 2), (0.05, -0.3, 0.22, 1)]:
        mesh = bpy.data.meshes.new("t")
        b2 = bmesh.new()
        bmesh.ops.create_icosphere(b2, subdivisions=1, radius=r)
        for v in b2.verts:
            v.co.z *= 0.62
            v.co += Vector((cx, cy, r * 0.5))
            v.co += Vector((noise.noise(v.co * 3.0) * 0.05,) * 3)
        for f in b2.faces:
            f.material_index = m
        b2.to_mesh(mesh)
        b2.free()
        bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)
    return bm

def build_boulder():
    bm = new_bm()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.75)
    for v in bm.verts:
        v.co += Vector((noise.noise(v.co * 1.7 + Vector((3, 1, 7))) * 0.22,) * 3)
        v.co.z = v.co.z * 0.75 + 0.45
    for f in bm.faces:
        up = f.normal.z
        mossy = up > 0.35 and noise.noise(f.calc_center_median() * 2.2) > -0.15
        f.material_index = (2 if noise.noise(f.calc_center_median() * 5) < 0.2 else 3) if mossy else (0 if up < 0.7 else 1)
    return bm

def build_stump():
    bm = new_bm()
    rings = trunk(bm, 1.1, 0.42, 0.34, n=7, flare=0.5, flutes=1.2, bark=0, bark_lit=1, tiers=2)
    for v in rings[-1]:
        v.co.z += random.random() * 0.35 - 0.1
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        c = f.calc_center_median()
        if c.z > 0.95 or (f.normal.z > 0.5):
            f.material_index = 2
        elif c.z > 0.6 and noise.noise(c * 4) > 0.1:
            f.material_index = 2
    return bm

def build_raven():
    bm = new_bm()
    body = [bm.verts.new(p) for p in [(-0.28, 0, 0.02), (0.05, 0.05, 0.06), (0.05, -0.05, 0.06), (0.34, 0, 0.0)]]
    for tri in [(0, 1, 2), (1, 3, 2), (0, 2, 1), (1, 2, 3)]:
        try:
            f = bm.faces.new((body[tri[0]], body[tri[1]], body[tri[2]]))
            f.material_index = 0
        except ValueError:
            pass
    for s in (1, -1):
        a = bm.verts.new((0.02, 0.04 * s, 0.05))
        b = bm.verts.new((-0.08, 0.55 * s, 0.16))
        c = bm.verts.new((-0.22, 0.95 * s, 0.10))
        d = bm.verts.new((-0.16, 0.5 * s, 0.04))
        f = bm.faces.new((a, b, d) if s > 0 else (a, d, b)); f.material_index = 1
        f = bm.faces.new((b, c, d) if s > 0 else (b, d, c)); f.material_index = 1
    return bm

def export(bm, name):
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    idx = {v: i for i, v in enumerate(bm.verts)}
    verts = []
    for v in bm.verts:
        # Blender Z-up -> three.js Y-up
        verts += [round(v.co.x, 3), round(v.co.z, 3), round(-v.co.y, 3)]
    tris, mats = [], []
    for f in bm.faces:
        vs = [idx[v] for v in f.verts]
        tris += vs
        mats.append(min(f.material_index, len(PAL[name]) - 1))
    bm.free()
    return {"pal": PAL[name], "v": verts, "t": tris, "m": mats}

out = {}
for name, fn in [("cedar", build_cedar), ("fir", build_fir), ("snag", build_snag), ("fern", build_fern),
                 ("salal", build_salal), ("boulder", build_boulder), ("stump", build_stump), ("raven", build_raven)]:
    bm = fn()
    out[name] = export(bm, name)
    print(name, len(out[name]["v"]) // 3, "verts", len(out[name]["m"]), "tris")

with open(OUT, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print("WROTE", OUT)
