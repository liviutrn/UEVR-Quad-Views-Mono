#!/usr/bin/env python3
"""v211: staged, exact-anchor live NGX depth into fovea-only sharpen, opt-in."""
from pathlib import Path
import sys

def one(s, old, new, name):
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{name}: required exact anchor count {n}: {old[:100]!r}")
    return s.replace(old,new,1)

def apply(root,source):
    cfg=root/"src/mods/vr/DuoViewConfig.hpp"
    vrh=root/"src/mods/VR.hpp"
    vrc=root/"src/mods/VR.cpp"
    dx=root/"src/mods/vr/D3D12Component.cpp"
    src=root/"src/mods/vr/DuoViewNgxDepthCapture.hpp"
    if src.exists(): raise RuntimeError("Unexpected depth capture header already exists")
    files={p:p.read_text(encoding="utf-8-sig") for p in (cfg,vrh,vrc,dx)}
    c,h,v,d=files[cfg],files[vrh],files[vrc],files[dx]
    c=one(c,'    bool sharpen_distance_smooth{true};',
        '    bool sharpen_distance_smooth{true};\n    bool depth_reversed_z{true};\n    uint32_t depth_preview_mode{};',str(cfg))
    c=one(c,'    out.sharpen_distance_smooth=requested.sharpen_distance_smooth;',
        '    out.sharpen_distance_smooth=requested.sharpen_distance_smooth;\n'
        '    out.depth_reversed_z=requested.depth_reversed_z;\n'
        '    out.depth_preview_mode=requested.depth_preview_mode<=2u?requested.depth_preview_mode:current.depth_preview_mode;',str(cfg))
    c=one(c,'            !valid_distance_sharpen_range(proposed.sharpen_near_m, proposed.sharpen_far_m) ||',
        '            proposed.depth_preview_mode>2u ||\n'
        '            !valid_distance_sharpen_range(proposed.sharpen_near_m, proposed.sharpen_far_m) ||',str(cfg))
    h=one(h,'    bool duoview_ngx_browser_enabled() const { return m_duo_ngx_browser->value(); }',
        '    bool duoview_ngx_browser_enabled() const { return m_duo_ngx_browser->value(); }\n'
        '    bool duoview_depth_requested() const { return m_duo_distance_enabled->value() || m_duo_depth_preview->value()!=0; }',str(vrh))
    h=one(h,'    const ModToggle::Ptr m_duo_ngx_browser{ModToggle::create(generate_name("DuoViewNgxDepthBrowser"), false)};',
        '    const ModToggle::Ptr m_duo_ngx_browser{ModToggle::create(generate_name("DuoViewNgxDepthBrowser"), false)};\n'
        '    const ModToggle::Ptr m_duo_depth_reverse{ModToggle::create(generate_name("DuoViewDepthReversedZ"), true)};\n'
        '    const ModInt32::Ptr m_duo_depth_preview{ModSliderInt32::create(generate_name("DuoViewDepthPreview"),0,2,0)};',str(vrh))
    h=one(h,'            *m_duo_far_distance, *m_duo_distance_smooth, *m_duo_ngx_browser, *m_duo_gaze,',
        '            *m_duo_far_distance, *m_duo_distance_smooth, *m_duo_ngx_browser,\n'
        '            *m_duo_depth_reverse, *m_duo_depth_preview, *m_duo_gaze,',str(vrh))
    v=one(v,'#include "vr/DuoViewNgxManualDepth.hpp"',
        '#include "vr/DuoViewNgxManualDepth.hpp"\n#include "vr/DuoViewNgxDepthCapture.hpp"',str(vrc))
    v=one(v,'                    m_duo_distance_smooth->value()=true;',
        '                    m_duo_distance_smooth->value()=true;\n'
        '                    m_duo_depth_reverse->value()=true; m_duo_depth_preview->value()=0;',str(vrc))
    v=one(v,'ImGui::TextWrapped("Distance sharpening v209: CONTROL STAGING ONLY. Depth is not yet connected; current fixed sharpening is always used.");',
        'ImGui::TextWrapped("Depth sharpening v211: consumes selected NGX-SR fovea depth ONLY when the exact render packet and original game queue are verified. If unavailable, ordinary fixed sharpening is preserved. HEADSET TEST REQUIRED.");',str(vrc))
    labels={
      'Future fovea distance sharpening (not yet applied)':'Distance-aware fovea sharpening (requires current DLSS depth)',
      'Future near sharpness (0-5)':'Near sharpness (0-5)',
      'Future far sharpness (0-5)':'Far sharpness (0-5)',
      'Future near distance (meters)':'Near sharpness ends at distance (meters)',
      'Future far distance (meters; must exceed near)':'Far sharpness begins at distance (meters; must exceed near)',
      'Future smooth transition (OFF = linear)':'Smooth transition (OFF = linear)'
    }
    for k,value in labels.items(): v=one(v,k,value,str(vrc))
    # The game previously repeated reject_sharpen_distance (bit 20) every 5s.
    # Keep both the loaded profile and interactive near/far sliders valid.
    v=one(v,'                m_duo_far_distance->draw("Far sharpness begins at distance (meters; must exceed near)");',
        '                m_duo_far_distance->draw("Far sharpness begins at distance (meters; must exceed near)");\n'
        '                if (m_duo_near_distance->value() >= m_duo_far_distance->value()) {\n'
        '                    const float near_m=std::clamp(m_duo_near_distance->value(),0.f,999.9f);\n'
        '                    m_duo_near_distance->value()=near_m;\n'
        '                    m_duo_far_distance->value()=std::max(m_duo_far_distance->value(),near_m+.1f);\n'
        '                }',str(vrc))
    v=one(v,'        .sharpen_near_m=m_duo_near_distance->value(),',
        '        .sharpen_near_m=std::clamp(m_duo_near_distance->value(),0.f,999.9f),',str(vrc))
    v=one(v,'        .sharpen_far_m=m_duo_far_distance->value(),',
        '        .sharpen_far_m=std::clamp(m_duo_far_distance->value(),\n'
        '            std::clamp(m_duo_near_distance->value(),0.f,999.9f)+.1f,1000.f),',str(vrc))
    v=one(v,'                m_duo_distance_smooth->draw("Smooth transition (OFF = linear)");',
        '                m_duo_distance_smooth->draw("Smooth transition (OFF = linear)");\n'
        '                m_duo_depth_reverse->draw("DLSS depth reversed Z (UE5 default)");\n'
        '                m_duo_depth_preview->draw("Depth preview: 0 off / 1 raw / 2 distance ramp");\n'
        '                ImGui::Text("Depth GPU: captured=%llu submitted=%llu USED=%llu skipped=%llu",\n'
        '                    static_cast<unsigned long long>(uevr::duoview::ngx::depth_snapshots().captures()),\n'
        '                    static_cast<unsigned long long>(uevr::duoview::ngx::depth_snapshots().submits()),\n'
        '                    static_cast<unsigned long long>(uevr::duoview::ngx::depth_snapshots().used()),\n'
        '                    static_cast<unsigned long long>(uevr::duoview::ngx::depth_snapshots().skips()));',str(vrc))
    v=one(v,'Native NGX-SR depth sources are now OBSERVED and can be manually pinned. This browser does not yet copy or sample the depth pixels. Distance sharpening still uses fixed strength until matching the producing fovea is proven.',
        'Native NGX-SR depth sources can be selected or pinned. The v211 shader samples an owned GPU copy only when the same render packet and queue match. Visualize raw depth and the near/far distance ramp before trusting the effect.',str(vrc))
    v=one(v,' (depth pixels NOT yet copied)',' (GPU snapshot subject to exact-frame verification)',str(vrc))
    v=one(v,'        .sharpen_distance_smooth=m_duo_distance_smooth->value(),',
        '        .sharpen_distance_smooth=m_duo_distance_smooth->value(),\n'
        '        .depth_reversed_z=m_duo_depth_reverse->value(),\n'
        '        .depth_preview_mode=static_cast<uint32_t>(m_duo_depth_preview->value()),',str(vrc))
    v=one(v,'        current.sharp_periphery==candidate.sharp_periphery) return;',
        '        current.distance_sharpen_enabled==candidate.distance_sharpen_enabled &&\n'
        '        current.sharpen_near_strength==candidate.sharpen_near_strength &&\n'
        '        current.sharpen_far_strength==candidate.sharpen_far_strength &&\n'
        '        current.sharpen_near_m==candidate.sharpen_near_m &&\n'
        '        current.sharpen_far_m==candidate.sharpen_far_m &&\n'
        '        current.sharpen_distance_smooth==candidate.sharpen_distance_smooth &&\n'
        '        current.depth_reversed_z==candidate.depth_reversed_z &&\n'
        '        current.depth_preview_mode==candidate.depth_preview_mode &&\n'
        '        current.sharp_periphery==candidate.sharp_periphery) return;',str(vrc))
    d=one(d,'const bool browser_active=vr && vr->is_duoview_renderer_active() && vr->duoview_ngx_browser_enabled();',
        'const bool browser_active=vr && vr->is_duoview_renderer_active() &&\n'
        '        (vr->duoview_ngx_browser_enabled() || vr->duoview_depth_requested());',str(dx))
    d=one(d,'    if (browser_active) ngx_depth_browser.install();',
        '    if (browser_active) {\n'
        '        ngx_depth_browser.install();\n'
        '        if (g_framework && g_framework->get_d3d12_hook())\n'
        '            ngx_depth_browser.install_queue(g_framework->get_d3d12_hook()->get_command_queue());\n'
        '    }',str(dx))
    # Expose a periodic runtime health signal in log.txt when live depth is
    # requested but nothing has reached the native compositor.
    d=one(d,
        '            ngx_depth_browser.install_queue(g_framework->get_d3d12_hook()->get_command_queue());',
        '            ngx_depth_browser.install_queue(g_framework->get_d3d12_hook()->get_command_queue());\n'
        '        if (vr->duoview_depth_requested() && uevr::duoview::ngx::depth_snapshots().used()==0) {\n'
        '            SPDLOG_WARNING_EVERY_N_SEC(8,\n'
        '                "[DuoView][NGX] unavailable: eval={} qualified={} no_rhi={} hooks={} queue_hook={} captured={} submitted={} used={} skipped={} selected={} inactive={} stale={} attempted={} output={}x{} render={}x{} depth_fmt={} cmd_type={} selected_tid={} output_captured={} output_matched={} late_ticket={}",\n'
        '                ngx_depth_browser.calls(),ngx_depth_browser.candidates_seen(),\n'
        '                ngx_depth_browser.missing_rhi_ticket(),ngx_depth_browser.installed_evaluators(),\n'
        '                ngx_depth_browser.queue_hook_installed(),\n'
        '                uevr::duoview::ngx::depth_snapshots().captures(),\n'
        '                uevr::duoview::ngx::depth_snapshots().submits(),\n'
        '                uevr::duoview::ngx::depth_snapshots().used(),\n'
        '                uevr::duoview::ngx::depth_snapshots().skips(),\n'
        '                ngx_depth_browser.selected_calls(),ngx_depth_browser.inactive_renderer(),\n'
        '                ngx_depth_browser.stale_packet(),ngx_depth_browser.capture_attempts(),\n'
        '                ngx_depth_browser.last_output_w(),ngx_depth_browser.last_output_h(),\n'
        '                ngx_depth_browser.last_render_w(),ngx_depth_browser.last_render_h(),\n'
        '                ngx_depth_browser.last_depth_format(),ngx_depth_browser.last_command_type(),\n'
        '                ngx_depth_browser.last_selected_thread(),\n'
        '                uevr::duoview::ngx::depth_snapshots().unkeyed_captures(),\n'
        '                uevr::duoview::ngx::depth_snapshots().output_matches(),\n'
        '                uevr::duoview::ngx::depth_snapshots().late_tickets());\n'
        '        }',str(dx))
    d=one(d,'                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);',
        '                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0,\n'
        '                                        g_framework->get_d3d12_hook()->get_command_queue());',str(dx))
    if not (source/"DuoViewNgxDepthCapture.hpp").exists():
        raise RuntimeError("Missing shipped depth capture implementation")
    for path,data in ((cfg,c),(vrh,h),(vrc,v),(dx,d)):
        path.write_text(data,encoding="utf-8",newline="")
    src.write_bytes((source/"DuoViewNgxDepthCapture.hpp").read_bytes())
    print("PASS v211: live NGX depth capture, frozen settings, fused fovea compositor and preview controls")

if __name__=="__main__":
    if len(sys.argv)!=3: raise SystemExit("Usage: apply_v211_live_depth.py BACKEND DUOVIEW_SOURCE")
    apply(Path(sys.argv[1]),Path(sys.argv[2]))
