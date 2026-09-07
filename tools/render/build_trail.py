"""Live Blender: rebuild the Suspension Lab world (Ladies Only-inspired course) from world.json,
light it for a misty North Shore morning, place cameras on the signature features, save the .blend,
render three stills with EEVEE. three.js is Y-up: (x, y, z) -> Blender (x, -z, y)."""
import bpy, bmesh, json, math
from mathutils import Vector, Euler

SCR = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw"
W = json.load(open(SCR + r"\world.json"))
Y = lambda x, y, z: (x, -z, y)

# ---------------------------------------------------------------- collections
sc = bpy.context.scene
def coll(name, parent=None):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        (parent or sc.collection).children.link(c)
    return c
lib = coll("PNW")                         # the asset lineup, becomes instance source only
trail = coll("TRAIL")
for ob in list(trail.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
for ch in list(trail.children):
    for ob in list(ch.objects): bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.collections.remove(ch)
flora_c = coll("TRAIL_flora", trail)
# hide the library lineup from renders and viewport
for ob in lib.objects:
    ob.hide_render = True; ob.hide_viewport = True

# ---------------------------------------------------------------- vertex-coloured meshes
def vc_material(name, roughness, spec=0.5):
    m = bpy.data.materials.get(name)
    if m: return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    attr = nt.nodes.new("ShaderNodeVertexColor"); attr.layer_name = "Col"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = roughness
    return m

def mesh_from(name, pos, col, idx, mat):
    me = bpy.data.meshes.new(name)
    nv = len(pos) // 3
    verts = [Y(pos[i*3], pos[i*3+1], pos[i*3+2]) for i in range(nv)]
    faces = [(idx[i], idx[i+1], idx[i+2]) for i in range(0, len(idx), 3)]
    me.from_pydata(verts, [], faces)
    me.validate(); me.update()
    ca = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    for i in range(nv):
        r, g, b = col[i*3], col[i*3+1], col[i*3+2]
        ca.data[i].color = (r**2.2, g**2.2, b**2.2, 1.0)      # three.js linear-treated hex -> Blender linear
    me.materials.append(mat)
    for p in me.polygons: p.use_smooth = False
    ob = bpy.data.objects.new(name, me); trail.objects.link(ob); return ob

t = W["terrain"]; terr = mesh_from("Terrain", t["pos"], t["col"], t["idx"], vc_material("pnw_terrain", 0.95))
if W.get("ribbon"):
    r = W["ribbon"]; rib = mesh_from("TrailRibbon", r["pos"], r["col"], r["idx"], vc_material("pnw_ribbon", 0.62))

# ---------------------------------------------------------------- obstacles
def solid_material(name, hexc, rough=0.9):
    m = bpy.data.materials.get(name)
    if m: return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    rr, gg, bb = (int(hexc[i:i+2], 16) / 255 for i in (0, 2, 4))
    b.inputs["Base Color"].default_value = (rr**2.2, gg**2.2, bb**2.2, 1); b.inputs["Roughness"].default_value = rough
    return m
m_log, m_rock, m_shelf = solid_material("pnw_log", "4A3626"), solid_material("pnw_rock", "777D74"), solid_material("pnw_shelf", "5E655C")
for i, o in enumerate(W["obst"]):
    bm = bmesh.new()
    if o["type"] == "log":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=o["r"], radius2=o["r"] * 0.92, depth=2.8)
        mat = m_log; lift = o["r"]
    else:
        h = o["h"]; w = o["w"]; d = 1.9 if o["type"] == "rock" else 2.4
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts: v.co = Vector((v.co.x * w, v.co.y * d, v.co.z * h))
        mat = m_rock if o["type"] == "rock" else m_shelf; lift = h / 2 - 0.02
    me = bpy.data.meshes.new("obst_%d" % i); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    ob = bpy.data.objects.new("obst_%d_%s" % (i, o["type"]), me); trail.objects.link(ob)
    # three.js holder: position on trail, rotation.y = -theta; log cylinder axis was along local z (across the trail), plus yaw
    ob.location = Y(o["x"], o["y"] + lift, o["z"])
    th = o["theta"]
    if o["type"] == "log":
        # cylinder axis is Blender Z after create_cone; lay it flat across the trail
        ob.rotation_euler = Euler((math.pi / 2, 0, th + (o.get("yaw") or 0) + math.pi / 2), "XYZ")
    else:
        ob.rotation_euler = Euler((0, 0, th), "XYZ")

