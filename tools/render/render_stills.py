"""Headless: open ladies_only.blend (passed on the command line), report the scene, render the three feature cameras."""
import bpy, time
SCR = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw"
log = open(SCR + r"\render_stills.log", "w")
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
try: sc.eevee.taa_render_samples = 48
except Exception: pass
log.write("engine %s objects %d meshes %d cameras %s\n" % (sc.render.engine, len(sc.objects), sum(1 for o in sc.objects if o.type == "MESH"),
          [o.name for o in sc.objects if o.type == "CAMERA"])); log.flush()
trail = bpy.data.collections.get("TRAIL")
log.write("TRAIL objects %d, flora %d\n" % (len(trail.objects) if trail else -1, len(trail.children[0].objects) if trail and trail.children else -1)); log.flush()
for name in ("Cam_Staircase", "Cam_Ladder", "Cam_RockRoll"):
    cam = bpy.data.objects.get(name)
    if cam is None:
        log.write("missing camera %s\n" % name); continue
    sc.camera = cam
    sc.render.filepath = SCR + "\\render_" + name[4:].lower() + ".png"
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    log.write("rendered %s in %.1f s -> %s\n" % (name, time.time() - t0, sc.render.filepath)); log.flush()
log.write("DONE\n"); log.close()
