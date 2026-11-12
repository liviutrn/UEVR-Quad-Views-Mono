#!/usr/bin/env python3
"""Opt-in DuoView Mono Phase 2 for B43; patch only ID6 generated backend.
Apply after all original DuoView/TriView scripts and defaults, before HLSL embed.
The pinned v208d subtree is left intact in Git; CI compiles the changed
workspace DuoView shader against the original Joey DX12 backend.
No new GPU allocations, temporal history, runtime shader compilation, or mode7 edits.
"""
from pathlib import Path
import sys

def once(s, old, new, label):
    hits = s.count(old)
    if hits != 1:
        raise RuntimeError(f"DuoView Phase2 {label}: expected one anchor, got {hits}: {old[:95]!r}")
    return s.replace(old, new, 1)

def edits(path, operations):
    s = path.read_text(encoding="utf-8-sig")
    for label, before, after in operations:
        s = once(s, before, after, label)
    path.write_text(s, encoding="utf-8", newline="\n")

def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_phase2.py <backend> <workspace-duoview>")
    root = Path(sys.argv[1])
    src = Path(sys.argv[2])
    helper = Path(__file__).with_name("DuoViewPhase2Effects.hlsl")
    if not helper.is_file():
        raise RuntimeError("Phase2 helper HLSL missing")
    if (src / "DuoViewPhase2Effects.hlsl").exists():
        raise RuntimeError("Phase2 already patched; refusing to compound the shader")
    # No changes to the pinned Git object: this is a CI working-tree overlay
    # after the v208d source hash verification and B43 source overlays.
    cfg = root / "src/mods/vr/DuoViewConfig.hpp"
    edits(cfg, [
        ("settings fields", "    bool debug_border{};",
         """    bool sharpen_wide{};
    bool focus_lift_enabled{};
    float focus_brightness{1.f}, focus_corner_gain{}, focus_onset{.35f}, focus_power{2.f};
    bool seam_match_enabled{};
    float seam_strength{.75f}, seam_limit{.25f}, seam_reach_px{80.f};
    float seam_inward_px{64.f}, seam_color_strength{};
    bool debug_border{};"""),
        ("reject masks", "    reject_sharpen=1u<<17, reject_sharpen_max=1u<<18",
         """    reject_sharpen=1u<<17, reject_sharpen_max=1u<<18,
    reject_focus_brightness=1u<<19, reject_focus_corner=1u<<20, reject_focus_onset=1u<<21,
    reject_focus_power=1u<<22, reject_seam_strength=1u<<23, reject_seam_limit=1u<<24,
    reject_seam_reach=1u<<25, reject_seam_inward=1u<<26, reject_seam_color=1u<<27"""),
        ("bool reconciliation", "    out.sharp_periphery=requested.sharp_periphery;",
         """    out.sharp_periphery=requested.sharp_periphery;
    out.sharpen_wide=requested.sharpen_wide;
    out.focus_lift_enabled=requested.focus_lift_enabled;
    out.seam_match_enabled=requested.seam_match_enabled;"""),
        ("extended strength", "scalar(requested.sharpen_strength,0.f,5.f,reject_sharpen",
         "scalar(requested.sharpen_strength,0.f,20.f,reject_sharpen"),
        ("extended max change", "scalar(requested.sharpen_max_change,.05f,.30f,reject_sharpen_max",
         "scalar(requested.sharpen_max_change,.05f,.80f,reject_sharpen_max"),
        ("new scalar reconciliation", "    scalar(requested.guard_fraction,0.f,.05f,reject_guard,&Settings::guard_fraction);",
         """    scalar(requested.focus_brightness,.5f,1.5f,reject_focus_brightness,&Settings::focus_brightness);
    scalar(requested.focus_corner_gain,0.f,.7f,reject_focus_corner,&Settings::focus_corner_gain);
    scalar(requested.focus_onset,0.f,.85f,reject_focus_onset,&Settings::focus_onset);
    scalar(requested.focus_power,.5f,5.f,reject_focus_power,&Settings::focus_power);
    scalar(requested.seam_strength,0.f,1.f,reject_seam_strength,&Settings::seam_strength);
    scalar(requested.seam_limit,0.f,.5f,reject_seam_limit,&Settings::seam_limit);
    scalar(requested.seam_reach_px,8.f,192.f,reject_seam_reach,&Settings::seam_reach_px);
    scalar(requested.seam_inward_px,8.f,192.f,reject_seam_inward,&Settings::seam_inward_px);
    scalar(requested.seam_color_strength,0.f,1.f,reject_seam_color,&Settings::seam_color_strength);
    scalar(requested.guard_fraction,0.f,.05f,reject_guard,&Settings::guard_fraction);"""),
        ("latch extended validation", "proposed.sharpen_strength>5.f ||",
         "proposed.sharpen_strength>20.f ||"),
        ("latch max validation", "proposed.sharpen_max_change<.05f || proposed.sharpen_max_change>.30f ||",
         """proposed.sharpen_max_change<.05f || proposed.sharpen_max_change>.80f ||
             !std::isfinite(proposed.focus_brightness) || proposed.focus_brightness<.5f || proposed.focus_brightness>1.5f ||
             !std::isfinite(proposed.focus_corner_gain) || proposed.focus_corner_gain<0.f || proposed.focus_corner_gain>.7f ||
             !std::isfinite(proposed.focus_onset) || proposed.focus_onset<0.f || proposed.focus_onset>.85f ||
             !std::isfinite(proposed.focus_power) || proposed.focus_power<.5f || proposed.focus_power>5.f ||
             !std::isfinite(proposed.seam_strength) || proposed.seam_strength<0.f || proposed.seam_strength>1.f ||
             !std::isfinite(proposed.seam_limit) || proposed.seam_limit<0.f || proposed.seam_limit>.5f ||
             !std::isfinite(proposed.seam_reach_px) || proposed.seam_reach_px<8.f || proposed.seam_reach_px>192.f ||
             !std::isfinite(proposed.seam_inward_px) || proposed.seam_inward_px<8.f || proposed.seam_inward_px>192.f ||
             !std::isfinite(proposed.seam_color_strength) || proposed.seam_color_strength<0.f || proposed.seam_color_strength>1.f ||"""),
    ])
    vrh = root / "src/mods/VR.hpp"
    edits(vrh, [
        ("strength range", 'ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 5.f, 1.f)',
         'ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 20.f, 1.f)'),
        ("change range and UI sliders",
         '    const ModSlider::Ptr m_duo_sharpen_max{ModSlider::create(generate_name("DuoViewGlamaryeFoveaMaxChange"), 0.05f, 0.30f, 0.10f)};',
         """    const ModSlider::Ptr m_duo_sharpen_max{ModSlider::create(generate_name("DuoViewGlamaryeFoveaMaxChange"), 0.05f, 0.80f, 0.10f)};
    const ModToggle::Ptr m_duo_sharpen_wide{ModToggle::create(generate_name("DuoViewGlamaryeExtraWide"), false)};
    const ModToggle::Ptr m_duo_focus_lift{ModToggle::create(generate_name("DuoViewFocusLift"), false)};
    const ModSlider::Ptr m_duo_focus_brightness{ModSlider::create(generate_name("DuoViewFocusBrightness"), .5f, 1.5f, 1.f)};
    const ModSlider::Ptr m_duo_focus_corner{ModSlider::create(generate_name("DuoViewFocusCornerGain"), 0.f, .7f, 0.f)};
    const ModSlider::Ptr m_duo_focus_onset{ModSlider::create(generate_name("DuoViewFocusLiftOnset"), 0.f, .85f, .35f)};
    const ModSlider::Ptr m_duo_focus_power{ModSlider::create(generate_name("DuoViewFocusLiftPower"), .5f, 5.f, 2.f)};
    const ModToggle::Ptr m_duo_seam_match{ModToggle::create(generate_name("DuoViewSeamMatch"), false)};
    const ModSlider::Ptr m_duo_seam_strength{ModSlider::create(generate_name("DuoViewSeamStrength"), 0.f, 1.f, .75f)};
    const ModSlider::Ptr m_duo_seam_limit{ModSlider::create(generate_name("DuoViewSeamMaxGain"), 0.f, .5f, .25f)};
    const ModSlider::Ptr m_duo_seam_reach{ModSlider::create(generate_name("DuoViewSeamOutwardReachPx"), 8.f, 192.f, 80.f)};
    const ModSlider::Ptr m_duo_seam_inward{ModSlider::create(generate_name("DuoViewSeamInwardFeatherPx"), 8.f, 192.f, 64.f)};
    const ModSlider::Ptr m_duo_seam_color{ModSlider::create(generate_name("DuoViewSeamColorStrength"), 0.f, 1.f, 0.f)};"""),
        ("persist new controls", "            *m_duo_sharpen_max,",
         """            *m_duo_sharpen_max, *m_duo_sharpen_wide, *m_duo_focus_lift,
            *m_duo_focus_brightness, *m_duo_focus_corner, *m_duo_focus_onset, *m_duo_focus_power,
            *m_duo_seam_match, *m_duo_seam_strength, *m_duo_seam_limit,
            *m_duo_seam_reach, *m_duo_seam_inward, *m_duo_seam_color,"""),
    ])
    vrc = root / "src/mods/VR.cpp"
    edits(vrc, [
        ("reset controls", "m_duo_sharpen_max->value()=.10f;",
         """m_duo_sharpen_max->value()=.10f;
                    m_duo_sharpen_wide->value()=false; m_duo_focus_lift->value()=false;
                    m_duo_focus_brightness->value()=1.f; m_duo_focus_corner->value()=0.f;
                    m_duo_focus_onset->value()=.35f; m_duo_focus_power->value()=2.f;
                    m_duo_seam_match->value()=false; m_duo_seam_strength->value()=.75f;
                    m_duo_seam_limit->value()=.25f; m_duo_seam_reach->value()=80.f;
                    m_duo_seam_inward->value()=64.f; m_duo_seam_color->value()=0.f;"""),
        ("insert draw controls", '                m_duo_sharpen_max->draw("Glamarye fovea max change per pixel (default 0.10; higher = stronger on hard edges, more halo risk)");',
         """                m_duo_sharpen_max->draw("Glamarye fovea max change (0.05-0.80; higher risks halos)");
                m_duo_sharpen_wide->draw("Extra-wide sharpen ring (OFF by default; additional 2x radius)");
                m_duo_focus_lift->draw("Fovea anti-vignette / brightness correction (OFF by default)");
                if (m_duo_focus_lift->value()) {
                    m_duo_focus_brightness->draw("Fovea overall brightness");
                    m_duo_focus_corner->draw("Fovea corner gain");
                    m_duo_focus_onset->draw("Fovea radial onset");
                    m_duo_focus_power->draw("Fovea radial power");
                }
                m_duo_seam_match->draw("Mono seam brightness/color matching (OFF by default)");
                if (m_duo_seam_match->value()) {
                    m_duo_seam_strength->draw("Seam matching strength");
                    m_duo_seam_limit->draw("Max automatic seam gain");
                    m_duo_seam_reach->draw("Outside crop matching reach (pixels)");
                    m_duo_seam_inward->draw("Inward blended feather (pixels)");
                    m_duo_seam_color->draw("Color matching (0=brightness-only, 1=RGB)");
                }
                ImGui::TextWrapped("DuoView seam is mono-specific: four spatial edge groups reject strong outliers, with no temporal history or resets. Off leaves the v208d blend unchanged. This is NOT the TriView B40 temporal seam pipeline.");"""),
        ("candidate settings", ".sharpen_max_change=m_duo_sharpen_max->value(), ",
         """.sharpen_max_change=m_duo_sharpen_max->value(),
        .sharpen_wide=m_duo_sharpen_wide->value(),
        .focus_lift_enabled=m_duo_focus_lift->value(),
        .focus_brightness=m_duo_focus_brightness->value(), .focus_corner_gain=m_duo_focus_corner->value(),
        .focus_onset=m_duo_focus_onset->value(), .focus_power=m_duo_focus_power->value(),
        .seam_match_enabled=m_duo_seam_match->value(),
        .seam_strength=m_duo_seam_strength->value(), .seam_limit=m_duo_seam_limit->value(),
        .seam_reach_px=m_duo_seam_reach->value(), .seam_inward_px=m_duo_seam_inward->value(),
        .seam_color_strength=m_duo_seam_color->value(), """),
        ("settings equality", "current.sharpen_max_change==candidate.sharpen_max_change &&",
         """current.sharpen_max_change==candidate.sharpen_max_change &&
        current.sharpen_wide==candidate.sharpen_wide &&
        current.focus_lift_enabled==candidate.focus_lift_enabled &&
        current.focus_brightness==candidate.focus_brightness &&
        current.focus_corner_gain==candidate.focus_corner_gain &&
        current.focus_onset==candidate.focus_onset &&
        current.focus_power==candidate.focus_power &&
        current.seam_match_enabled==candidate.seam_match_enabled &&
        current.seam_strength==candidate.seam_strength &&
        current.seam_limit==candidate.seam_limit &&
        current.seam_reach_px==candidate.seam_reach_px &&
        current.seam_inward_px==candidate.seam_inward_px &&
        current.seam_color_strength==candidate.seam_color_strength &&"""),
        ("invalid label", '{uevr::duoview::reject_sharpen_max,"Glamarye max change"},',
         """{uevr::duoview::reject_sharpen_max,"Glamarye max change"},
                        {uevr::duoview::reject_focus_brightness,"Fovea brightness"},
                        {uevr::duoview::reject_focus_corner,"Fovea corner gain"},
                        {uevr::duoview::reject_focus_onset,"Fovea onset"},
                        {uevr::duoview::reject_focus_power,"Fovea radial power"},
                        {uevr::duoview::reject_seam_strength,"Seam strength"},
                        {uevr::duoview::reject_seam_limit,"Seam gain limit"},
                        {uevr::duoview::reject_seam_reach,"Seam outward reach"},
                        {uevr::duoview::reject_seam_inward,"Seam inward feather"},
                        {uevr::duoview::reject_seam_color,"Seam color mix"},"""),
    ])
    dx = root / "src/mods/vr/DuoViewD3D12.hpp"
    focus_constants = """{frame.config.settings.focus_lift_enabled ? 1.f : 0.f,
                frame.config.settings.focus_brightness, frame.config.settings.focus_corner_gain,
                frame.config.settings.focus_onset},
            {frame.config.settings.focus_power, 0.f, 0.f, 0.f},
            {frame.config.settings.seam_match_enabled ? 1.f : 0.f,
                frame.config.settings.seam_strength, frame.config.settings.seam_limit, 0.f},
            {frame.config.settings.seam_reach_px, frame.config.settings.seam_inward_px,
                frame.config.settings.seam_color_strength, 0.f}"""
    # FocusProfile separated from FocusLift to match original B31 center/radial
    # behavior; 4 float4 structs add 64 bytes => 184B / 46 root DWORDs.
    edits(dx, [
        ("shader constant fields",
         "    uint32_t sharpen_flags;\n};\nstatic_assert(sizeof(ShaderConstants) == 120);",
         """    uint32_t sharpen_flags;
    float focus_lift[4];
    float focus_profile[4];
    float seam_options[4];
    float seam_geometry[4];
};
static_assert(sizeof(ShaderConstants) == 184);
static_assert(sizeof(ShaderConstants)/4 <= 64); // D3D12 root DWORD budget"""),
        ("direct xr avoid double apply",
         "            frame.config.settings.sharpen_strength <= 0.0f &&",
         """            frame.config.settings.sharpen_strength <= 0.0f &&
            !frame.config.settings.focus_lift_enabled &&
            !frame.config.settings.seam_match_enabled &&"""),
        ("native shader constant values",
         "                (frame.config.settings.sharp_periphery ? 8u : 0u) // v207 Catmull-Rom periphery\n        };",
         """                (frame.config.settings.sharp_periphery ? 8u : 0u) | // v207 Catmull-Rom periphery
                (frame.config.settings.sharpen_wide ? 16u : 0u),
            """+focus_constants+"""
        };"""),
        ("gather constants", "            frame.settings.debug_border ? 1u : 0u, frame.settings.diagnostic_view, 0.f};",
         """            frame.settings.debug_border ? 1u : 0u, frame.settings.diagnostic_view, 0.f,
            {0u,0u}, {0u,0u}, {0u,0u},
            frame.settings.sharpen_strength, frame.settings.sharpen_max_change, .02f,
            3u | (srgb ? 0u : 4u) | (frame.settings.sharpen_wide ? 16u : 0u),
            {frame.settings.focus_lift_enabled ? 1.f : 0.f,
                frame.settings.focus_brightness, frame.settings.focus_corner_gain, frame.settings.focus_onset},
            {frame.settings.focus_power, 0.f, 0.f, 0.f},
            {frame.settings.seam_match_enabled ? 1.f : 0.f,
                frame.settings.seam_strength, frame.settings.seam_limit, 0.f},
            {frame.settings.seam_reach_px, frame.settings.seam_inward_px,
                frame.settings.seam_color_strength, 0.f}};"""),
    ])
    common = src / "DuoViewComposite.hlsl"
    edits(common, [
        ("GPU root constants",
         "    uint SharpenFlags;      // bit0=edge protection; bit1=bigger; bit2=manual SDR decode",
         """    uint SharpenFlags;      // bit0=edge protection; bit1=bigger; bit2=manual SDR decode
    float4 FocusLift;         // enabled, brightness, corner gain, onset r²
    float4 FocusProfile;      // radial power, reserved
    float4 SeamOptions;       // enabled, strength, max gain delta, reserved
    float4 SeamGeometry;      // outward px, inward feather px, colour mix, reserved"""),
        ("optional inward feather", "    const float2 local = (fullUv - CropUv.xy) / cropSize;",
         """    [branch] if (SeamOptions.x > .5 && SeamGeometry.y > 0.0) {
        const float2 edgePx = min(fullUv - CropUv.xy, CropUv.zw - fullUv) * float2(OutputSize);
        const float inner = saturate(min(edgePx.x, edgePx.y) / SeamGeometry.y);
        return inner * inner * (3.0 - 2.0 * inner);
    }
    const float2 local = (fullUv - CropUv.xy) / cropSize;"""),
    ])
    glam = src / "DuoViewGlamaryeFovea.hlsl"
    wide = """
// B43 Mono extra-wide ring. Applied to the original decoded center, after
// the v208d inner ring, so the extra ring remains zero-mean detail only.
float3 GlamExtraWideChange(float2 uv, float3 original) {
    const float3 c = GlamDecode(original);
    const float radius = 2.8;
    const float3 ne = GlamReadFovea(uv, float2( radius,  radius));
    const float3 nw = GlamReadFovea(uv, float2(-radius,  radius));
    const float3 se = GlamReadFovea(uv, float2( radius, -radius));
    const float3 sw = GlamReadFovea(uv, float2(-radius, -radius));
    const float3 around = ne + nw + se + sw;
    const float3 smoothC = min(clamp((around + c) / 5.0, c*.5, c*2.0), 1.0);
    const float dy = dot(kGlamLuma, abs((ne+nw)-(se+sw)));
    const float dx = dot(kGlamLuma, abs((ne+se)-(nw+sw)));
    const bool horizontal = dy > dx;
    const float3 n2 = (horizontal ? ne+nw : ne+se)*.5;
    const float3 s2 = (horizontal ? se+sw : nw+sw)*.5;
    const float2 west = horizontal ? float2(-7.0,0.0) : float2(0.0,7.0);
    const float2 east = -west;
    const float3 ww = GlamReadFovea(uv,west);
    const float3 ee = GlamReadFovea(uv,east);
    const float3 d1 = abs((ww-n2)-(ee-s2));
    const float3 d2 = abs((ee-n2)-(ww-s2));
    const float3 total = d1+d2+.00004;
    const float3 maximum = max(d1,d2)+.00001-SharpenFXAABias*sqrt(max(smoothC,0.0));
    const float guard = max(2.0*dot(kGlamLuma,maximum/total)-1.0,0.0);
    const float3 difference = 2.0*c+around-
        3.0*(max(max(ne,nw),max(se,sw))+min(min(ne,nw),min(se,sw)));
    const float detail = dot(kGlamLuma,difference);
    float3 possible = min(smoothC,c*.5);
    possible = min(possible,1.0-max(smoothC,c));
    possible = clamp(possible,.00001,SharpenMaxChange);
    const float3 change = detail/(1.0/max(SharpenStrength,.00001)+abs(detail)/possible);
    return change*(1.0-guard);
}
"""
    glam.write_text(glam.read_text(encoding="utf-8") + wide, encoding="utf-8", newline="\n")
    native = src / "DuoViewNativeCompositeRaster.hlsl"
    edits(native, [
        ("native helper insertion", "#include \"DuoViewGlamaryeFovea.hlsl\"",
         """#include "DuoViewGlamaryeFovea.hlsl"
float3 DuoReadFocus(float2 uv) {
    const float2 local = (uv - CropUv.xy) / (CropUv.zw - CropUv.xy);
    return SourceAtlas.SampleLevel(LinearClamp, NativeSampleUV(local, FoveaRect.zw, NativeFoveaDimensions), 0.0).rgb;
}
float3 DuoReadContext(float2 uv) {
    return PeripheralNativeSource.SampleLevel(LinearClamp, NativeSampleUV(uv, PeripheralRect.zw, NativePeripheryDimensions), 0.0).rgb;
}
#include "DuoViewPhase2Effects.hlsl" """.rstrip()),
        ("native context correction",
         "    float4 result = DebugViewMode == 2 ? float4(.04,.04,.04,1) : periphery;",
         """    if (DebugViewMode == 0 && weight < 1.0 && SeamOptions.x > .5)
        periphery.rgb = DuoPhase2MatchContext(fullUv, periphery.rgb);
    float4 result = DebugViewMode == 2 ? float4(.04,.04,.04,1) : periphery;"""),
        ("native shader corrections",
         """        if (SharpenStrength > 0.0 && DebugViewMode == 0)
            fovea.rgb = GlamSharpenNativeFovea(fullUv, fovea.rgb);""",
         """        if (SharpenStrength > 0.0 && DebugViewMode == 0) {
            const float3 beforeSharpen = fovea.rgb;
            fovea.rgb = GlamSharpenNativeFovea(fullUv, fovea.rgb);
            [branch] if ((SharpenFlags & 16u) != 0u)
                fovea.rgb = GlamEncode(saturate(GlamDecode(fovea.rgb) +
                                            GlamExtraWideChange(fullUv, beforeSharpen)));
        }
        if (DebugViewMode == 0) fovea.rgb = DuoPhase2FocusLift(fovea.rgb, localFovea);"""),
    ])
    raster = src / "DuoViewCompositeRaster.hlsl"
    edits(raster, [
        ("gather helper insertion", "float4 PSMain(VertexOut i) : SV_TARGET0 {",
         """// This fallback needs the SAME fused appearance controls as native mode.
// NativeSampleUV here adapts the existing atlas-bounded sampling for Glamarye.
float2 NativeSampleUV(float2 uv, uint2 active, uint2 size) {
    return AtlasSampleUV(FoveaRect, uv);
}
#include "DuoViewGlamaryeFovea.hlsl"
float3 DuoReadFocus(float2 uv) {
    return SourceAtlas.SampleLevel(LinearClamp,
            AtlasSampleUV(FoveaRect, (uv - CropUv.xy) / (CropUv.zw - CropUv.xy)), 0.0).rgb;
}
float3 DuoReadContext(float2 uv) {
    return SourceAtlas.SampleLevel(LinearClamp, AtlasSampleUV(PeripheralRect, uv), 0.0).rgb;
}
#include "DuoViewPhase2Effects.hlsl"
float4 PSMain(VertexOut i) : SV_TARGET0 {"""),
        ("gather context correction",
         "    const float4 peripheralColor = SourceAtlas.SampleLevel(LinearClamp, peripheralSample, 0.0);",
         """    float4 peripheralColor = SourceAtlas.SampleLevel(LinearClamp, peripheralSample, 0.0);
    if (DebugViewMode == 0 && SeamOptions.x > .5 && BlendWeight(fullUv) < 1.0)
        peripheralColor.rgb = DuoPhase2MatchContext(fullUv, peripheralColor.rgb);"""),
        ("gather fovea correction",
         """        const float4 fovealColor = SourceAtlas.SampleLevel(LinearClamp, foveaSample, 0.0);
        result = DebugViewMode == 2 ? fovealColor : lerp(peripheralColor, fovealColor, weight);""",
         """        float4 fovealColor = SourceAtlas.SampleLevel(LinearClamp, foveaSample, 0.0);
        if (DebugViewMode == 0) {
            if (SharpenStrength > 0.0) {
                const float3 beforeSharpen = fovealColor.rgb;
                fovealColor.rgb = GlamSharpenNativeFovea(fullUv, fovealColor.rgb);
                [branch] if ((SharpenFlags & 16u) != 0u)
                    fovealColor.rgb = GlamEncode(saturate(GlamDecode(fovealColor.rgb) +
                                              GlamExtraWideChange(fullUv, beforeSharpen)));
            }
            fovealColor.rgb = DuoPhase2FocusLift(fovealColor.rgb, foveaUV);
        }
        result = DebugViewMode == 2 ? fovealColor : lerp(peripheralColor, fovealColor, weight);"""),
    ])
    (src / "DuoViewPhase2Effects.hlsl").write_text(helper.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    # No TriView shader, mode-7 C++ member, or mode-7 settings file is edited.
    print("Phase2 patched only ID6: B43 0-20/0.80 sharpen + wide ring, B31 anti-vignette, 4-group seam.")
    print("Mode7 untouched; new effects OFF by default; DXBC must be re-embedded offline.")

if __name__ == "__main__":
    main()
