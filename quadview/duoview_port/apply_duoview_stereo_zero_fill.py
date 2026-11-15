"""B318 stereo cleanup A: skip work with mathematically zero M8 foveal fill.

Apply *after* the B318 source-fit overlay. Exact guarded anchors intentionally fail
if an earlier production overlay changes; never patch a stale generated postimage.
"""
from pathlib import Path
import sys


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 anchor, got {count}")
    return text.replace(old, new, 1)


def apply(backend: Path, shaders: Path):
    path = shaders / "DuoViewM1Stereo.hlsl"
    src = path.read_text(encoding="utf-8")
    src = replace_once(src,
        """        [branch] if(inCrop || (M3Flags.x>.5 && M3Flags.z>0.0))
            uv.x=M3FillHole(base.x,uv.x,base.y,k,eye,fill,inCrop);""",
        """        // M8 with both background-fill endpoints zero is identically zero
        // at every distance. Avoid even the depth probes that precede the
        // 32-step search; preserve legacy periphery fill when M3 is active.
        const bool foveaFillEnabled=M8Distance.z<=.5 ||
            M8Effects.z>0.0 || M8Effects.w>0.0;
        [branch] if((inCrop && foveaFillEnabled) ||
                    (!inCrop && M3Flags.x>.5 && M3Flags.z>0.0))
            uv.x=M3FillHole(base.x,uv.x,base.y,k,eye,fill,inCrop);""",
        "M1PullUv fill search gate")
    path.write_text(src, encoding="utf-8")

    path = backend / "src/mods/vr/DuoViewD3D12.hpp"
    src = path.read_text(encoding="utf-8")
    src = replace_once(src,
        """        const bool write_history=settings.synthetic_stereo && settings.m4_fovea_grid &&
            settings.m21_depth_debug==0 && (settings.edge_history>0.f || settings.fill_history>0.f) &&""",
        """        // The M8 zero-fill endpoints preclude ALL foveal background-color
        // consumers, but must not suppress unrelated temporal edge history.
        const bool no_fovea_fill=settings.m8_distance &&
            settings.m8_fill_near==0.f && settings.m8_fill_far==0.f;
        const float fill_history_effective=no_fovea_fill ? 0.f : settings.fill_history;
        const float fill_blur_effective=no_fovea_fill ? 0.f : settings.fill_blur_px;
        const bool write_history=settings.synthetic_stereo && settings.m4_fovea_grid &&
            settings.m21_depth_debug==0 && (settings.edge_history>0.f || fill_history_effective>0.f) &&""",
        "M7 history policy")
    src = replace_once(src,
        """                settings.edge_history,settings.fill_history,settings.fill_blur_px,
                settings.edge_reach_px,color_extent,""",
        """                settings.edge_history,fill_history_effective,fill_blur_effective,
                settings.edge_reach_px,color_extent,""",
        "M7 effective controls")
    src = replace_once(src,
        """        const auto fovea_sample_state=history_output && settings.fill_history>0.f""",
        """        const auto fovea_sample_state=history_output && fill_history_effective>0.f""",
        "M7 color source state")
    path.write_text(src, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: apply_duoview_stereo_zero_fill.py <backend> <shaders>")
    apply(Path(sys.argv[1]), Path(sys.argv[2]))
    print("stereo cleanup A: zero-fill search/color-history work gated")
