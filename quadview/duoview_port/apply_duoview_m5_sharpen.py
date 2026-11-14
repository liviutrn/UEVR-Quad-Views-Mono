#!/usr/bin/env python3
"""DuoView M5 (Claude, 14 Nov 2026): six per-eye sharpening sliders.

Liviu's layout: max sharpness L/R, normal sharpen L/R, wide sharpen L/R; no
link/unlink toggles (0 = off). Distance-faded sharpening (toggle + 4 sliders)
stays as it is. The existing Settings fields are derived from the six sliders
in the freeze, so every downstream path keeps its own math:
  normal L/R -> m2_left/right_sharpen (always per-eye), sharpen_strength=max(L,R)
  wide L/R   -> m23_left/right_wide (always per-eye), sharpen_wide=(L>0||R>0)
  max L/R    -> new per-eye limiter in the stereo raster; sharpen_max_change=max(L,R)
Old link/unlink and linked-strength controls are hidden (keys kept, ignored).

Run after apply_duoview_m4_fovea.py. Every edit is exact-once.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def shaders(sh):
    patch(sh/"DuoViewGlamaryeFovea.hlsl", [
        ("M5 per-eye limiter (0 = use the shared SharpenMaxChange)",
         "float3 GlamSharpenNativeFovea(float2 fullUv, float3 center, float strength) {",
         "static float GlamEyeMaxChange = -1.0; // M5: set per eye by the stereo raster\n"
         "float GlamMaxChange() { return GlamEyeMaxChange >= 0.0 ? GlamEyeMaxChange : SharpenMaxChange; }\n"
         "float3 GlamSharpenNativeFovea(float2 fullUv, float3 center, float strength) {"),
        ("M5 normal sharpen limiter",
         "    possible = clamp(possible, 0.00001, SharpenMaxChange);",
         "    possible = clamp(possible, 0.00001, max(.00001,GlamMaxChange()));"),
        ("M5 wide sharpen limiter",
         "    possible = clamp(possible,.00001,SharpenMaxChange);",
         "    possible = clamp(possible,.00001,max(.00001,GlamMaxChange()));"),
    ])
    patch(sh/"DuoViewM1Stereo.hlsl", [
        ("M5 constants",
         "    float4 M4Flags; // x: on, y/z: shared-grid texels per fovea texel (x/y), w: read blend band (crop-local)\n};",
         "    float4 M4Flags; // x: on, y/z: shared-grid texels per fovea texel (x/y), w: read blend band (crop-local)\n"
         "    float4 M5Sharpen; // x/y: left/right max change (negative = shared SharpenMaxChange)\n};"),
    ])
    patch(sh/"DuoViewNativeCompositeRaster.hlsl", [
        ("M5 select this eye's limiter",
         "        const bool rightEye=i.pos.x>=OutputSize.x;\n",
         "        const bool rightEye=i.pos.x>=OutputSize.x;\n"
         "        GlamEyeMaxChange=rightEye ? M5Sharpen.y : M5Sharpen.x;\n"),
        ("M5 zero per-eye limit disables both passes",
         "        if (DebugViewMode == 0 &&\n            (fineSharpen > 0.0",
         "        if (DebugViewMode == 0 && GlamMaxChange()>0.0 &&\n            (fineSharpen > 0.0"),
    ])


def backend(mods):
    vr = mods/"vr"
    patch(vr/"DuoViewM1D3D12.hpp", [
        ("M5 constants",
         "    float m4_flags[4]{};   // on, x/y texel ratios, read blend band\n};\nstatic_assert(sizeof(M1Constants) == 352);",
         "    float m4_flags[4]{};   // on, x/y texel ratios, read blend band\n"
         "    float m5_sharpen[4]{}; // left/right max change (negative = shared)\n"
         "};\nstatic_assert(sizeof(M1Constants) == 368);"),
        ("M5 writer parameters (defaulted: fixtures keep their call)",
         "D3D12_CPU_DESCRIPTOR_HANDLE focus_srv, bool m4_fovea_grid=false) {",
         "D3D12_CPU_DESCRIPTOR_HANDLE focus_srv, bool m4_fovea_grid=false,\n"
         "                         float left_max_change=.10f, float right_max_change=.10f) {"),
        ("M5 per-eye limiter values",
         "        void* address{};\n        const D3D12_RANGE no_read{0,0};",
         "        if(std::isfinite(left_max_change))\n"
         "            data.m5_sharpen[0]=(std::clamp)(left_max_change,0.f,.80f);\n"
         "        if(std::isfinite(right_max_change))\n"
         "            data.m5_sharpen[1]=(std::clamp)(right_max_change,0.f,.80f);\n"
         "        void* address{};\n        const D3D12_RANGE no_read{0,0};"),
    ])
    patch(vr/"DuoViewD3D12.hpp", [
        ("M5 writer receives per-eye limits",
         "m1_raw_srv_,m2_fovea_srv_,settings.m4_fovea_grid);",
         "m1_raw_srv_,m2_fovea_srv_,settings.m4_fovea_grid,\n"
         "                settings.m5_left_max,settings.m5_right_max);"),
    ])
    patch(vr/"DuoViewConfig.hpp", [
        ("M5 settings",
         "    bool m4_fovea_grid{false}; // M4: fovea keeps its own full-resolution depth field\n",
         "    bool m4_fovea_grid{false}; // M4: fovea keeps its own full-resolution depth field\n"
         "    float m5_left_max{.10f}, m5_right_max{.10f}; // M5: per-eye sharpen limiter\n"),
        ("M5 validate",
         "    out.m4_fovea_grid=requested.m4_fovea_grid;\n",
         "    out.m4_fovea_grid=requested.m4_fovea_grid;\n"
         "    if(std::isfinite(requested.m5_left_max)) out.m5_left_max=(std::clamp)(requested.m5_left_max,0.f,.80f);\n"
         "    if(std::isfinite(requested.m5_right_max)) out.m5_right_max=(std::clamp)(requested.m5_right_max,0.f,.80f);\n"),
    ])
    patch(mods/"VR.hpp", [
        ("M5 wide left default off",
         'generate_name("DuoM23WideLeft"),0.f,20.f,1.f)',
         'generate_name("DuoM23WideLeft"),0.f,20.f,0.f)'),
        ("M5 wide right default off",
         'generate_name("DuoM23WideRight"),0.f,20.f,1.f)',
         'generate_name("DuoM23WideRight"),0.f,20.f,0.f)'),
        ("M5 options",
         '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n',
         '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n'
         '    const ModSlider::Ptr m_duo_m5_left_max{ModSlider::create(generate_name("DuoM5LeftMaxSharpness"),0.f,0.80f,0.10f)};\n'
         '    const ModSlider::Ptr m_duo_m5_right_max{ModSlider::create(generate_name("DuoM5RightMaxSharpness"),0.f,0.80f,0.10f)};\n'),
        ("M5 persist",
         "*m_duo_m4_fovea_grid, ",
         "*m_duo_m4_fovea_grid, *m_duo_m5_left_max, *m_duo_m5_right_max, "),
    ])
    patch(mods/"VR.cpp", [
        ("M5 wide reset off",
         "m_duo_m23_wide_left->value()=1.f; m_duo_m23_wide_right->value()=1.f;",
         "m_duo_m23_wide_left->value()=0.f; m_duo_m23_wide_right->value()=0.f;"),
        ("M5 defaults",
         "                    m_duo_m4_fovea_grid->value()=false;\n",
         "                    m_duo_m4_fovea_grid->value()=false;\n"
         "                    m_duo_m5_left_max->value()=.10f; m_duo_m5_right_max->value()=.10f;\n"),
        ("M5 derived linked values",
         ".sharpen_strength=m_duo_sharpen->value(), .sharpen_max_change=m_duo_sharpen_max->value(),",
         ".sharpen_strength=(std::max)(m_duo_m2_left->value(),m_duo_m2_right->value()),"
         " .sharpen_max_change=(std::max)({.05f,m_duo_m5_left_max->value(),m_duo_m5_right_max->value()}),"),
        ("M5 wide on when either eye > 0",
         "        .sharpen_wide=m_duo_sharpen_wide->value(),\n",
         "        .sharpen_wide=m_duo_m23_wide_left->value()>0.f || m_duo_m23_wide_right->value()>0.f,\n"),
        ("M5 freeze (declaration order: right after m4_fovea_grid)",
         "        .m4_fovea_grid=m_duo_m4_fovea_grid->value(),\n",
         "        .m4_fovea_grid=m_duo_m4_fovea_grid->value(),\n"
         "        .m5_left_max=m_duo_m5_left_max->value(),\n"
         "        .m5_right_max=m_duo_m5_right_max->value(),\n"),
        ("M5 always per-eye",
         "        .m23_wide_unlinked=m_duo_m23_unlinked_wide->value(),\n"
         "        .m23_wide_strength=m_duo_m23_wide->value(),\n",
         "        .m23_wide_unlinked=true,\n"
         "        .m23_wide_strength=(std::max)(m_duo_m23_wide_left->value(),m_duo_m23_wide_right->value()),\n"),
        ("M5 always per-eye normal",
         "        .m2_unlinked_sharpen=m_duo_m2_unlinked->value(),\n",
         "        .m2_unlinked_sharpen=true,\n"),
        ("M5 equality",
         "        current.m4_fovea_grid==candidate.m4_fovea_grid &&\n",
         "        current.m4_fovea_grid==candidate.m4_fovea_grid &&\n"
         "        current.m5_left_max==candidate.m5_left_max &&\n"
         "        current.m5_right_max==candidate.m5_right_max &&\n"),
        ("M5 six-slider menu",
         """                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                m_duo_sharpen_max->draw("Glamarye fovea max change (0.05-0.80; higher risks halos)");
                m_duo_sharpen_wide->draw("Extra-wide sharpen ring (OFF by default; 1.5x regular radius)");
                if (m_duo_sharpen_wide->value()) {
                    m_duo_m23_wide->draw("Wide sharpen strength (independent of regular)");
                    m_duo_m23_unlinked_wide->draw("Separate left/right wide sharpen");
                    if (m_duo_m23_unlinked_wide->value()) {
                        m_duo_m23_wide_left->draw("Left eye wide sharpen strength");
                        m_duo_m23_wide_right->draw("Right eye wide sharpen strength");
                    }
                }
                if (m_duo_stereo->value()) {
                    m_duo_m2_unlinked->draw("Separate left/right sharpening (synthetic stereo)");
                    if (m_duo_m2_unlinked->value()) {
                        m_duo_m2_left->draw("Left eye sharpen");
                        m_duo_m2_right->draw("Right eye sharpen");
                    }
                    m_duo_m24_distance->draw("Distance-faded sharpening (synthetic stereo)");
""",
         """                ImGui::TextWrapped("Sharpening, per eye (0 = off):");
                m_duo_m5_left_max->draw("Left eye max sharpness (per-pixel limit; higher risks halos)");
                m_duo_m5_right_max->draw("Right eye max sharpness (per-pixel limit; higher risks halos)");
                m_duo_m2_left->draw("Left eye normal sharpen");
                m_duo_m2_right->draw("Right eye normal sharpen");
                m_duo_m23_wide_left->draw("Left eye wide sharpen (1.5x radius)");
                m_duo_m23_wide_right->draw("Right eye wide sharpen (1.5x radius)");
                {
                    m_duo_m24_distance->draw("Distance-faded sharpening");
"""),
    ])


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_m5_sharpen.py <backend> <shaders>")
    shaders(Path(sys.argv[2]))
    backend(Path(sys.argv[1])/"src/mods")
    print("M5: six per-eye sharpening sliders, distance fade kept")


if __name__ == "__main__":
    main()
