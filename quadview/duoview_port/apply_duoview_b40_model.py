#!/usr/bin/env python3
"""DuoView Mono B40: guarded generated config/UI/HLSL model overlay.
Runs AFTER Phase2 and all TriView B43 scripts. ID7 is not edited.
Part 2 (apply_duoview_b40_pipeline.py) supplies persistent GPU queue history.
"""
from pathlib import Path
import sys

def once(s,old,new,label):
    n=s.count(old)
    if n!=1: raise RuntimeError(f"B40 Mono {label}: anchor found {n}, expected one: {old[:110]!r}")
    return s.replace(old,new,1)

def patch(path,ops):
    s=path.read_text(encoding="utf-8-sig")
    for label,old,new in ops:
        s=once(s,old,new,label)
    path.write_text(s,encoding="utf-8",newline="\n")

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_b40_model.py <backend> <workspace-duoview>")
    root=Path(sys.argv[1]); src=Path(sys.argv[2])
    cfg=root/"src/mods/vr/DuoViewConfig.hpp"
    patch(cfg,[
        ("B40 new fields",
         "    float seam_strength{.75f}, seam_limit{.25f}, seam_reach_px{80.f};\n"
         "    float seam_inward_px{64.f}, seam_color_strength{};",
         "    float seam_strength{.85f}, seam_limit{.25f}, seam_reach_px{240.f};\n"
         "    float seam_inward_px{12.f}, seam_color_strength{1.f};\n"
         "    float seam_ambient_radius_px{48.f}, seam_ambient_inside_px{32.f};\n"
         "    uint32_t seam_time_ms{350u};"),
        ("reject additional B40 settings",
         "reject_seam_inward=1u<<26, reject_seam_color=1u<<27",
         "reject_seam_inward=1u<<26, reject_seam_color=1u<<27,\n"
         "    reject_ambient_radius=1u<<28, reject_ambient_inside=1u<<29, reject_seam_time=1u<<30"),
        ("outward radius range",
         "scalar(requested.seam_reach_px,8.f,192.f,reject_seam_reach,&Settings::seam_reach_px);",
         "scalar(requested.seam_reach_px,16.f,1024.f,reject_seam_reach,&Settings::seam_reach_px);"),
        ("B38 inward anchor range",
         "scalar(requested.seam_inward_px,8.f,192.f,reject_seam_inward,&Settings::seam_inward_px);",
         "scalar(requested.seam_inward_px,2.f,64.f,reject_seam_inward,&Settings::seam_inward_px);"),
        ("B40 sampling/time reconciliation",
         "    scalar(requested.seam_color_strength,0.f,1.f,reject_seam_color,&Settings::seam_color_strength);",
         "    scalar(requested.seam_color_strength,0.f,1.f,reject_seam_color,&Settings::seam_color_strength);\n"
         "    scalar(requested.seam_ambient_radius_px,8.f,128.f,reject_ambient_radius,&Settings::seam_ambient_radius_px);\n"
         "    scalar(requested.seam_ambient_inside_px,8.f,96.f,reject_ambient_inside,&Settings::seam_ambient_inside_px);\n"
         "    unsigned_int(requested.seam_time_ms,50u,1500u,reject_seam_time,&Settings::seam_time_ms);"),
        ("outward range latch",
         "proposed.seam_reach_px<8.f || proposed.seam_reach_px>192.f",
         "proposed.seam_reach_px<16.f || proposed.seam_reach_px>1024.f"),
        ("B38 range latch",
         "proposed.seam_inward_px<8.f || proposed.seam_inward_px>192.f",
         "proposed.seam_inward_px<2.f || proposed.seam_inward_px>64.f"),
        ("B40 sampler/time latch",
         "proposed.seam_color_strength<0.f || proposed.seam_color_strength>1.f ||",
         "proposed.seam_color_strength<0.f || proposed.seam_color_strength>1.f ||\n"
         "             !std::isfinite(proposed.seam_ambient_radius_px) || proposed.seam_ambient_radius_px<8.f || proposed.seam_ambient_radius_px>128.f ||\n"
         "             !std::isfinite(proposed.seam_ambient_inside_px) || proposed.seam_ambient_inside_px<8.f || proposed.seam_ambient_inside_px>96.f ||\n"
         "             proposed.seam_time_ms<50u || proposed.seam_time_ms>1500u ||"),
    ])
    vrh=root/"src/mods/VR.hpp"
    patch(vrh,[
        ("strength default", 'ModSlider::create(generate_name("DuoViewSeamStrength"), 0.f, 1.f, .75f)',
         'ModSlider::create(generate_name("DuoViewSeamStrength"), 0.f, 1.f, .85f)'),
        ("outward default", 'ModSlider::create(generate_name("DuoViewSeamOutwardReachPx"), 8.f, 192.f, 80.f)',
         'ModSlider::create(generate_name("DuoViewSeamOutwardReachPx"), 16.f, 1024.f, 240.f)'),
        ("B38 default", 'ModSlider::create(generate_name("DuoViewSeamInwardFeatherPx"), 8.f, 192.f, 64.f)',
         'ModSlider::create(generate_name("DuoViewSeamInwardFeatherPx"), 2.f, 64.f, 12.f)'),
        ("full RGB default and B40 UI controls",
         '    const ModSlider::Ptr m_duo_seam_color{ModSlider::create(generate_name("DuoViewSeamColorStrength"), 0.f, 1.f, 0.f)};',
         '    const ModSlider::Ptr m_duo_seam_color{ModSlider::create(generate_name("DuoViewSeamColorStrength"), 0.f, 1.f, 1.f)};\n'
         '    const ModSlider::Ptr m_duo_b40_radius{ModSlider::create(generate_name("DuoViewB40AmbientRadiusPx"), 8.f, 128.f, 48.f)};\n'
         '    const ModSlider::Ptr m_duo_b40_inside{ModSlider::create(generate_name("DuoViewB40AmbientInsidePx"), 8.f, 96.f, 32.f)};\n'
         '    const ModCombo::Ptr m_duo_b40_preset{ModCombo::create(generate_name("DuoViewB40TemporalPreset"), s_quadview_b40_presets, 2)};'),
        ("saved settings",
         "            *m_duo_seam_reach, *m_duo_seam_inward, *m_duo_seam_color,",
         "            *m_duo_seam_reach, *m_duo_seam_inward, *m_duo_seam_color,\n"
         "            *m_duo_b40_radius, *m_duo_b40_inside, *m_duo_b40_preset,"),
    ])
    vrc=root/"src/mods/VR.cpp"
    patch(vrc,[
        ("reset B40 defaults",
         "m_duo_seam_match->value()=false; m_duo_seam_strength->value()=.75f;\n"
         "                    m_duo_seam_limit->value()=.25f; m_duo_seam_reach->value()=80.f;\n"
         "                    m_duo_seam_inward->value()=64.f; m_duo_seam_color->value()=0.f;",
         "m_duo_seam_match->value()=false; m_duo_seam_strength->value()=.85f;\n"
         "                    m_duo_seam_limit->value()=.25f; m_duo_seam_reach->value()=240.f;\n"
         "                    m_duo_seam_inward->value()=12.f; m_duo_seam_color->value()=1.f;\n"
         "                    m_duo_b40_radius->value()=48.f; m_duo_b40_inside->value()=32.f;\n"
         "                    m_duo_b40_preset->value()=2;"),
        ("actual B40 controls",
         '                    m_duo_seam_limit->draw("Max automatic seam gain");\n'
         '                    m_duo_seam_reach->draw("Outside crop matching reach (pixels)");\n'
         '                    m_duo_seam_inward->draw("Inward blended feather (pixels)");\n'
         '                    m_duo_seam_color->draw("Color matching (0=brightness-only, 1=RGB)");',
         '                    m_duo_seam_reach->draw("B40 outward reach (240 px default)");\n'
         '                    m_duo_seam_inward->draw("B38 inward raw-context anchor (12 px default)");\n'
         '                    m_duo_seam_color->draw("B40 RGB correction (1=exact RGB, 0=brightness only)");\n'
         '                    m_duo_b40_radius->draw("B40 spatial radius along edge (48 px)");\n'
         '                    m_duo_b40_inside->draw("B40 interior sampling depth (32 px)");\n'
         '                    m_duo_b40_preset->draw("B40 temporal 0=Fast 75ms / 1=Balanced 200ms / 2=High 350ms / 3=Maximum 600ms");'),
        ("correct old prototype description",
         '                ImGui::TextWrapped("DuoView seam is mono-specific: four spatial edge groups reject strong outliers, with no temporal history or resets. Off leaves the v208d blend unchanged. This is NOT the TriView B40 temporal seam pipeline.");',
         '                ImGui::TextWrapped("Mono B40 continuous seam: 32 knots x four spatial centers x 15 probes, RGB-trimmed outliers, queue-owned persistent GPU EMA. No gaze/scene/epoch resets. The same B40 temporal smoothing as TriView (one Mono image instead of two eyes). No extra correction with seam OFF.");'),
        ("candidate B40 values",
         "        .seam_color_strength=m_duo_seam_color->value(), ",
         "        .seam_color_strength=m_duo_seam_color->value(),\n"
         "        .seam_ambient_radius_px=m_duo_b40_radius->value(),\n"
         "        .seam_ambient_inside_px=m_duo_b40_inside->value(),\n"
         "        .seam_time_ms=m_duo_b40_preset->value()==0 ? 75u :\n"
         "                      m_duo_b40_preset->value()==1 ? 200u :\n"
         "                      m_duo_b40_preset->value()==3 ? 600u : 350u, "),
        ("settings change-detection",
         "        current.seam_color_strength==candidate.seam_color_strength &&",
         "        current.seam_color_strength==candidate.seam_color_strength &&\n"
         "        current.seam_ambient_radius_px==candidate.seam_ambient_radius_px &&\n"
         "        current.seam_ambient_inside_px==candidate.seam_ambient_inside_px &&\n"
         "        current.seam_time_ms==candidate.seam_time_ms &&"),
        ("B40 controls rejection",
         '{uevr::duoview::reject_seam_color,"Seam color mix"},',
         '{uevr::duoview::reject_seam_color,"Seam color mix"},\n'
         '                        {uevr::duoview::reject_ambient_radius,"B40 spatial radius"},\n'
         '                        {uevr::duoview::reject_ambient_inside,"B40 sampling depth"},\n'
         '                        {uevr::duoview::reject_seam_time,"B40 temporal preset"},'),
    ])
    common=src/"DuoViewComposite.hlsl"
    patch(common,[
        ("B40 temporal cbuffer", "    float4 SeamGeometry;      // outward px, inward feather px, colour mix, reserved",
         "    float4 SeamGeometry;      // outward px, inward anchor px, RGB mix, spatial radius px\n"
         "    uint4 B40Temporal;       // monotonic ms, EMA time constant, history enabled, reserved\n"
         "    float4 B40EyeSharpen;   // exact displayed non-wide L/R sharpen reference"),
        ("B38 restore original v208d feather",
         "    [branch] if (SeamOptions.x > .5 && SeamGeometry.y > 0.0) {\n"
         "        const float2 edgePx = min(fullUv - CropUv.xy, CropUv.zw - fullUv) * float2(OutputSize);\n"
         "        const float inner = saturate(min(edgePx.x, edgePx.y) / SeamGeometry.y);\n"
         "        return inner * inner * (3.0 - 2.0 * inner);\n"
         "    }\n", ""),
    ])
    native=src/"DuoViewNativeCompositeRaster.hlsl"
    patch(native,[
        ("keep B38 unmodified context",
         '    if (DebugViewMode == 0 && weight < 1.0 && SeamOptions.x > .5)\n'
         '        periphery.rgb = DuoPhase2MatchContext(fullUv, periphery.rgb);',
         '    const float4 rawPeriphery = periphery;\n'
         '    if (DebugViewMode == 0 && weight < 1.0 && SeamOptions.x > .5)\n'
         '        periphery.rgb = DuoPhase2MatchContext(fullUv, periphery.rgb);'),
        ("B38 restore inward raw-context feather",
         "        result = DebugViewMode == 2 ? fovea : lerp(periphery,fovea,weight);",
         "        const float4 blendPeriphery = SeamOptions.x > .5\n"
         "            ? lerp(rawPeriphery,periphery,DuoB40InwardAnchor(fullUv)) : periphery;\n"
         "        result = DebugViewMode == 2 ? fovea : lerp(blendPeriphery,fovea,weight);"),
    ])
    gather=src/"DuoViewCompositeRaster.hlsl"
    patch(gather,[
        ("retain uncorrected gather context",
         "    float4 peripheralColor = SourceAtlas.SampleLevel(LinearClamp, peripheralSample, 0.0);\n",
         "    float4 peripheralColor = SourceAtlas.SampleLevel(LinearClamp, peripheralSample, 0.0);\n"
         "    const float4 rawPeripheralColor = peripheralColor;\n"),
        ("B38 gather inward original raw context",
         "        result = DebugViewMode == 2 ? foveaColor : lerp(peripheralColor, foveaColor, weight);",
         "        const float4 blendPeripheral = SeamOptions.x > .5\n"
         "            ? lerp(rawPeripheralColor,peripheralColor,DuoB40InwardAnchor(fullUv)) : peripheralColor;\n"
         "        result = DebugViewMode == 2 ? foveaColor : lerp(blendPeripheral, foveaColor, weight);"),
    ])
    helper=Path(__file__).with_name("DuoViewB40Mono.hlsl")
    if not helper.is_file(): raise RuntimeError("Missing real B40 shader source")
    (src/"DuoViewPhase2Effects.hlsl").write_text(helper.read_text(encoding="utf-8"),
          encoding="utf-8",newline="\n")
    print("DuoView B40 controls + 128x15 shader: pinned B43 untouched, prototype replaced")

if __name__=="__main__":
    main()
