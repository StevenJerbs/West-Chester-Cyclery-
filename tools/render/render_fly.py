"""Headless: chase-camera flythrough of the Ladies Only-inspired course from ladies_only.blend.
Camera rides 1.6 m behind and 1.9 m above the trail line at a steady ground speed, looking 7 m ahead.
Frames -> fly/frame_####.png (ffmpeg assembles the mp4 afterwards)."""
import bpy, json, math, time
from mathutils import Vector
SCR = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw"
W = json.load(open(SCR + r"\world.json"))
Y = lambda x, y, z: Vector((x, -z, y))
path = [Y(*p) for p in W["path"]]                      # every 0.5 m of trail, at ground height
course = {g["name"]: g for g in W["course"]}
s_start, s_end = course["OFF THE FIREROAD"]["start"], course["SPRINT OUT"]["start"] + 6
FPS, SPEED = 24, 6.0                                    # m/s ~ 12 mph, the lab's pace through the tech
n_frames = int((s_end - s_start) / SPEED * FPS)
sc = bpy.context.scene
cam_d = bpy.data.cameras.new("FlyCam"); cam_d.lens = 24
cam = bpy.data.objects.new("FlyCam", cam_d); sc.collection.objects.link(cam); sc.camera = cam
def at(s):
    i = max(0, min(len(path) - 2, s / 0.5)); k = int(i); f = i - k
    return path[k].lerp(path[k + 1], f)
sc.frame_start, sc.frame_end = 1, n_frames
prev_rot = None
for fr in range(1, n_frames + 1):
    s = s_start + (fr - 1) / FPS * SPEED
    p, q = at(s), at(s + 7)
    fwd = (q - p); fwd.z = 0
    if fwd.length < 1e-3: fwd = Vector((1, 0, 0))
    fwd.normalize()
    loc = p - fwd * 1.6 + Vector((0, 0, 1.9))
    rot = (q + Vector((0, 0, 0.5)) - loc).to_track_quat("-Z", "Y").to_euler()
    if prev_rot is not None:                             # smooth the look direction
        rot = type(rot)([prev_rot[i] * 0.75 + rot[i] * 0.25 for i in range(3)])
    prev_rot = rot
    cam.location = loc; cam.rotation_euler = rot
    cam.keyframe_insert("location", frame=fr); cam.keyframe_insert("rotation_euler", frame=fr)
sc.render.resolution_x, sc.render.resolution_y = 1600, 900
try: sc.eevee.taa_render_samples = 24
except Exception: pass
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = SCR + r"\fly\frame_"
log = open(SCR + r"\render_fly.log", "w"); log.write("frames %d\n" % n_frames); log.flush()
t0 = time.time()
bpy.ops.render.render(animation=True)
log.write("DONE %d frames in %.0f s\n" % (n_frames, time.time() - t0)); log.close()