# ---------------------------------------------------------------- flora instances
srcs = {name: bpy.data.objects.get(name) for name in ["cedar", "cedar3", "fir", "hemlock", "maple", "snag", "fern", "salal", "boulder", "stump"]}
n_inst = 0
for name, places in W["flora"].items():
    src = srcs.get(name)
    if src is None: continue
    for k, p in enumerate(places):
        ob = bpy.data.objects.new("%s_%03d" % (name, k), src.data)
        ob.location = Y(p["x"], p["y"], p["z"])
        ob.rotation_euler = Euler((0, 0, -p.get("ry", 0)), "XYZ")
        ob.scale = (p.get("s", 1),) * 3
        flora_c.objects.link(ob); n_inst += 1

# ---------------------------------------------------------------- light, atmosphere, render settings
for ob in list(sc.objects):
    if ob.type == "LIGHT" and ob.name != "Sun_PNW": bpy.data.objects.remove(ob, do_unlink=True)
sun_d = bpy.data.lights.get("Sun_PNW") or bpy.data.lights.new("Sun_PNW", "SUN")
sun_d.energy = 2.6; sun_d.angle = math.radians(6); sun_d.color = (0.95, 0.97, 0.92)
sun = bpy.data.objects.get("Sun_PNW") or bpy.data.objects.new("Sun_PNW", sun_d)
if sun.name not in sc.collection.objects: sc.collection.objects.link(sun)
sun.rotation_euler = Euler((math.radians(52), 0, math.radians(-35)), "XYZ")
world = sc.world or bpy.data.worlds.new("PNW_World"); sc.world = world; world.use_nodes = True
wn = world.node_tree; wn.nodes.clear()
out = wn.nodes.new("ShaderNodeOutputWorld"); bg = wn.nodes.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.42, 0.50, 0.46, 1); bg.inputs["Strength"].default_value = 1.1
wn.links.new(bg.outputs[0], out.inputs["Surface"])
vol = wn.nodes.new("ShaderNodeVolumeScatter"); vol.inputs["Color"].default_value = (0.78, 0.84, 0.80, 1); vol.inputs["Density"].default_value = 0.010
wn.links.new(vol.outputs[0], out.inputs["Volume"])
engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = next((e for e in engines if "EEVEE" in e), engines[0])
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
sc.render.image_settings.file_format = "PNG"
ee = sc.eevee
for attr, val in (("taa_render_samples", 48), ("use_shadows", True), ("use_volumetric_shadows", True), ("volumetric_tile_size", "4")):
    try: setattr(ee, attr, val)
    except Exception: pass
sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
sc.view_settings.look = "AgX - Medium High Contrast" if sc.view_settings.view_transform == "AgX" else "Medium High Contrast"

# ---------------------------------------------------------------- cameras on the signature features
path = W["path"]; ds2 = 0.5                                     # path sampled every 2 x 0.25 m
course = {g["name"]: g for g in W["course"]}
def path_pt(s):
    i = max(0, min(len(path) - 1, int(s / ds2))); return Vector(Y(*path[i]))
def look_cam(name, s_cam, s_look, height, side=0.0):
    cam_d = bpy.data.cameras.get(name) or bpy.data.cameras.new(name); cam_d.lens = 28
    cam = bpy.data.objects.get(name) or bpy.data.objects.new(name, cam_d)
    if cam.name not in trail.objects: trail.objects.link(cam)
    p, q = path_pt(s_cam), path_pt(s_look)
    fwd = (q - p); fwd.z = 0; fwd.normalize(); right = Vector((fwd.y, -fwd.x, 0))
    cam.location = p + Vector((0, 0, height)) + right * side - fwd * 1.5
    tgt = q + Vector((0, 0, 0.6))
    cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    return cam
cams = [
    look_cam("Cam_Staircase", course["ROOT STAIRCASE 18%"]["start"] - 4.5, course["ROOT STAIRCASE 18%"]["start"] + 7, 2.4, 1.2),
    look_cam("Cam_Ladder", course["LADDER BRIDGE 1"]["start"] - 6, course["LADDER BRIDGE 1"]["start"] + 6, 2.0, -1.4),
    look_cam("Cam_RockRoll", course["ROCK ROLL 26%"]["start"] - 7, course["CATCH BERM R 28°"]["start"] + 3, 2.8, 1.6),
]
bpy.ops.wm.save_as_mainfile(filepath=SCR + r"\ladies_only.blend")
rendered = []
for cam in cams:
    sc.camera = cam
    sc.render.filepath = SCR + "\\render_" + cam.name[4:].lower() + ".png"
    bpy.ops.render.render(write_still=True)
    rendered.append(sc.render.filepath)
result = "engine=%s instances=%d obst=%d rendered=%s" % (sc.render.engine, n_inst, len(W["obst"]), rendered)
