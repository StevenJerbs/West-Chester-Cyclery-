"""Headless (blender-launcher -b ladies_only_final.blend --python render_run.py): animate Goldstone's simulated lap of the
Ladies Only-inspired course from ladies_only_run_pro.json (Suspension Lab physics, 30 fps trajectory) with a bike + rider
proxy, chase camera, and render the descent to run/frame_####.png at 24 fps. Every step logs; exceptions land in the log."""
import bpy, json, math, time, traceback
from mathutils import Vector, Euler, Quaternion
SCR = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw"
log = open(SCR + r"\render_run.log", "w")
def L(m): log.write(m + "\n"); log.flush()

def main():
    R = json.load(open(SCR + r"\ladies_only_run_pro.json"))
    cols = {c: i for i, c in enumerate(R["columns"])}
    traj = R["traj"]; pts = R["path"]["pts"]; ds = R["path"]["ds"]; gs = R["groundSamples"]; course = {g["name"]: g for g in R["course"]}
    L("loaded: %d frames, %d path pts, lap %.1f s" % (len(traj), len(pts), R["lapTime"]))
    Y = lambda x, y, z: Vector((x, -z, y))                                   # three.js Y-up -> Blender Z-up
    N = len(pts); CL = R["courseLen"]
    def path_at(s):
        sp = s % CL; f = sp / ds; i = int(f) % N; j = (i + 1) % N; t = f - i
        x = pts[i][0] + (pts[j][0] - pts[i][0]) * t; z = pts[i][1] + (pts[j][1] - pts[i][1]) * t
        th0 = pts[i][2]; th1 = pts[j][2]
        while th1 - th0 > math.pi: th1 -= 2 * math.pi
        while th1 - th0 < -math.pi: th1 += 2 * math.pi
        return x, z, th0 + (th1 - th0) * t
    def ground_at(s):
        sp = s % CL; f = sp / 0.25; i = int(f) % len(gs); j = (i + 1) % len(gs); t = f - i
        return gs[i] + (gs[j] - gs[i]) * t
    # ---- window: the descent proper (drop-in to finish), interpolated to 24 fps
    FPS = 24; s0 = course["OFF THE FIREROAD"]["start"] - 3; s1 = course["FINISH"]["start"] + course["FINISH"]["len"]
    tS = R["fps"]
    def row_at(t):
        f = t * tS; i = max(0, min(len(traj) - 2, int(f))); u = f - i; a, b = traj[i], traj[i + 1]
        out = []
        for k in range(len(a)):
            if isinstance(a[k], str): out.append(a[k] if u < 0.5 else b[k])
            else: out.append(a[k] + (b[k] - a[k]) * u)
        return out
    t_start = next(r[0] for r in traj if r[cols["s"]] >= s0); t_end = next((r[0] for r in traj if r[cols["s"]] >= s1), traj[-1][0])
    n_frames = int((t_end - t_start) * FPS)
    L("window s %.1f..%.1f  t %.2f..%.2f  frames %d" % (s0, s1, t_start, t_end, n_frames))

    sc = bpy.context.scene
    geo = R["geo"]; rF, rR, wb, cs = geo["rF"], geo["rR"], geo["wb"], geo["cs"]
    # ---- materials
    def mat(name, hexc, rough=0.6, metal=0.0):
        m = bpy.data.materials.get(name)
        if m: return m
        m = bpy.data.materials.new(name); m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        rr, gg, bb = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
        b.inputs["Base Color"].default_value = (rr ** 2.2, gg ** 2.2, bb ** 2.2, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
        return m
    m_frame, m_blue, m_tire, m_rim, m_gold, m_jersey, m_pants, m_skin, m_helmet = (mat("v10_frame", "14161C", 0.35), mat("v10_blue", "1F3B7A", 0.4), mat("tire", "2B2622", 0.9),
        mat("rim", "1C1C1C", 0.5, 0.4), mat("fork_gold", "C8952A", 0.35, 0.6), mat("jersey", "1F3B7A", 0.8), mat("pants", "15161A", 0.8), mat("skin", "D8AA80", 0.7), mat("helmet", "F2F2F0", 0.3))
    col = bpy.data.collections.new("RUN"); sc.collection.children.link(col)
    def cyl(name, r, m):
        bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=1.0, vertices=12); ob = bpy.context.active_object; ob.name = name; ob.data.materials.append(m)
        for c in ob.users_collection: c.objects.unlink(ob)
        col.objects.link(ob); return ob
    def torus(name, R_, r_, m):
        bpy.ops.mesh.primitive_torus_add(major_radius=R_, minor_radius=r_, major_segments=28, minor_segments=8); ob = bpy.context.active_object; ob.name = name; ob.data.materials.append(m)
        for c in ob.users_collection: c.objects.unlink(ob)
        col.objects.link(ob); return ob
    def sphere(name, r, m):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=16, ring_count=10); ob = bpy.context.active_object; ob.name = name; ob.data.materials.append(m)
        for c in ob.users_collection: c.objects.unlink(ob)
        col.objects.link(ob); return ob
    parts = {}
    for nm, m in (("downtube", m_frame), ("toptube", m_frame), ("seattube", m_blue), ("stays", m_frame), ("fork", m_gold), ("bar", m_frame), ("torso", m_jersey), ("uarm", m_jersey), ("larm", m_jersey), ("thigh", m_pants), ("shin", m_pants)):
        parts[nm] = cyl(nm, {"downtube": 0.035, "toptube": 0.028, "seattube": 0.028, "stays": 0.022, "fork": 0.02, "bar": 0.016, "torso": 0.11, "uarm": 0.045, "larm": 0.04, "thigh": 0.07, "shin": 0.055}[nm], m)
    parts["wF"] = torus("wheelF", rF - 0.03, 0.032, m_tire); parts["wR"] = torus("wheelR", rR - 0.03, 0.032, m_tire)
    parts["rimF"] = torus("rimF", rF - 0.075, 0.012, m_rim); parts["rimR"] = torus("rimR", rR - 0.075, 0.012, m_rim)
    parts["head"] = sphere("head", 0.12, m_helmet); parts["shadow"] = None
    L("proxy built")
    def aim(ob, a, b, fr):
        d = b - a; ln = max(d.length, 1e-3)
        ob.location = (a + b) / 2; ob.scale = (1, 1, ln)
        ob.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
        ob.keyframe_insert("location", frame=fr); ob.keyframe_insert("rotation_euler", frame=fr); ob.keyframe_insert("scale", frame=fr)
    def place(ob, p, rot, fr, scale=None):
        ob.location = p; ob.rotation_euler = rot
        ob.keyframe_insert("location", frame=fr); ob.keyframe_insert("rotation_euler", frame=fr)
    cam_d = bpy.data.cameras.new("RunCam"); cam_d.lens = 26
    cam = bpy.data.objects.new("RunCam", cam_d); col.objects.link(cam); sc.camera = cam
    sc.frame_start, sc.frame_end = 1, n_frames
    prev_cam = None; prev_look = None
    for fr in range(1, n_frames + 1):
        t = t_start + (fr - 1) / FPS
        r = row_at(t)
        s = r[cols["s"]]; phi = r[cols["phi"]]; lean = r[cols["lean"]]; cy = r[cols["chassisY"]]
        px, pz, th = path_at(s); gy = ground_at(s)
        # frame axes in world (three.js): forward along the tangent, up; pitch phi about the lateral axis, roll lean about forward
        fwd = Vector((math.cos(th), 0, math.sin(th))); up = Vector((0, 1, 0)); right = Vector((-math.sin(th), 0, math.cos(th)))
        cp, sp = math.cos(phi), math.sin(phi); cl, sl = math.cos(lean), math.sin(lean)
        def W(x, y):                                                              # frame-local (x fwd, y up) -> world (three), with pitch and roll about the trail point
            X = x * cp - y * sp; Yl = x * sp + y * cp
            base = Vector((px, gy, pz)); v = fwd * X + up * (Yl * cl) + right * (Yl * -sl) + up * (cy - gy)
            return base + v
        axF = W(wb - cs, r[cols["wheelFy"]] - cy); axR = W(-cs, r[cols["wheelRy"]] - cy)
        # keep the axles at the physics' world heights (the frame-local pitch already moved them): overwrite y from the record
        axF = Vector((axF.x, r[cols["wheelFy"]], axF.z)); axR = Vector((axR.x, r[cols["wheelRy"]], axR.z))
        bb = W(0, 0); head_top = W(0.447, 0.668); seat = W(-0.12, 0.42); bar = W(0.52, 0.72)
        hips = W(r[cols["hipX"]], r[cols["hipY"]] + r[cols["riderU"]]); tor = math.radians(r[cols["torsoDeg"]])
        sh = W(r[cols["hipX"]] + 0.5 * math.cos(tor), r[cols["hipY"]] + r[cols["riderU"]] + 0.5 * math.sin(tor))
        hd = W(r[cols["hipX"]] + 0.5 * math.cos(tor) + 0.17 * math.cos(tor + 0.61), r[cols["hipY"]] + r[cols["riderU"]] + 0.5 * math.sin(tor) + 0.17 * math.sin(tor + 0.61))
        crank = r[cols["crank"]]; pedal = W(math.sin(crank) * 0.165, math.cos(crank) * 0.165 - 0.02)
        knee = (hips + pedal) / 2 + fwd * 0.18 + up * 0.05; elbow = (sh + bar) / 2 + up * -0.12 + right * 0.2
        B = lambda v: Y(v.x, v.y, v.z)
        aim(parts["downtube"], B(head_top - fwd * 0.05 - up * 0.1), B(bb), fr); aim(parts["toptube"], B(head_top), B(seat), fr); aim(parts["seattube"], B(bb + up * 0.05), B(seat), fr)
        aim(parts["stays"], B(seat), B(axR), fr); aim(parts["fork"], B(head_top), B(axF), fr); aim(parts["bar"], B(bar + right * 0.38), B(bar - right * 0.38), fr)
        aim(parts["torso"], B(hips), B(sh), fr); aim(parts["uarm"], B(sh + right * 0.16), B(elbow), fr); aim(parts["larm"], B(elbow), B(bar + right * 0.3), fr)
        aim(parts["thigh"], B(hips + right * 0.1), B(knee), fr); aim(parts["shin"], B(knee), B(pedal + right * 0.14), fr)
        wrot = Euler((math.radians(90) - 0, 0, -th), "XYZ")
        # wheel spin: the torus' local Z is its axle after the 90° tilt; spin about it
        spin = -s / rF
        for nm, ax, rr in (("wF", axF, rF), ("rimF", axF, rF), ("wR", axR, rR), ("rimR", axR, rR)):
            ob = parts[nm]; q = Quaternion((0, 0, 1), -th) @ Quaternion((1, 0, 0), math.radians(90)) @ Quaternion((0, 0, 1), s / rr)
            ob.rotation_mode = "QUATERNION"; ob.location = B(ax); ob.rotation_quaternion = q
            ob.keyframe_insert("location", frame=fr); ob.keyframe_insert("rotation_quaternion", frame=fr)
        place(parts["head"], B(hd), Euler((0, 0, -th)), fr)
        # chase camera: behind-right, above, looking a little ahead of the rider; smoothed
        camp = B(bb - fwd * 5.2 + up * 2.3 + right * 1.6); look = B(bb + fwd * 2.0 + up * 0.9)
        if prev_cam is not None: camp = prev_cam.lerp(camp, 0.18); look = prev_look.lerp(look, 0.3)
        prev_cam, prev_look = camp, look
        cam.location = camp; cam.rotation_euler = (look - camp).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=fr); cam.keyframe_insert("rotation_euler", frame=fr)
        if fr % 200 == 0: L("keyed %d/%d" % (fr, n_frames))
    L("animation keyed")
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1280, 720, 100
    sc.render.fps = FPS
    try: sc.eevee.taa_render_samples = 16
    except Exception: pass
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = SCR + r"\run\frame_"
    bpy.ops.wm.save_as_mainfile(filepath=SCR + r"\ladies_only_run.blend")
    L("saved blend, rendering %d frames" % n_frames)
    t0 = time.time()
    bpy.ops.render.render(animation=True)
    L("DONE %d frames in %.0f s" % (n_frames, time.time() - t0))

try: main()
except Exception:
    L("ERROR\n" + traceback.format_exc())
log.close()
