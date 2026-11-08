#!/usr/bin/env python3
"""Isolated B35 UI/history ownership. Run after all B31 overlays and B30 checks."""
from pathlib import Path
import sys

def once(s,a,b):
    if s.count(a)!=1: raise RuntimeError(f'B35 anchor count {s.count(a)}: {a[:100]!r}')
    return s.replace(a,b,1)

def main():
    r=Path(sys.argv[1])/'src/mods'
    p=r/'VR.hpp';s=p.read_text()
    anchor='    static const inline std::vector<std::string> s_quadview_seam_mode_names'
    s=once(s,anchor,'    static const inline std::vector<std::string> s_quadview_edge_mode_names{ "B31", "Edge V2 Instant", "Edge V2 Temporal" };\n'+anchor)
    anchor='    const ModToggle::Ptr m_quadview_seam_debug'
    controls='''    const ModCombo::Ptr m_quadview_edge_mode{ModCombo::create(generate_name("QuadViewEdgeV2Mode"), s_quadview_edge_mode_names, 2)};
    const ModSlider::Ptr m_quadview_edge_strength{ModSlider::create(generate_name("QuadViewEdgeV2Strength"), 0.f, 1.f, 1.f)};
    const ModSlider::Ptr m_quadview_edge_reach{ModSlider::create(generate_name("QuadViewEdgeV2Reach"), 16.f, 1024.f, 240.f)};
    const ModSlider::Ptr m_quadview_edge_fast{ModSlider::create(generate_name("QuadViewEdgeV2Fast"), 1.f, 256.f, 32.f)};
    const ModSlider::Ptr m_quadview_edge_rate{ModSlider::create(generate_name("QuadViewEdgeV2Rate"), .001f, 4.f, .15f)};
    const ModSlider::Ptr m_quadview_edge_noise{ModSlider::create(generate_name("QuadViewEdgeV2Noise"), 0.f, .05f, .004f)};
    const ModSlider::Ptr m_quadview_edge_feather{ModSlider::create(generate_name("QuadViewEdgeV2Feather"), 0.f, 64.f, 2.f)};
'''
    s=once(s,anchor,controls+anchor)
    anchor='            *m_quadview_seam_mode,'
    s=once(s,anchor,'''            *m_quadview_edge_mode, *m_quadview_edge_strength, *m_quadview_edge_reach,
            *m_quadview_edge_fast, *m_quadview_edge_rate, *m_quadview_edge_noise, *m_quadview_edge_feather,
'''+anchor)
    p.write_text(s)
    p=r/'VR.cpp';s=p.read_text()
    anchor='                    m_quadview_seam_mode->draw("Mode");'
    s=once(s,anchor,'''                    m_quadview_edge_mode->draw("Edge matcher");
                    if (m_quadview_edge_mode->value()!=0) {
                        ImGui::TextWrapped("Matches the displayed post-NR/SR focus edge. Temporal stabilizes the wider surrounding correction; the narrow edge responds immediately. Geometry/disocclusion differences remain possible.");
                        m_quadview_edge_strength->draw("Edge match strength");
                        m_quadview_edge_reach->draw("Outward reach (output pixels)");
                        m_quadview_edge_fast->draw("Immediate edge reach (output pixels)");
                        m_quadview_edge_feather->draw("Inward feather (output pixels)");
                        if (m_quadview_edge_mode->value()==2) {
                            m_quadview_edge_rate->draw("Response rate (RGB units/sec; lower = steadier)");
                            m_quadview_edge_noise->draw("Hysteresis noise tolerance");
                        }
                        m_quadview_seam_debug->draw("Show edge correspondence diagnostic");
                    }
'''+anchor.replace('"Mode"','"B31 mode (used when Edge matcher = B31)"'))
    anchor='            requested.feather_fraction=m_quadview_feather->value();'
    s=once(s,anchor,'''            requested.edge_reach_px=m_quadview_edge_reach->value();
            requested.edge_fast_px=m_quadview_edge_fast->value();
            requested.edge_rate=m_quadview_edge_rate->value();
            requested.edge_hysteresis=m_quadview_edge_noise->value();
            if (m_quadview_edge_mode->value()!=0) {
                requested.seam_mode=static_cast<uint32_t>(m_quadview_edge_mode->value()+2);
                requested.seam_strength=m_quadview_edge_strength->value();
                requested.seam_transition_px=m_quadview_edge_feather->value();
            }
'''+anchor)
    p.write_text(s)
    p=r/'vr/D3D12Component.hpp';s=p.read_text();anchor='        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::quadview::dx12::Compositor>> quadview_compositors;'
    s=once(s,anchor,'        std::shared_ptr<uevr::quadview::dx12::EdgeHistoryState> quadview_edge_history;\n'+anchor);p.write_text(s)
    p=r/'vr/D3D12Component.cpp';s=p.read_text()
    anchor='    auto& context=it->second;\n    for (size_t i=0; i<context.texture_contexts.size()'
    s=once(s,anchor,'''    const auto hook=g_framework->get_d3d12_hook();
    const auto queue=hook ? hook->get_command_queue() : nullptr;
    if (!quadview_edge_history || quadview_edge_history->device.Get()!=device || quadview_edge_history->queue.Get()!=queue.Get())
        quadview_edge_history=uevr::quadview::dx12::EdgeHistoryState::create(device,queue.Get());
    auto& context=it->second;
    for (size_t i=0; i<context.texture_contexts.size()''')
    anchor='        if (!comp->prewarm(device,source_format,output_format,timestamp_frequency))\n            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][Prewarm] {}",comp->error());'
    s=once(s,anchor,anchor+'\n        comp->set_edge_history(quadview_edge_history);')
    # B31 depth overlay appends &depth_input to this call.
    anchor='(depth_input.texture || depth_input.show) ? &depth_input : nullptr);'
    s=once(s,anchor,'(depth_input.texture || depth_input.show) ? &depth_input : nullptr, frozen->key.generation);')
    # Old comp leases retain prior state if device/queue changes while slots are in flight.
    anchor='    this->quadview_compositors.clear();'
    s=once(s,anchor,anchor+'\n    this->quadview_edge_history.reset();')
    p.write_text(s)
    print('Applied B35 edge UI and fence-leased shared history ownership')
if __name__=='__main__': main()
