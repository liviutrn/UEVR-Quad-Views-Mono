#!/usr/bin/env python3
"""B318: reuse same generation/queue NGX coarse depth for ONE shared-image mono
distance fade. The shader's M1 mode uses a proved identity homography and k=0,
but the output metadata, viewport and XR submission remain MONO. Missing depth
uses the original mono sharpening path; M4 is never requested by this path.
Run after M8, after b318 startup overlay."""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_duoview_b318_mono_fade.py <backend>")
    mods=Path(sys.argv[1])/"src/mods"
    patch(mods/"VR.cpp", [
        ("request existing NGX depth on mono distance fade",
         "if (frame && frame->config.settings.synthetic_stereo) {\n        const auto& layout = frame->config.layout;",
         """if (frame && (frame->config.settings.synthetic_stereo ||
        (frame->config.settings.m24_distance_fade &&
         (frame->config.settings.sharpen_strength > 0.f ||
          (frame->config.settings.sharpen_wide && frame->config.settings.m23_wide_strength > 0.f))))) {
        const auto& layout = frame->config.layout;"""),
    ])
    patch(mods/"vr/D3D12Component.cpp", [
        ("keep NGX capture available for mono distance fade",
         """        const bool duo_depth = vr->is_duoview_renderer_active() &&
            vr->duoview_state().settings().synthetic_stereo;""",
         """        const auto duo_capture_settings = vr->duoview_state().settings();
        const bool mono_distance_requested =
            !duo_capture_settings.synthetic_stereo && duo_capture_settings.m24_distance_fade &&
            (duo_capture_settings.sharpen_strength > 0.f ||
             (duo_capture_settings.sharpen_wide && duo_capture_settings.m23_wide_strength > 0.f));
        const bool duo_depth = vr->is_duoview_renderer_active() &&
            (duo_capture_settings.synthetic_stereo || mono_distance_requested);"""),
        ("only build identity M1 context for mono if requested",
         """                                    if (packet_frame->config.settings.synthetic_stereo && current_queue) {
                                        std::array<uevr::duoview::stereo::Eye,2> eyes{};""",
         """                                    const bool mono_distance =
                                        !packet_frame->config.settings.synthetic_stereo &&
                                        packet_frame->config.settings.m24_distance_fade &&
                                        (packet_frame->config.settings.sharpen_strength > 0.f ||
                                         (packet_frame->config.settings.sharpen_wide &&
                                          packet_frame->config.settings.m23_wide_strength > 0.f));
                                    if ((packet_frame->config.settings.synthetic_stereo || mono_distance) && current_queue) {
                                        std::array<uevr::duoview::stereo::Eye,2> eyes{};"""),
        ("identity M1 source projection for shared mono image",
         """                                        stereo_geometry=uevr::duoview::stereo::make_geometry(packet_frame->projection,eyes,
                                            scale,packet_frame->config.settings.stereo_strength);""",
         """                                        if (mono_distance) {
                                            // Match the output to its original shared-camera
                                            // logical projection O. The Unreal source is F. With
                                            // k=0 this maps O->F but never creates eye disparity.
                                            const auto& p=packet_frame->logical_projection;
                                            if (std::isfinite(p[0]) && std::isfinite(p[5]) &&
                                                std::isfinite(p[8]) && std::isfinite(p[9]) &&
                                                p[0]>0.f && p[5]>0.f) {
                                                const std::array<float,4> same_tangents{
                                                    (-1.f-p[8])/p[0],(1.f-p[8])/p[0],
                                                    (1.f-p[9])/p[5],(-1.f-p[9])/p[5]};
                                                eyes[0].tangents=same_tangents;
                                                eyes[1]=eyes[0];
                                            } else {
                                                // No valid matching projection: do not use
                                                // stale or mismatched depth for this frame.
                                                stereo_geometry.reset();
                                            }
                                        }
                                        if (!mono_distance ||
                                            (eyes[0].tangents[0]<eyes[0].tangents[1] &&
                                             eyes[0].tangents[3]<eyes[0].tangents[2])) {
                                            stereo_geometry=uevr::duoview::stereo::make_geometry(packet_frame->projection,eyes,
                                                scale,mono_distance ? 0.0 : packet_frame->config.settings.stereo_strength);
                                        }
                                        if (mono_distance && stereo_geometry) {
                                            const auto& h=stereo_geometry->context_h[0];
                                            const auto& fit=packet_frame->config.source_fit;
                                            const float inv_span=1.f/fit.span();
                                            const bool identity=std::abs(h[0]-1.f)<.0002f &&
                                                std::abs(h[1])<.0002f && std::abs(h[2])<.0002f &&
                                                std::abs(h[4])<.0002f && std::abs(h[5]-inv_span)<.0002f &&
                                                std::abs(h[6]+fit.v0*inv_span)<.0002f && std::abs(h[8])<.0002f &&
                                                std::abs(h[9])<.0002f && std::abs(h[10]-1.f)<.0002f &&
                                                std::abs(stereo_geometry->k[0])<1.e-8f &&
                                                std::abs(stereo_geometry->k[1])<1.e-8f;
                                            if (!identity) {
                                                SPDLOG_WARNING_EVERY_N_SEC(5,
                                                    "[DuoView][MonoFade] Reject mismatched O-to-F depth projection; use original sharpening");
                                                stereo_geometry.reset();
                                            }
                                        }"""),
        ("reject unmatched stale depth for mono sharpening",
         """                                            if (snapshot) stereo_depth=uevr::duoview::dx12::M1DepthInput{
                                                snapshot->texture.Get(),snapshot->srv_format,""",
         """                                            // Unlike stereo's content-tolerant fallback, mono
                                            // fade is allowed only with the exact packet epoch.
                                            // Stale or missing depth retains ordinary sharpening.
                                            const bool mono_epoch_ok = !mono_distance || (snapshot &&
                                                snapshot->m24_present_epoch != 0 &&
                                                snapshot->m24_present_epoch == packet_frame->present_epoch);
                                            if (snapshot && mono_epoch_ok) stereo_depth=uevr::duoview::dx12::M1DepthInput{
                                                snapshot->texture.Get(),snapshot->srv_format,"""),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("mono distance fade shader admission separate from stereo activation",
         """        const bool m1_active=settings.synthetic_stereo && stereo_geometry &&
            stereo_depth && stereo_depth->texture && stereo_depth->lease &&
            xr_raster_compatible && m1_.ready() &&""",
         """        const bool mono_fade_active=!settings.synthetic_stereo && settings.m24_distance_fade &&
            (settings.sharpen_strength>0.f ||
             (settings.sharpen_wide && settings.m23_wide_strength>0.f));
        const bool m1_active=(settings.synthetic_stereo || mono_fade_active) && stereo_geometry &&
            stereo_depth && stereo_depth->texture && stereo_depth->lease &&
            xr_raster_compatible && m1_.ready() &&"""),
        ("mono fade must not fetch fine NGX depth or invoke M4",
         "settings.m2_fovea_depth ? stereo_fovea_depth : nullptr,",
         "(settings.synthetic_stereo && settings.m2_fovea_depth) ? stereo_fovea_depth : nullptr,"),
        ("mono fade still renders one single source image",
         "const UINT direct_width=!m1_active && frame.config.settings.shared_eye_image ? width_ : width_*2;",
         "const UINT direct_width=!settings.synthetic_stereo && frame.config.settings.shared_eye_image ? width_ : width_*2;"),
        ("mono fade does not signal synthetic stereo to OpenXR or VectorXR",
         "        last_stereo_output_=m1_active;",
         "        last_stereo_output_=m1_active && settings.synthetic_stereo;"),
    ])
    print("B318 mono fade: matching NGX periphery depth, identity source projection, M1 single draw, fallback")

if __name__=="__main__":
    main()
