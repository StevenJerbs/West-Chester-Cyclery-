"""Headless final look for the trail scene: plain marine-layer world, warm soft sun, mist-pass fog in the
compositor, tamed foliage saturation; save ladies_only_final.blend and render the three feature stills.
Every step logs, and any exception lands in the log with a traceback."""
import bpy, math, time, traceback
from mathutils import Euler
SCR = r"C:\Users\nadc7\AppData\Local\Temp\claude\C--Users-nadc7\58e7389b-2193-48bd-9c6a-3da658d2b283\scratchpad\pnw"
log = open(SCR + r"\render_final.log", "w")
def L(msg):
    log.write(msg + "\n"); log.flush()

def main():
    sc = bpy.context.scene
    L("start, blender %s" % bpy.app.version_string)

    w = sc.world; w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld"); bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs[0].default_value = (0.46, 0.55, 0.50, 1); bg.inputs[1].default_value = 1.0
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    w.mist_settings.start = 10.0; w.mist_settings.depth = 95.0; w.mist_settings.falloff = "QUADRATIC"
    L("world ok")

    for o in list(sc.objects):
        if o.type == "LIGHT": bpy.data.objects.remove(o, do_unlink=True)
    ld = bpy.data.lights.new("Sun_PNW", "SUN"); ld.energy = 3.4; ld.angle = math.radians(7); ld.color = (1.0, 0.96, 0.88)
    lo = bpy.data.objects.new("Sun_PNW", ld); sc.collection.objects.link(lo); lo.rotation_euler = Euler((math.radians(58), 0, math.radians(-42)))
    L("sun ok")

    n_mat = 0
    for m in bpy.data.materials:
        if not m.name.startswith("pnw_") or not m.use_nodes: continue
        b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None: continue
        if "Specular IOR Level" in b.inputs: b.inputs["Specular IOR Level"].default_value = 0.15
        parts = m.name.split("_")
        if len(parts) > 1 and parts[1] in ("cedar", "cedar3", "fir", "hemlock", "maple", "fern", "salal", "snag"):
            c = list(b.inputs["Base Color"].default_value)
            lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
            b.inputs["Base Color"].default_value = tuple(lum + (ch - lum) * 0.72 for ch in c[:3]) + (1.0,)
            b.inputs["Roughness"].default_value = 0.95
            n_mat += 1
    L("materials ok (%d foliage desaturated)" % n_mat)

    vl = sc.view_layers[0]; vl.use_pass_mist = True
    try:
        if hasattr(sc, "compositing_node_group"):                       # Blender 5.x: compositor is a node group
            ng = bpy.data.node_groups.new("PNW_comp", "CompositorNodeTree"); sc.compositing_node_group = ng
            ct = ng
        else:
            sc.use_nodes = True; ct = sc.node_tree
        ct.nodes.clear()
        rl = ct.nodes.new("CompositorNodeRLayers")
        try: rl.scene = sc
        except Exception: pass
        mix_type = "CompositorNodeMixRGB" if hasattr(bpy.types, "CompositorNodeMixRGB") else "CompositorNodeMix"
        mix = ct.nodes.new(mix_type)
        try: mix.blend_type = "MIX"
        except Exception: pass
        L("mix node %s inputs %s outputs %s" % (mix_type, [(i.name, i.type) for i in mix.inputs], [(o.name, o.enabled) for o in mix.outputs]))
        fac_in = mix.inputs[0]
        cols = [i for i in mix.inputs[1:] if i.type in ("RGBA", "COLOR")]
        if len(cols) < 2:
            cols = [i for i in mix.inputs[1:] if i.enabled][:2]
        img_a, img_b = cols[0], cols[1]
        img_b.default_value = (0.50, 0.59, 0.54, 1.0)
        ramp = ct.nodes.new("CompositorNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
        ramp.color_ramp.elements[1].position = 1.0; ramp.color_ramp.elements[1].color = (0.82, 0.82, 0.82, 1)
        ct.links.new(rl.outputs["Mist"], ramp.inputs["Fac"])
        ct.links.new(ramp.outputs["Color"], fac_in)
        ct.links.new(rl.outputs["Image"], img_a)
        out_sock = next(o for o in mix.outputs if o.enabled)
        if hasattr(bpy.types, "CompositorNodeComposite"):
            comp = ct.nodes.new("CompositorNodeComposite"); ct.links.new(out_sock, comp.inputs[0])
        else:
            ct.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            go = ct.nodes.new("NodeGroupOutput"); ct.links.new(out_sock, go.inputs[0])
        L("compositor ok (%s)" % mix_type)
    except Exception:
        L("compositor FAILED, rendering without fog:\n" + traceback.format_exc())
        try: sc.compositing_node_group = None
        except Exception: pass
        try: sc.use_nodes = False
        except Exception: pass

    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
    sc.render.film_transparent = False
    try: sc.eevee.taa_render_samples = 48
    except Exception as e: L("samples: %s" % e)
    for attr, val in (("use_shadows", True), ("use_gtao", True), ("use_raytracing", True)):
        try: setattr(sc.eevee, attr, val)
        except Exception: pass
    vts = [i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items]
    sc.view_settings.view_transform = "AgX" if "AgX" in vts else "Filmic"
    try: sc.view_settings.look = "AgX - Medium High Contrast" if sc.view_settings.view_transform == "AgX" else "Medium High Contrast"
    except Exception as e: L("look: %s" % e)
    sc.view_settings.exposure = 0.15
    bpy.ops.wm.save_as_mainfile(filepath=SCR + r"\ladies_only_final.blend")
    L("saved final blend; view %s" % sc.view_settings.view_transform)
    for name in ("Cam_Staircase", "Cam_Ladder", "Cam_RockRoll"):
        sc.camera = bpy.data.objects[name]
        sc.render.filepath = SCR + "\\final_" + name[4:].lower() + ".png"
        t0 = time.time(); bpy.ops.render.render(write_still=True)
        L("rendered %s %.1f s" % (name, time.time() - t0))

try:
    main()
except Exception:
    L("ERROR\n" + traceback.format_exc())
L("DONE"); log.close()
