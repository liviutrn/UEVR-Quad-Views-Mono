#!/usr/bin/env python3
"""P1 optional in-HMD *raw Z* preview of two owned GPU depth candidates."""
import argparse
from pathlib import Path

def edit(root,path,old,new):
    fp=root/path
    content=fp.read_text(encoding="utf-8-sig")
    n=content.count(old)
    if n!=1: raise RuntimeError(f"P1 visual anchor {path}: expected one, got {n}: {old[:80]}")
    fp.write_text(content.replace(old,new,1),encoding="utf-8",newline="\n")

def main(root):
    edit(root,"src/mods/VR.hpp",
        '''    bool is_duoview_depth_discovery_enabled() const {
        return is_duoview_renderer_active() && m_duo_depth_discovery->value();
    }''',
        '''    bool is_duoview_depth_discovery_enabled() const {
        return is_duoview_renderer_active() && m_duo_depth_discovery->value();
    }
    uint32_t duoview_p1_depth_visual_mode() const {
        return is_duoview_depth_discovery_enabled()
            ? static_cast<uint32_t>(m_duo_depth_visual->value()) : 0u;
    }''')
    edit(root,"src/mods/VR.hpp",
        '    const ModToggle::Ptr m_duo_depth_discovery{ModToggle::create(generate_name("DuoViewDepthDiscoveryP0"), false)};',
        '''    const ModToggle::Ptr m_duo_depth_discovery{ModToggle::create(generate_name("DuoViewDepthDiscoveryP0"), false)};
    const ModInt32::Ptr m_duo_depth_visual{ModSliderInt32::create(generate_name("DuoViewP1RawDepthView"), 0, 4, 0)};''')
    edit(root,"src/mods/VR.hpp",
        '*m_duo_debug_source, *m_duo_depth_discovery,',
        '*m_duo_debug_source, *m_duo_depth_discovery, *m_duo_depth_visual,')
    edit(root,"src/mods/VR.cpp",
        '                    m_duo_depth_discovery->draw("Trace candidate depth DSV resources (opt-in)");',
        '''                    m_duo_depth_discovery->draw("Trace candidate depth DSV resources (opt-in)");
                    m_duo_depth_visual->draw("P1 raw-Z debug 0=Mono 1=Periph candidate 2=Fovea candidate 3=Both 4=UNVERIFIED mask");
                    ImGui::TextWrapped("Raw GPU depth-Z grayscale, NOT linear meters. Capture order 0/1 is unverified as UE0/UE1. Outside ROI is dark; orange seam.");''')
    edit(root,"src/mods/vr/D3D12Component.cpp",
        '''                            ID3D12Resource* recorded_secondary=nullptr;''',
        '''                            const uint32_t p1_debug=m_duoview_p1.gpu_ready() ?
                                vr->duoview_p1_depth_visual_mode() : 0u;
                            auto depth0=p1_debug ? m_duoview_p1.candidate(0) : Microsoft::WRL::ComPtr<ID3D12Resource>{};
                            auto depth1=p1_debug ? m_duoview_p1.candidate(1) : Microsoft::WRL::ComPtr<ID3D12Resource>{};
                            ID3D12Resource* recorded_secondary=nullptr;''')
    edit(root,"src/mods/vr/D3D12Component.cpp",
        '''                                  secondary=m_scene_capture_tex.texture, device,
                                  &recorded, &callback_attempted, &compositor_fault,''',
        '''                                  secondary=m_scene_capture_tex.texture, device,
                                  depth0,depth1,p1_debug,
                                  &recorded, &callback_attempted, &compositor_fault,''')
    edit(root,"src/mods/vr/D3D12Component.cpp",
        '''                                         packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);''',
        '''                                         packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0,
                                         depth0.Get(),depth1.Get(),p1_debug);''')
    print("P1 depth visualization integrated as a separate, opt-in raw-Z shader path")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("backend",type=Path);main(p.parse_args().backend)
