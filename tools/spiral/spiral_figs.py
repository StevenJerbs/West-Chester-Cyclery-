"""Figures from spiral_sweep.json: (1) net gain vs radius per technique, trough / crest / berm, Earth and zero-g;
(2) the rotation itself: rider radius r, angular momentum L, energy E and leg work W along the arc, trough vs berm;
(3) the force lean angle and leg force through the arc."""
import json, math
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os; SCR = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(SCR + r"\spiral_sweep.json"))
BG, PANEL, INK, DIM, LINE = "#23261E", "#2F3328", "#EFE8D6", "#A39F88", "#484D3C"
COL = {"curve": "#8DBF6A", "slope": "#D9A441", "passive": "#D4784E", "rigid": "#B07BC2"}
LAB = {"curve": "push in the curve", "slope": "push on the slope", "passive": "passive", "rigid": "rigid"}
plt.rcParams.update({"font.family": "monospace", "text.color": INK, "axes.labelcolor": INK, "xtick.color": DIM, "ytick.color": DIM, "axes.edgecolor": LINE, "axes.facecolor": PANEL, "figure.facecolor": BG, "savefig.facecolor": BG, "legend.facecolor": PANEL, "legend.edgecolor": LINE, "axes.grid": True, "grid.color": LINE, "grid.alpha": 0.5})

# ---- figure 1: gain vs radius, 6 panels (3 scenes x Earth/zero-g), at 10 mph; dashed at 14 mph
fig, axs = plt.subplots(2, 3, figsize=(15, 8), sharex=True)
for gi, g in enumerate(["earth", "zerog"]):
    for si, sc in enumerate(["trough", "crest", "berm"]):
        ax = axs[gi, si]
        for t in ["curve", "slope", "passive", "rigid"]:
            for v, ls in ((10, "-"), (14, "--")):
                ys = [D["grid"][f"{g}/{sc}/{t}"][f"{R}@{v}"][0] for R in D["radii"]]
                st = [D["grid"][f"{g}/{sc}/{t}"][f"{R}@{v}"][3] for R in D["radii"]]
                ys = [y if not s_ else float("nan") for y, s_ in zip(ys, st)]
                ax.plot(D["radii"], ys, ls, color=COL[t], lw=2 if v == 10 else 1.2, label=(LAB[t] + (" · 10 mph" if v == 10 else " · 14 mph")) if (gi == 0 and si == 0) else None)
        ax.axhline(0, color=INK, lw=0.8, alpha=0.5)
        ax.set_title({"trough": "TROUGH", "crest": "CREST (push = pull toward the centre below)", "berm": "BERM (top view, no gravity in the plane)"}[sc] + ("" if g == "earth" else "  ·  ZERO-G TRACK"), fontsize=10, color=INK)
        if gi == 1: ax.set_xlabel("radius of curvature R (m)")
        if si == 0: ax.set_ylabel("net gain at entry height and posture (mph)")
axs[0, 0].legend(fontsize=8, ncol=2, loc="upper right")
fig.suptitle("Spiral Lab sweep: what the same 30 cm leg stroke is worth, by where and how it is spent (68 kg rider, 17 kg V10)", color=INK, fontsize=12)
fig.tight_layout(); fig.savefig(SCR + r"\spiral_fig1_gain_vs_radius.png", dpi=130); plt.close(fig)

# ---- figure 2: the rotation on the arc: r, L, E, W vs distance, trough (Earth) vs berm vs trough zero-g, push in the curve with rigid ghost
fig, axs = plt.subplots(3, 4, figsize=(17, 10))
rows = [("trough_curve", "trough_rigid", "TROUGH · Earth · push in the curve vs rigid"), ("trough_curve_zerog", None, "TROUGH · zero-g track · push in the curve (L exact)"), ("berm_curve", "berm_rigid", "BERM · push in the curve vs rigid")]
for ri, (nm, ghost, title) in enumerate(rows):
    tr = D["traces"][nm]; T = tr["trace"]; s0, s3 = tr["arc"]
    s = [p[0] for p in T]; r = [p[1] for p in T]; L = [p[2] for p in T]; E = [p[3] for p in T]; W = [p[4] for p in T]; Lc = [p[10] for p in T]
    G = D["traces"][ghost]["trace"] if ghost else None
    for ci, (ys, yl, extra) in enumerate([(r, "rider's radius from the centre r (m)", [p[1] for p in G] if G else None), (Lc if nm != "berm_curve" else L, "L about the centre (kg·m²/s)" + ("" if nm.startswith("berm") or "zerog" in nm else ", gravity's share removed"), [p[2] for p in G] if G else None), (E, "total mechanical energy E (J)", [p[3] for p in G] if G else None), (W, "leg work W (J)", [p[4] for p in G] if G else None)]):
        ax = axs[ri, ci]; ax.axvspan(s0, s3, color=INK, alpha=0.06)
        if extra is not None: ax.plot([p[0] for p in G], extra, color=COL["rigid"], lw=1.4, ls="--", label="rigid")
        ax.plot(s, ys, color=COL["curve"], lw=2, label="push in the curve")
        ax.set_ylabel(yl, fontsize=8)
        if ri == 2: ax.set_xlabel("distance along the path s (m)")
        if ci == 0: ax.set_title(title, fontsize=9, loc="left", color=INK)
        if ri == 0 and ci == 0: ax.legend(fontsize=8)
fig.suptitle("The rotation, in numbers: the rider's mass moves in toward the centre (r falls), L about the centre holds, E rises by exactly the leg work", color=INK, fontsize=11)
fig.tight_layout(); fig.savefig(SCR + r"\spiral_fig2_rotation_traces.png", dpi=130); plt.close(fig)

# ---- figure 3: the spiral geometry: lead angle and leg force through the arc, all techniques (trough, Earth)
fig, axs = plt.subplots(1, 3, figsize=(15, 4.6))
for t in ["curve", "slope", "passive", "rigid"]:
    T = D["traces"]["trough_" + t]["trace"]; s0, s3 = D["traces"]["trough_" + t]["arc"]
    axs[0].plot([p[0] for p in T], [p[6] for p in T], color=COL[t], lw=1.8, label=LAB[t])
    axs[1].plot([p[0] for p in T], [p[5] for p in T], color=COL[t], lw=1.8)
    axs[2].plot([p[0] for p in T], [p[7] for p in T], color=COL[t], lw=1.8)
for ax, yl in zip(axs, ["force leads velocity by (°): + means the radial push is doing work", "leg force (× body weight)", "bike speed (mph)"]):
    ax.axvspan(s0, s3, color=INK, alpha=0.06); ax.set_ylabel(yl, fontsize=8); ax.set_xlabel("distance along the path s (m)")
axs[0].axhline(0, color=INK, lw=0.8, alpha=0.5); axs[0].legend(fontsize=8)
fig.suptitle("Why the mass speeds up: on a spiral the radial leg force is no longer at right angles to the motion (trough, 6 m, 10 mph in)", color=INK, fontsize=11)
fig.tight_layout(); fig.savefig(SCR + r"\spiral_fig3_lean_angle.png", dpi=130); plt.close(fig)
print("figures written")
