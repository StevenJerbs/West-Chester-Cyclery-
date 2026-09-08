# Trail render pipeline (Suspension Lab -> Blender)

1. Serve the repo (`python -m http.server 8734`) and run `receiver.py <out.json>` on port 8735.
2. Open suspension-lab.html and run in the console:
   `fetch('http://127.0.0.1:8735/world', {method:'POST', body: JSON.stringify(WORLD_EXPORT())})`
   -> terrain, trail ribbon, obstacles, flora placements and the path land in world.json (~7 MB).
3. `build_trail.py` (run inside live Blender via blender-mcp, or headless) rebuilds the world: vertex-coloured
   terrain + ribbon, obstacle meshes, one instance per flora placement of the PNW library objects, three
   feature cameras. Saves ladies_only.blend.
4. `render_final.py` (headless: `blender --background ladies_only.blend --python render_final.py`) sets the
   look -- marine-layer world, warm soft sun, mist-pass fog via the Blender 5 node-group compositor
   (ShaderNodeMix, NodeGroupOutput), -28% foliage saturation -- and renders the stills.
5. `render_fly.py` renders a chase-camera flythrough (24 fps, 6 m/s) to fly/frame_####.png; assemble with
   `ffmpeg -framerate 24 -i fly/frame_%04d.png -c:v libx264 -pix_fmt yuv420p ladies_only_fly.mp4`.

Notes: the Microsoft Store Blender exposes only `blender-launcher.exe`, which detaches and swallows stdout --
every script writes its own log file. A world Volume Scatter renders black in EEVEE at this scene scale; use
the mist pass. Rendering from inside the MCP socket handler produces black frames; render headless from the
saved .blend instead.

## Simulated run (Suspension Lab physics -> Blender)

6. `ladies_only_lap.js` runs the Suspension Lab physics headlessly in Node (`sed -n '271,857p' suspension-lab.html > susp_base.js`
   first; the sliders are stubbed with their defaults) for one lap of the Ladies Only-inspired course and writes
   `ladies_only_run_<rider>.json`: a 30 fps trajectory (trail distance, speed, chassis height and pitch, fork and rear
   travel, rider hips/torso/state, crank, lean, brake, airborne, wheel heights) plus per-segment stats and the path.
7. `render_run.py` (headless: `blender-launcher -b ladies_only_final.blend --python render_run.py`) keys a bike + rider
   proxy and a chase camera from that trajectory and renders the descent at 1280x720, 24 fps to run/frame_####.png;
   assemble with `ffmpeg -framerate 24 -i run/frame_%04d.png -c:v libx264 -crf 22 -pix_fmt yuv420p ladies_only_run.mp4`.
