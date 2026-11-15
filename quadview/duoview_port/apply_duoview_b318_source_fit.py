#!/usr/bin/env python3
"""B318 vertical source fit for DuoView ID6 only. Apply AFTER M8/B318 mono-depth.
No cropped OpenXR output and no loss of foveal angular sampling.

Coordinate contract:
 O = original symmetric projection, original output, gaze and crop UV
 F = tighter periphery Unreal camera/source UV
 eye M1 warp -> F; composite seams/fovea use F->O; periphery sampling uses F
"""
from pathlib import Path
import shutil
import sys
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_b318_source_fit.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])
    here=Path(__file__).resolve().parents[2] / "duoview"
    shutil.copyfile(here/"DuoViewSourceFit.hpp",mods/"vr/DuoViewSourceFit.hpp")

    patch(mods/"vr/DuoViewConfig.hpp", [
        ("frame metadata includes fitted UV projection",
         '#include "DuoViewFrame.hpp"',
         '#include "DuoViewFrame.hpp"\n#include "DuoViewSourceFit.hpp"'),
        ("append source fit after existing config generation",
         "    uint64_t settings_revision{};\n};",
         "    uint64_t settings_revision{};\n    SourceFit source_fit{};\n};"),
    ])
    patch(mods/"vr/DuoViewState.hpp", [
        ("save unfitted common-camera projection for mono depth identity",
         "    std::array<float, 16> projection{};",
         """    std::array<float, 16> projection{};
    std::array<float, 16> logical_projection{};"""),
        ("source fit joins the immutable frame signature",
         "uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}) {",
         "uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}, SourceFit source_fit={}) {"),
        ("fit physical periphery and source camera before freezing",
         """        slot = ViewFrame{*frozen, projection};
        slot->mono_source_frame = mono_source_frame;""",
         """        if (!source_fit.valid()) return {};
        auto config=*frozen;
        config.source_fit=source_fit;
        config.layout.periphery=fitted_periphery_rect(config.layout.periphery,source_fit);
        if (!layout_valid(config.layout)) return {};
        auto source_projection=projection;
        if (!apply_source_fit_projection(source_projection,source_fit)) return {};
        slot = ViewFrame{config, source_projection};
        slot->logical_projection=projection;
        slot->mono_source_frame = mono_source_frame;"""),
        ("preserve foveal angular extent on fitted camera",
         "    if (view==frame.config.settings.fovea_view) apply_foveal_crop(matrix,frame.config.layout);",
         """    if (view==frame.config.settings.fovea_view) {
        auto crop=frame.config.layout;
        // The foveal ROI is expressed in O. Crop the actual UE camera
        // in F: its physical pixel dimensions remain unchanged.
        crop.v0=frame.config.source_fit.to_source_v(crop.v0);
        crop.v1=frame.config.source_fit.to_source_v(crop.v1);
        apply_foveal_crop(matrix,crop);
    }"""),
    ])
    patch(mods/"VR.hpp", [
        ("source fit user control",
         '    const ModToggle::Ptr m_duo_stereo{ModToggle::create(generate_name("DuoViewSyntheticStereo"), false)};',
         """    const ModToggle::Ptr m_duo_fit_source{ModToggle::create(generate_name("DuoViewFitSourceProjection"),true)};
    const ModToggle::Ptr m_duo_stereo{ModToggle::create(generate_name("DuoViewSyntheticStereo"), false)};"""),
        ("source fit persisted",
         "            *m_duo_shared_eye, *m_duo_stereo, *m_duo_stereo_strength,",
         "            *m_duo_shared_eye, *m_duo_fit_source, *m_duo_stereo, *m_duo_stereo_strength,"),
    ])
    patch(mods/"VR.cpp", [
        ("source fit UI in both mono and stereo",
         '                m_duo_stereo->draw("Synthetic stereo (M1, experimental)");',
         """                m_duo_fit_source->draw("Fit Unreal periphery source vertically to calibrated view (B318; no XR crop)");
                m_duo_stereo->draw("Synthetic stereo (M1, experimental)");"""),
        ("read OpenXR bound geometry before creating the shared UE pair",
         """    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,""",
         """    // Cache one safe source envelope for this OpenXR generation. Never
    // resize on eye gaze, and never derive bounds from a different pose.
    auto source_fit=uevr::duoview::SourceFit{};
    if (m_duo_fit_source->value() && get_openxr_runtime()) {
        if (const auto proposed=get_openxr_runtime()->duoview_source_fit(source_frame)) {
            if (std::abs(projection[0][0] - proposed->expected_x_scale) < .0005f &&
                std::abs(projection[1][1] - proposed->expected_y_scale) < .0005f &&
                std::abs(projection[2][0]) < .0005f &&
                std::abs(projection[2][1]) < .0005f)
                source_fit=proposed->fit;
            else
                SPDLOG_WARNING_EVERY_N_SEC(5,"[DuoView][Fit] Original mono projection differs from calibrated source basis; keeping baseline");
        }
    }
    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,"""),
        ("pass selected fit into one immutable State::begin",
         "}, GetTickCount64(), source_frame);",
         "}, GetTickCount64(), source_frame, source_fit);"),
    ])
    patch(mods/"vr/runtimes/OpenXR.hpp", [
        ("access guarded calibrated view bounds from source frame",
         '#include "../DuoViewFrame.hpp"',
         '#include "../DuoViewFrame.hpp"\n#include "../DuoViewSourceFit.hpp"'),
        ("source-fit query beside coherent pose accessor",
         '    std::optional<PipelineState> capture_duoview_pose(uint32_t frame);',
         """    struct DuoSourceFitSnapshot {
        uevr::duoview::SourceFit fit;
        float expected_x_scale{}, expected_y_scale{};
    };
    std::optional<DuoSourceFitSnapshot> duoview_source_fit(uint32_t frame);
    std::optional<PipelineState> capture_duoview_pose(uint32_t frame);"""),
        ("source-fit cache is generation owned",
         '    std::optional<PipelineState> duoview_pending_pose, duoview_submitted_pose;',
         """    uint64_t duoview_source_fit_generation{};
    std::optional<DuoSourceFitSnapshot> duoview_source_fit_cache;
    std::optional<PipelineState> duoview_pending_pose, duoview_submitted_pose;"""),
    ])
    patch(mods/"vr/runtimes/OpenXR.cpp", [
        ("reset on runtime projection generation retirement",
         "    mono_frames = {};\n    mono_copied_frame.reset();",
         """    mono_frames = {};
    duoview_source_fit_generation=0;
    duoview_source_fit_cache.reset();
    mono_copied_frame.reset();"""),
        ("add source envelope accessor after validated original optical basis",
         "void OpenXR::note_mono_projection() {",
         """std::optional<OpenXR::DuoSourceFitSnapshot> OpenXR::duoview_source_fit(uint32_t frame) {
    std::scoped_lock lock{this->sync_assignment_mtx};
    const auto generation=VR::get()->mono_generation();
    if (!generation) return {};
    if (duoview_source_fit_generation == generation && duoview_source_fit_cache)
        return duoview_source_fit_cache;
    const auto& slot=mono_frames[frame % QUEUE_SIZE];
    if (!slot.pose_valid || slot.pose_frame!=frame || !slot.geometry) return {};
    const auto& g=*slot.geometry;
    DuoSourceFitSnapshot fitted{uevr::duoview::fit_vertical_source(g.bounds,.02f),
        1.f/g.horizontal,1.f/g.vertical};
    if (!fitted.fit.valid()) return {};
    duoview_source_fit_generation=generation;
    duoview_source_fit_cache=fitted;
    SPDLOG_INFO("[DuoView][Fit] Calibrated vertical envelope [{:.5f},{:.5f}] span={:.5f}, unchanged XR output",
        fitted.fit.v0,fitted.fit.v1,fitted.fit.span());
    return fitted;
}

void OpenXR::note_mono_projection() {"""),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp", [
        ("encode O/F vertical mapping in two existing reserved shader floats (native)",
         '{frame.config.settings.focus_power, frame.config.settings.sharpen_wide ? frame.config.settings.m23_wide_strength : 0.f, 0.f, 0.f}',
         '{frame.config.settings.focus_power, frame.config.settings.sharpen_wide ? frame.config.settings.m23_wide_strength : 0.f, frame.config.source_fit.v0, frame.config.source_fit.v1-1.f}'),
        ("encode O/F mapping in packed fallback too",
         '{frame.settings.focus_power, frame.settings.sharpen_wide ? frame.settings.m23_wide_strength : 0.f, 0.f, 0.f}',
         '{frame.settings.focus_power, frame.settings.sharpen_wide ? frame.settings.m23_wide_strength : 0.f, frame.source_fit.v0, frame.source_fit.v1-1.f}'),
        ("M2/M4 coarse grid and fine crop use actual source projection",
         '{layout.u0,layout.v0,layout.u1,layout.v1},',
         '{layout.u0,frame.config.source_fit.to_source_v(layout.v0),layout.u1,frame.config.source_fit.to_source_v(layout.v1)},'),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp", [
        ("allow partially offscreen fine ROI when gaze reaches optical edge",
         """        const bool crop_ok = crop[0] >= 0.f && crop[1] >= 0.f &&
            crop[2] <= 1.f && crop[3] <= 1.f &&
            crop[2] > crop[0] && crop[3] > crop[1] &&""",
         """        const bool crop_ok = crop[0] >= 0.f && crop[2] <= 1.f &&
            crop[2] > crop[0] && crop[3] > crop[1] &&
            crop[1] < 1.f && crop[3] > 0.f &&
            crop[1] > -1.f && crop[3] < 2.f &&"""),
    ])
    patch(sh/"DuoViewComposite.hlsl", [
        ("add explicit logical->source mapping in the existing shared shader",
         "float2 AtlasSampleUV(uint4 rect, float2 localUv)",
         """// FocusProfile.z=logical top crop, FocusProfile.w=logical bottom crop - 1.
// 0,0 is the proven identity path; no new root constants or descriptor.
float2 DuoLogicalToSourceUv(float2 logicalUv) {
    const float span=max(1.e-5,1.f+FocusProfile.w-FocusProfile.z);
    return float2(logicalUv.x,(logicalUv.y-FocusProfile.z)/span);
}
float2 DuoSourceToLogicalUv(float2 sourceUv) {
    return float2(sourceUv.x,FocusProfile.z+sourceUv.y*(1.f+FocusProfile.w-FocusProfile.z));
}

float2 AtlasSampleUV(uint4 rect, float2 localUv)"""),
    ])
    patch(sh/"DuoViewNativeCompositeRaster.hlsl", [
        ("M6 final point-fill source and logical UV conversion",
         """    float2 fill=0.;
    float2 fullUv=outputUv;
    [branch] if (M2Sharpen.z <= .5)
        fullUv=M1PullUv(outputUv,i.pos.x >= OutputSize.x ? 1u : 0u,fill);""",
         """    float2 fill=0.;
    float2 sourceUv=outputUv;
    [branch] if (M2Sharpen.z <= .5)
        sourceUv=M1PullUv(outputUv,i.pos.x >= OutputSize.x ? 1u : 0u,fill);
    const float2 fullUv=DuoSourceToLogicalUv(sourceUv);"""),
        ("periphery UV helper applies projection fit for all users including seam",
         "float2 NativePeripheryUV(float2 uv) {",
         "float2 NativePeripheryUV(float2 uv) {\n    uv=DuoLogicalToSourceUv(uv);"),
        ("Catmull-Rom periphery uses physical fitted UV",
         "SamplePeripheryCatmullRom(fullUv, PeripheralRect.zw, NativePeripheryDimensions)",
         "SamplePeripheryCatmullRom(DuoLogicalToSourceUv(fullUv), PeripheralRect.zw, NativePeripheryDimensions)"),
        ("M6 background fill has its own source projection",
         "        const float2 fillUv=float2(fill.x,fullUv.y);",
         "        const float2 fillUv=DuoSourceToLogicalUv(float2(fill.x,sourceUv.y));"),
        ("M4 depth picture samples the source's conditioned field",
         "const float D=M1ReadConditionedEye(outputUv,i.pos.x>=OutputSize.x ? 1u : 0u);",
         "const float D=M1ReadConditionedEye(sourceUv,i.pos.x>=OutputSize.x ? 1u : 0u);"),
        ("mono and stereo depth both sample the fitted source UV",
         "const float D=M1ReadConditioned(fullUv);",
         "const float D=M1ReadConditioned(sourceUv);"),
    ])
    patch(sh/"DuoViewCompositeRaster.hlsl",[
        ("packed fallback uses the fitted periphery too",
         "    const float2 peripheralSample = AtlasSampleUV(PeripheralRect, fullUv);",
         "    const float2 peripheralSample = AtlasSampleUV(PeripheralRect, DuoLogicalToSourceUv(fullUv));"),
    ])
    print("B318 fit: trimmed Unreal periphery viewport, asymmetric projection, stereo/depth/fovea mapping; XR unchanged")

if __name__=="__main__":
    main()
