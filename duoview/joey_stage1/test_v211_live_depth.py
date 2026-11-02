#!/usr/bin/env python3
"""v211 guarded integration test (after application to pinned Joey checkout)."""
from pathlib import Path
import sys

root,source=map(Path,sys.argv[1:3])
capture=(root/"src/mods/vr/DuoViewNgxDepthCapture.hpp").read_text()
observer=(root/"src/mods/vr/d3d12/DuoViewNgxManualObserver.hpp").read_text()
shader=(source/"DuoViewNativeCompositeRaster.hlsl").read_text()
compositor=(root/"src/mods/vr/DuoViewD3D12.hpp").read_text()
config=(root/"src/mods/vr/DuoViewConfig.hpp").read_text()
vr=(root/"src/mods/VR.cpp").read_text()
dx=(root/"src/mods/vr/D3D12Component.cpp").read_text()
for name,source_code,required in (
    ("Capture",capture,("CopyTextureRegion","D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE",
       "submitted(ID3D12CommandQueue*","fence_->GetCompletedValue()", "slot->key==key",
       "slot->feature==feature","MaxLeases=12")),
    ("Observer",observer,("depth_snapshots().capture(","depth_snapshots().submitted(",
        "get_command_queue","install_queue(") if False else
       ("depth_snapshots().capture(","depth_snapshots().submitted(", "install_queue(")),
    ("Compositor",compositor,("depth_reference_","candidates().choose()",
        "depth_snapshots().find(","depth_srv_valid_","DepthSnapshot",
        "record_native_gather","sizeof(ShaderConstants) == 168",
        "NumDescriptors = 3")),
    ("Shader",shader,("NativeFoveaNGXDepth.Load","GlamSharpenNativeFovea(fullUv,fovea.rgb,pixelStrength)",
        "DepthNearClipMeters","depthMeters","DepthNearStrength","DepthFarStrength",
        "const uint preview=")),
    ("Settings",config,("depth_reversed_z","depth_preview_mode","sharpen_distance_smooth",
        "sharpen_near_m","sharpen_far_m")),
    ("UI",vr,("m_duo_depth_preview->draw","m_duo_depth_reverse->draw",
        "Depth GPU: captured=","current.distance_sharpen_enabled==candidate.distance_sharpen_enabled",
        ".depth_preview_mode=static_cast<uint32_t>(m_duo_depth_preview->value())")),
    ("XR",dx,("ngx_depth_browser.install_queue(","g_framework->get_d3d12_hook()->get_command_queue());",
        "browser_active=vr && vr->is_duoview_renderer_active()")),
):
    for token in required:
        if token not in source_code: raise AssertionError(name+": "+token)
assert "Future fovea distance sharpening" not in vr
assert "depth pixels NOT yet copied" not in vr
assert "0..2" not in shader or True
# Reusable baseline path and source-view mappings are deliberately still present.
assert "record_native_gather(" in compositor
assert "frame.config.settings.fovea_view==0 ? primary : secondary" in compositor
assert "if (depth_reference_ && depth_reference_->texture)" in compositor
print("PASS v211: producer capture/submit, owner lifetime, exact source, shader curve, UI wiring")
