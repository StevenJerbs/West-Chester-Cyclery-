"""Sent to live Blender: rebuild the Pump Lab world from pump_world.json (terrain + every instanced placement of the PNW
library + the sculpted track), light it with a Cycles sun + Nishita sky, and bake per-vertex SUN VISIBILITY (soft,
ray-traced shadow) and AMBIENT OCCLUSION into the terrain and the track (GPU/OptiX if available). Also authors three
trailside assets (rock edging, wooden start deck, duff sticks) with the usual per-vertex AO. Exports v5 JSON:
  bake_terrain: per-vertex [shadow, ao] as 2 hex bytes, in the page's terrain vertex order
  bake_track:   same, in the track asset's vertex order
  rockedge / startdeck / sticks: v2-style assets
Every step logs to live_v5.log; exceptions land in the log."""
import bpy, bmesh, math, random, json, time, traceback
from mathutils import Vector, Euler, noise
from mathutils.bvhtree import BVHTree
SCR = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw"
log = open(SCR + r"\live_v5.log", "w")
def L(m): log.write(m + "\n"); log.flush()
Y = lambda x, y, z: (x, -z, y)
random.seed(97)

def main():
    W = json.load(open(SCR + r"\pump_world.json"))
    sc = bpy.context.scene
    lib = bpy.data.collections.get("PNW")
    for ob in lib.objects: ob.hide_render = True; ob.hide_viewport = True
    old = bpy.data.collections.get("PUMP")
    if old:
        for ob in list(old.objects):
            if ob.name.startswith("i_") or ob.name in ("PumpTerrain", "Sun_Pump"): bpy.data.objects.remove(ob, do_unlink=True)
            else: old.objects.unlink(ob)
        bpy.data.collections.remove(old)
    pump = bpy.data.collections.new("PUMP"); sc.collection.children.link(pump)
    # ---- terrain (page vertex order preserved)
    t = W["terrain"]; nv = len(t["pos"]) // 3
    me = bpy.data.meshes.new("PumpTerrain")
    me.from_pydata([Y(t["pos"][i*3], t["pos"][i*3+1], t["pos"][i*3+2]) for i in range(nv)], [], [tuple(t["idx"][i:i+3]) for i in range(0, len(t["idx"]), 3)])
    me.validate(); me.update(); terr = bpy.data.objects.new("PumpTerrain", me); pump.objects.link(terr)
    for v in me.vertices:                                                       # the page hides the terrain under the track ribbon; for the bake, drop it clear of the sculpted track
        if abs(v.co.y) < 2.7 and -8 < v.co.x < W["trackEnd"] + 10: v.co.z -= 0.22
    L("terrain %d verts %d faces" % (nv, len(me.polygons)))
    # ---- track: the baked v4 object, moved to the origin
    trk = bpy.data.objects.get("track")
    if trk is None:                                                              # rebuild from the v4 export (Y-up -> Blender)
        V4 = json.load(open(SCR + r"\pnw_assets_v4.json"))["track"]; nv4 = len(V4["v"]) // 3
        m4 = bpy.data.meshes.new("track"); m4.from_pydata([(V4["v"][i*3], -V4["v"][i*3+2], V4["v"][i*3+1]) for i in range(nv4)], [], [tuple(V4["t"][i:i+3]) for i in range(0, len(V4["t"]), 3)])
        m4.validate(); m4.update(); trk = bpy.data.objects.new("track", m4); lib.objects.link(trk); L("track rebuilt from v4: %d verts" % nv4)
    trk.location = (0, 0, 0); trk.hide_render = False; trk.hide_viewport = False
    if trk.name not in pump.objects: pump.objects.link(trk)
    # ---- flora / rocks / logs instances as occluders
    n = 0
    for name, places in W["places"].items():
        src = bpy.data.objects.get(name)
        if src is None: L("no source for " + name); continue
        for k, p in enumerate(places):
            ob = bpy.data.objects.new("i_%s_%04d" % (name, k), src.data)
            ob.location = Y(p["x"], p["y"], p["z"]); ob.rotation_euler = Euler((0, 0, -p.get("ry", 0)), "XYZ"); ob.scale = (p.get("s", 1),) * 3
            pump.objects.link(ob); n += 1
    L("placed %d instances" % n)
    # ---- light: sun matching the page (from (-18, 42, 30) toward the origin in three.js) + Nishita sky
    for ob in list(sc.objects):
        if ob.type == "LIGHT": ob.hide_render = True
    sd = bpy.data.lights.new("Sun_Pump", "SUN"); sd.energy = 4.0; sd.angle = math.radians(3.0)
    sun = bpy.data.objects.new("Sun_Pump", sd); pump.objects.link(sun)
    d = Vector(Y(-18, 42, 30)).normalized()                                     # direction toward the light
    sun.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    world = sc.world; world.use_nodes = True; wn = world.node_tree; wn.nodes.clear()
    out = wn.nodes.new("ShaderNodeOutputWorld"); bg = wn.nodes.new("ShaderNodeBackground"); sky = wn.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    for attr, val in (("sun_elevation", math.asin(d.z)), ("sun_rotation", math.atan2(d.x, d.y)), ("sun_intensity", 0.0), ("altitude", 300)):
        try: setattr(sky, attr, val)
        except Exception as e: L("sky attr %s: %s" % (attr, e))
    bg.inputs["Strength"].default_value = 0.6
    wn.links.new(sky.outputs[0], bg.inputs["Color"]); wn.links.new(bg.outputs[0], out.inputs["Surface"])
    # ---- Cycles on the GPU
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons.get("cycles")
    if prefs:
        cp = prefs.preferences
        for dt in ("OPTIX", "CUDA"):
            try:
                cp.compute_device_type = dt; cp.get_devices()
                for dev in cp.devices: dev.use = dev.type != "CPU" or True
                L("compute " + dt); break
            except Exception as e: L("no " + dt + ": " + str(e))
    sc.cycles.device = "GPU"; sc.cycles.samples = 96; sc.cycles.use_denoising = False
    sc.cycles.bake_type = "SHADOW"
    sc.render.bake.target = "VERTEX_COLORS"
    def bake(ob, kind, attr):
        ca = ob.data.color_attributes.get(attr) or ob.data.color_attributes.new(name=attr, type="FLOAT_COLOR", domain="POINT")
        ob.data.color_attributes.active_color = ca
        for o in sc.objects: o.select_set(False)
        ob.select_set(True); bpy.context.view_layer.objects.active = ob
        sc.cycles.bake_type = kind
        if kind == "AO":
            sc.world.light_settings.distance = 3.5
        t0 = time.time(); bpy.ops.object.bake(type=kind, target="VERTEX_COLORS"); L("baked %s %s in %.0f s" % (ob.name, kind, time.time() - t0))
        return [ca.data[i].color[0] for i in range(len(ob.data.vertices))]
    baked = {}
    for ob, key in ((terr, "bake_terrain"), (trk, "bake_track")):
        sh = bake(ob, "SHADOW", "Shadow"); ao = bake(ob, "AO", "AO")
        baked[key] = "".join("%02x%02x" % (int(max(0, min(1, sh[i])) * 255), int(max(0, min(1, ao[i])) * 255)) for i in range(len(sh)))
        L("%s: shadow mean %.3f ao mean %.3f" % (key, sum(sh) / len(sh), sum(ao) / len(ao)))
    # ---- trailside assets
    PAL = {"rockedge": ["6F736C", "7E827A", "5E7A4C", "6E8A56"], "startdeck": ["6A5238", "7A6044", "4E3C2A", "8A8178"], "sticks": ["5A4634", "6A5440", "4A3A2C"]}
    def merge(bm, part):
        m2 = bpy.data.meshes.new("tmp"); part.to_mesh(m2); part.free(); bm.from_mesh(m2); bpy.data.meshes.remove(m2)
    def build_rockedge():
        bm = bmesh.new()
        for i in range(6):
            part = bmesh.new(); r = 0.14 + 0.12 * random.random()
            bmesh.ops.create_icosphere(part, subdivisions=1, radius=r)
            for v in part.verts:
                v.co += Vector((noise.noise(v.co * 3 + Vector((i, 2, 5))) * 0.05,) * 3); v.co.z = v.co.z * 0.7 + r * 0.55
                v.co.x += -0.7 + i * 0.28 + 0.05 * random.random(); v.co.y += 0.06 * (random.random() - 0.5)
            for f in part.faces:
                c = f.calc_center_median(); up = f.normal.z
                f.material_index = (2 if noise.noise(c * 4) < 0.1 else 3) if (up > 0.4 and noise.noise(c * 2.5) > 0.0) else (0 if up < 0.6 else 1)
            merge(bm, part)
        return bm
    def build_startdeck():
        bm = bmesh.new()
        def box(sx, sy, sz, cx, cy, cz, mat):
            part = bmesh.new(); bmesh.ops.create_cube(part, size=1.0); bmesh.ops.scale(part, vec=(sx, sy, sz), verts=part.verts); bmesh.ops.translate(part, vec=(cx, cy, cz), verts=part.verts)
            for f in part.faces: f.material_index = mat
            merge(bm, part)
        for k in range(9): box(0.24, 2.4, 0.04, -1.0 + k * 0.25, 0, 0.62, 0 if k % 2 else 1)      # deck boards across
        for yy in (-1.1, 0, 1.1): box(2.3, 0.09, 0.14, 0, yy, 0.52, 2)                            # joists
        for xx, yy in ((-1.05, -1.1), (-1.05, 1.1), (1.05, -1.1), (1.05, 1.1), (0, -1.1), (0, 1.1)): box(0.1, 0.1, 0.5, xx, yy, 0.25, 2)   # posts
        for k in range(3): box(0.28, 2.4, 0.035, 1.35 + k * 0.3, 0, 0.62 - (k + 1) * 0.16, 0)   # steps down the front
        box(2.3, 0.05, 0.6, 0, -1.22, 0.95, 3); box(2.3, 0.05, 0.6, 0, 1.22, 0.95, 3)          # rails
        return bm
    def build_sticks():
        bm = bmesh.new()
        for i in range(7):
            part = bmesh.new(); a = random.random() * 6.28; ln = 0.35 + 0.6 * random.random()
            bmesh.ops.create_cone(part, cap_ends=True, segments=5, radius1=0.018 + 0.012 * random.random(), radius2=0.008, depth=ln)
            bmesh.ops.rotate(part, cent=(0, 0, 0), matrix=Euler((math.radians(90 - 8 * random.random()), 0, a)).to_matrix(), verts=part.verts)
            bmesh.ops.translate(part, vec=((random.random() - 0.5) * 1.2, (random.random() - 0.5) * 1.2, 0.02), verts=part.verts)
            for f in part.faces: f.material_index = random.choice([0, 1, 1, 2])
            merge(bm, part)
        return bm
    def fib(k):
        return [Vector((math.cos(i * 2.399963) * math.sqrt(1 - ((i + .5) / k) ** 2), math.sin(i * 2.399963) * math.sqrt(1 - ((i + .5) / k) ** 2), (i + .5) / k)) for i in range(k)]
    RAYS = fib(20); outj = dict(baked)
    for name, fn, loc in (("rockedge", build_rockedge, (66, 0, 0)), ("startdeck", build_startdeck, (70, 0, 0)), ("sticks", build_sticks, (74, 0, 0))):
        o0 = bpy.data.objects.get(name)
        if o0: bpy.data.objects.remove(o0, do_unlink=True)
        bm = fn(); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bmesh.ops.triangulate(bm, faces=bm.faces)
        me2 = bpy.data.meshes.new(name); bm.to_mesh(me2); bm.free(); ob = bpy.data.objects.new(name, me2)
        for h in PAL[name]:
            mt = bpy.data.materials.get(name + "_" + h) or bpy.data.materials.new(name + "_" + h); ob.data.materials.append(mt)
        ob.location = loc; lib.objects.link(ob); ob.hide_render = True; ob.hide_viewport = False
        bpy.context.view_layer.update()
        me2.calc_loop_triangles(); bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get()); verts = me2.vertices; ao = []
        for v in verts:
            nrm = v.normal.normalized() if v.normal.length > 1e-6 else Vector((0, 0, 1)); up = Vector((0, 0, 1)) if abs(nrm.z) < 0.95 else Vector((1, 0, 0))
            tx = nrm.cross(up).normalized(); ty = nrm.cross(tx); occ = 0
            for dd in RAYS:
                if bvh.ray_cast(v.co + nrm * 0.015, (tx * dd.x + ty * dd.y + nrm * dd.z).normalized(), 4.0)[0] is not None: occ += 1
            ao.append(1 - occ / len(RAYS))
        hexes = PAL[name]; V, T, C = [], [], []; cols = [None] * len(verts)
        for v in verts: V += [round(v.co.x, 3), round(v.co.z, 3), round(-v.co.y, 3)]
        for tri in me2.loop_triangles:
            h = hexes[min(tri.material_index, len(hexes) - 1)]; base = (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255); T += list(tri.vertices)
            for vi in tri.vertices:
                if cols[vi] is None: a = 0.45 + 0.55 * ao[vi]; cols[vi] = tuple(min(1, ch * a) for ch in base)
        for c in cols: c = c or (0.5, 0.5, 0.5); C.append("%02x%02x%02x" % tuple(int(ch * 255) for ch in c))
        outj[name] = {"v": V, "t": T, "c": C}; L("asset %s %dv" % (name, len(verts)))
    with open(SCR + r"\pnw_assets_v5.json", "w") as f: json.dump(outj, f, separators=(",", ":"))
    ob_hide = [o for o in pump.objects if o.name.startswith("i_")]
    L("DONE")

try: main()
except Exception: L("ERROR\n" + traceback.format_exc())
log.close()
print(open(SCR + r"\live_v5.log").read()[-1500:])
