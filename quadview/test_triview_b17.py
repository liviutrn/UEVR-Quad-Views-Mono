#!/usr/bin/env python3
"""B17 source integration contract: run against the ACTUAL generated backend."""
from pathlib import Path
import sys

def main():
    root=Path(sys.argv[1])
    get=lambda name:(root/name).read_text(encoding="utf-8")
    vr=get("src/mods/VR.cpp")
    hdr=get("src/mods/vr/FFakeStereoRenderingHook.hpp")
    hook=get("src/mods/vr/FFakeStereoRenderingHook.cpp")
    native=get("src/mods/vr/QuadViewNativeDelivery.hpp")
    targets=get("src/mods/vr/QuadViewNativeTargets.hpp")
    geo=get("src/mods/vr/QuadViewGeometry.hpp")
    consumer=get("src/mods/vr/D3D12Component.cpp")
    panel=get("src/mods/vr/QuadViewStatusPanel.hpp")
    openxr=get("src/mods/vr/runtimes/OpenXR.hpp")
    assert "valid_native_triview_targets(identities,extents)" in hdr
    assert "valid_native_triview_targets(" in targets
    assert "triview_source_extents(" in geo
    assert "uevr::quadview::triview_source_extents(" in vr
    assert "uevr::quadview::triview_source_extents(" in hook
    assert "extents[1][0]==0 && extents[1][1]==0" in hook
    assert "if (i==1) continue; // Do not spawn a holder or allocate a texture." in hook
    assert "if (i==1) continue; // No physical right periphery" in hook
    assert "if (i==1) continue;" in hook
    assert "if (i==1) {" in hdr
    assert "j!=1 && native_sources[i]==native_sources[j]" in consumer
    assert "frozen->layout.shared_context && i==1" in consumer
    assert "required_roles & uint8_t(1u << i)" in native
    assert "ImGuiWindowFlags_NoScrollWithMouse" in panel
    assert "TriViewScrollBody" not in vr
    assert "Scroll up###TriViewUp" not in vr
    assert 'm_quadview_tri_view->draw(' not in vr
    assert 'm_quadview_compact_targets->draw(' not in vr
    assert "QuadView fallback disabled" in vr
    # B15's head-pose redirection and B7/B11 reprojection code are retained.
    assert "triview_newest_pose_location" in openxr
    assert "m_quadview_depth_reproject->draw(" in vr
    assert "m_quadview_depth_strength->draw(" in vr
    assert "native_target_set_generation" in consumer
    print("B17 generated backend contracts passed: three sources, shader alias, original UI, B15 pose, B11 depth")

if __name__ == "__main__":
    main()
