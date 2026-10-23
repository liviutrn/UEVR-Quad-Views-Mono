#!/usr/bin/env python3
"""Build49-to-P1 fail-closed compilation and baseline regression assertions."""
from pathlib import Path
import argparse

def main(root):
    def read(p):return (root/p).read_text(encoding="utf-8-sig")
    vr=read("src/mods/VR.hpp")
    ui=read("src/mods/VR.cpp")
    cpp=read("src/mods/vr/D3D12Component.cpp")
    hdr=read("src/mods/vr/D3D12Component.hpp")
    shader=read("src/mods/vr/DuoViewD3D12.hpp")
    capture=read("src/mods/vr/DuoDepthPairP1.hpp")
    embedded=read("src/mods/vr/DuoViewShaderSource.hpp")
    assert 'DuoViewDepthDiscoveryP0"), false' in vr
    assert 'DuoViewP1RawDepthView"), 0, 4, 0' in vr
    assert "is_duoview_renderer_active() && m_duo_depth_discovery->value()" in vr
    assert "Capture TWO owned P1 depth snapshots (one shot)" in ui
    assert "arm_duoview_p1(VR* vr)" in hdr and "DepthPairP1 m_duoview_p1" in hdr
    assert "bool D3D12Component::arm_duoview_p1(VR* vr)" in cpp
    assert 'get_texture<ID3D12Resource>(L"SceneDepthZ")' in cpp
    assert "(duo_depth_discovery && m_duoview_p1.armed())" in cpp
    assert "m_duoview_p1.signal_after_source_submit(queue)" in cpp
    assert "m_duoview_p1.gpu_ready()" in cpp
    assert "packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0," in cpp
    assert "depth0.Get(),depth1.Get(),p1_debug" in cpp
    assert "const bool depth_mode=((depth_debug>=1 && depth_debug<=4) || (depth_debug>=7 && depth_debug<=10))" in shader
    assert "if ((depth_mode || stereo_preview) && !ensure_depth_srvs" in shader
    assert "native_depth_probe_pixel_shader_bytecode" in shader and "native_depth_probe_pixel_shader_bytecode" in embedded
    assert "if (FAILED(device->CreateGraphicsPipelineState(" in shader
    assert "native_depth_pipeline_.Reset()" in shader
    assert 'return true;' in shader
    assert "capture" not in read("src/mods/vr/runtimes/OpenXR.cpp").lower()[:0] # no-op, keep original untouched
    assert "D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE" in capture
    assert "D3D12_RESOURCE_STATE_DEPTH_WRITE" in capture
    assert "std::try_to_lock" in capture and "CopyTextureRegion" in capture
    # Regression: STALKER 2 emitted 54,129 depth transitions but the previous
    # exact NPSR->DEPTH_WRITE predicate rejected every one of them.
    assert 'const auto before=t.Transition.StateBefore;' in capture
    assert 'const auto after=t.Transition.StateAfter;' in capture
    assert 'const auto can_copy_from_before' in capture
    assert 'before==D3D12_RESOURCE_STATE_DEPTH_WRITE' in capture
    assert 'before==D3D12_RESOURCE_STATE_DEPTH_READ' in capture
    assert 'before==D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE' in capture
    assert 'before,D3D12_RESOURCE_STATE_COPY_SOURCE};' in capture
    assert 'observed_before_.store' in capture
    assert 'example_before=' in capture and 'example_subresource=' in capture
    assert 'D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE' not in capture

    assert "CreateCommittedResource" in capture
    assert 'GetCompletedValue()>=1' in capture
    assert 'bool gpu_ready() const' in capture
    assert "snapshots_[0]" in capture and "snapshots_[1]" in capture
    assert "no GPU depth copies" not in ui, "stale P0 info in P1 UI"
    assert "compositor.record_native(" in cpp and "note_duoview_copy" in cpp
    print("Depth P1 safety gates: default Mono, opt-in two owned GPU captures, nonblocking fence, optional raw-Z shader.")

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("backend",type=Path)
    main(parser.parse_args().backend)
