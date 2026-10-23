#!/usr/bin/env python3
"""Fail-closed safety assertions for post-Build49 passive depth discovery."""
from pathlib import Path
import argparse

def main(root):
    vr=(root/"src/mods/VR.hpp").read_text(encoding="utf-8")
    ui=(root/"src/mods/VR.cpp").read_text(encoding="utf-8")
    hdr=(root/"src/mods/vr/D3D12Component.hpp").read_text(encoding="utf-8")
    dx=(root/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
    assert 'generate_name("DuoViewDepthDiscoveryP0"), false' in vr, "probe MUST default OFF"
    assert 'is_duoview_renderer_active() && m_duo_depth_discovery->value()' in vr, "P0 only in active DuoView"
    assert 'm_duo_depth_discovery->draw(' in ui, "explicit UI activation required"
    assert 'arm_duoview_depth_discovery' in hdr and 'store(200, std::memory_order_release)' in hdr
    assert 'compare_exchange_weak(' in dx, "log count must be bounded without underflow"
    assert 'const bool duo_depth_discovery = vr->is_duoview_depth_discovery_enabled()' in dx
    assert '!vr->is_duoview_renderer_active() && vr->is_dibr_ue5_rdg_depth_capture_enabled()' in dx
    assert 'duo_depth_discovery ||' in dx and '!vr->is_duoview_renderer_active() && vr->is_dibr_depth_trace_requested()' in dx
    assert 'm_dibr_depth_capture.set_depth_trace_expected_extent(' in dx
    assert '[DuoDepthP0][UNVERIFIED]' in dx
    assert 'const auto packet_binding = packet_frame' in dx and 'compositor.record_native(' in dx, "do not remove original Mono compositor"
    assert 'apply_runtime_eye_alignment_persistence_build49' not in ui, "invalid self-reference"
    assert 'const ModToggle::Ptr m_duo_depth_discovery' in vr
    assert 'm_duo_depth_discovery->draw(' in ui
    # ensure no new render mode or stereo DIBR synthesis introduced
    assert 'is_duoview_depth_discovery_enabled()' not in (root/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    assert 'is_duoview_depth_discovery_enabled()' not in (root/"src/mods/vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8")
    print("P0: default OFF, gated observer, no DIBR depth-copy, bounded logging, Build49 renderer unchanged")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("backend",type=Path)
    main(p.parse_args().backend)
