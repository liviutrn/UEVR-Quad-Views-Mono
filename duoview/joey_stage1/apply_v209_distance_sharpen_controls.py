#!/usr/bin/env python3
"""V209: stage validated in-game distance controls, without hooking unproven depth.

Called after the v208 range-only patch; leaves the shader, GPU resources,
view geometry, gaze, frame delivery and all non-DuoView rendering untouched.
Controls intentionally do NOT alter the live fixed-strength shader yet.
"""
from pathlib import Path
import sys


def replace_once(text, before, after, name):
    n = text.count(before)
    if n != 1:
        raise RuntimeError(f"{name}: expected exactly one v208 anchor; found {n}: {before[:90]!r}")
    return text.replace(before, after, 1)


def apply(root, source):
    names = ("src/mods/VR.hpp", "src/mods/VR.cpp", "src/mods/vr/DuoViewConfig.hpp")
    edited = {name: (root / name).read_text(encoding="utf-8-sig") for name in names}

    def edit(name, before, after):
        edited[name] = replace_once(edited[name], before, after, name)

    cfg = "src/mods/vr/DuoViewConfig.hpp"
    vrh = "src/mods/VR.hpp"
    vrc = "src/mods/VR.cpp"

    edit(cfg, '#include "DuoViewGaze.hpp"',
         '#include "DuoViewGaze.hpp"\n#include "DuoViewDistanceCurve.hpp"')
    edit(cfg, "    // v207: Catmull-Rom (bicubic) upscaling of the low-resolution periphery.",
         """    // v209 staged controls. The live shader deliberately still uses fixed strength.
    bool distance_sharpen_enabled{false};
    float sharpen_near_strength{5.f}, sharpen_far_strength{1.f};
    float sharpen_near_m{.5f}, sharpen_far_m{10.f};
    bool sharpen_distance_smooth{true};
    // v207: Catmull-Rom (bicubic) upscaling of the low-resolution periphery.""")
    edit(cfg, "    reject_sharpen=1u<<17",
         """    reject_sharpen=1u<<17, reject_sharpen_near=1u<<18,
    reject_sharpen_far=1u<<19, reject_sharpen_distance=1u<<20""")
    edit(cfg, "    out.sharp_periphery=requested.sharp_periphery;",
         """    out.sharp_periphery=requested.sharp_periphery;
    out.distance_sharpen_enabled=requested.distance_sharpen_enabled;
    out.sharpen_distance_smooth=requested.sharpen_distance_smooth;""")
    edit(cfg, "    scalar(requested.sharpen_strength,0.f,5.f,reject_sharpen,&Settings::sharpen_strength);",
         """    scalar(requested.sharpen_strength,0.f,5.f,reject_sharpen,&Settings::sharpen_strength);
    scalar(requested.sharpen_near_strength,0.f,5.f,reject_sharpen_near,&Settings::sharpen_near_strength);
    scalar(requested.sharpen_far_strength,0.f,5.f,reject_sharpen_far,&Settings::sharpen_far_strength);
    if (valid_distance_sharpen_range(requested.sharpen_near_m, requested.sharpen_far_m)) {
        out.sharpen_near_m=requested.sharpen_near_m;
        out.sharpen_far_m=requested.sharpen_far_m;
    } else {
        result.rejected|=reject_sharpen_distance;
    }""")
    edit(cfg, "            proposed.sharpen_strength>5.f ||",
         """            proposed.sharpen_strength>5.f ||
            !std::isfinite(proposed.sharpen_near_strength) ||
            proposed.sharpen_near_strength<0.f || proposed.sharpen_near_strength>5.f ||
            !std::isfinite(proposed.sharpen_far_strength) ||
            proposed.sharpen_far_strength<0.f || proposed.sharpen_far_strength>5.f ||
            !valid_distance_sharpen_range(proposed.sharpen_near_m, proposed.sharpen_far_m) ||""")

    edit(vrh,
         '    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 5.f, 1.f)};',
         """    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 5.f, 1.f)};
    const ModToggle::Ptr m_duo_distance_enabled{ModToggle::create(generate_name("DuoViewDistanceSharpen"), false)};
    const ModSlider::Ptr m_duo_near_strength{ModSlider::create(generate_name("DuoViewNearSharpen"), 0.f, 5.f, 5.f)};
    const ModSlider::Ptr m_duo_far_strength{ModSlider::create(generate_name("DuoViewFarSharpen"), 0.f, 5.f, 1.f)};
    const ModSlider::Ptr m_duo_near_distance{ModSlider::create(generate_name("DuoViewNearSharpenMeters"), 0.f, 1000.f, .5f)};
    const ModSlider::Ptr m_duo_far_distance{ModSlider::create(generate_name("DuoViewFarSharpenMeters"), 0.f, 1000.f, 10.f)};
    const ModToggle::Ptr m_duo_distance_smooth{ModToggle::create(generate_name("DuoViewDistanceSmoothstep"), true)};""")
    edit(vrh, "            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze,",
         """            *m_duo_feather, *m_duo_sharpen, *m_duo_distance_enabled,
            *m_duo_near_strength, *m_duo_far_strength, *m_duo_near_distance,
            *m_duo_far_distance, *m_duo_distance_smooth, *m_duo_gaze,""")

    edit(vrc, "m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;",
         """m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;
                    m_duo_distance_enabled->value()=false;
                    m_duo_near_strength->value()=5.f; m_duo_far_strength->value()=1.f;
                    m_duo_near_distance->value()=.5f; m_duo_far_distance->value()=10.f;
                    m_duo_distance_smooth->value()=true;""")
    edit(vrc, '                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");',
         """                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                ImGui::TextWrapped("Distance sharpening v209: CONTROL STAGING ONLY. Depth is not yet connected; current fixed sharpening is always used.");
                m_duo_distance_enabled->draw("Future fovea distance sharpening (not yet applied)");
                m_duo_near_strength->draw("Future near sharpness (0-5)");
                m_duo_far_strength->draw("Future far sharpness (0-5)");
                m_duo_near_distance->draw("Future near distance (meters)");
                m_duo_far_distance->draw("Future far distance (meters; must exceed near)");
                m_duo_distance_smooth->draw("Future smooth transition (OFF = linear)");""")
    edit(vrc, "        .gaze_relock_samples=static_cast<uint32_t>(m_duo_relock->value()),\n        .sharp_periphery=",
         """        .gaze_relock_samples=static_cast<uint32_t>(m_duo_relock->value()),
        .distance_sharpen_enabled=m_duo_distance_enabled->value(),
        .sharpen_near_strength=m_duo_near_strength->value(),
        .sharpen_far_strength=m_duo_far_strength->value(),
        .sharpen_near_m=m_duo_near_distance->value(),
        .sharpen_far_m=m_duo_far_distance->value(),
        .sharpen_distance_smooth=m_duo_distance_smooth->value(),
        .sharp_periphery=""")

    new_header = root / "src/mods/vr/DuoViewDistanceCurve.hpp"
    if new_header.exists():
        raise RuntimeError("Refusing to replace an existing distance-curve module")
    src = (source / "DuoViewDistanceCurve.hpp").read_bytes()
    for name, text in edited.items():
        (root / name).write_text(text, encoding="utf-8", newline="")
    new_header.write_bytes(src)
    print("PASS: v209 controls are validated/latch-safe; live shader, depth and compositor unchanged")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_v209_distance_sharpen_controls.py <backend> <duoview-source>")
    apply(Path(sys.argv[1]), Path(sys.argv[2]))
