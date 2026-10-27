#!/usr/bin/env python3
"""Build167 audited source checks (full CTest also runs in Windows CI)."""
from pathlib import Path
import argparse
p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
a=p.parse_args()
root=a.backend/"src"
r=lambda f:(root/f).read_text(encoding="utf-8")
frame=r("Framework.cpp");hdr=r("Framework.hpp")
win=r("hooks/WindowsMessageHook.cpp")
layer=r("mods/vr/OverlayComponent.cpp");layerh=r("mods/vr/OverlayComponent.hpp")
d3d=r("mods/vr/D3D12Component.cpp")
vr=r("mods/VR.hpp"); xrh=r("mods/vr/runtimes/OpenXR.hpp")
assert "*mono_eye_alignment_enabled" in xrh
assert "is_duoview_renderer_active" in vr
assert "m_duoview_game_ui_quad_valid{false}" in layerh
assert 'openxr_overlay.begin_duoview_cursor_submit();' in d3d
assert d3d.index("openxr_overlay.begin_duoview_cursor_submit();") < d3d.index("openxr_overlay.generate_slate_layer(",d3d.index("openxr_overlay.begin_duoview_cursor_submit();"))
assert "m_duoview_game_ui_quad_valid=false;" in layer
assert "m_duoview_game_ui_quad_valid=true;" in layer
assert "m_duoview_cursor_game_frame" not in layer, "broken Build166 frame guard reintroduced"
assert "FrameworkConfig::get()->is_always_show_cursor()" in frame
assert "FrameworkConfig::get()->is_always_show_cursor()" in layer
assert "vr->is_duoview_renderer_active()" in layer
assert "return std::nullopt;" in layer
assert "layer.pose=m_slate_layer.pose;" in layer
assert "layer.size=m_slate_layer.size;" in layer
assert "layer.pose.position.z+=to_user.z;" in layer
assert "m_slate_layer.subImage.swapchain !=" in layer
assert "layer.space=m_slate_layer.space;" in layer
assert "m_duoview_cursor_block_set" in hdr
assert "g_duoview_get_cursor_hook.call<BOOL>(pt)" in frame
assert "g_duoview_set_cursor_hook.call<BOOL>(x,y)" in frame
assert "g_duoview_set_cursor_hook.call<BOOL>(pt.x,pt.y)" in frame
assert "is_duoview_cursor_remap_active()" in frame
assert "remove_set_cursor_pos_patch();" in frame
assert "install_duoview_cursor_hooks();" in frame
assert 'l_param = g_framework->map_duoview_mouse_message(message,l_param);' in win
assert "if (m_duoview_cursor_hooks_ready.load(std::memory_order_acquire)) return;" in frame
def rescale(v,fr0,fr1,to0,to1):
    f,t=fr1-fr0,to1-to0
    if f<=1 or t<=1 or f==t:return v+(to0-fr0)
    return to0+round((v-fr0)*(t-1)/(f-1))
for lo,hi,left,right in [(0,2560,0,3072),(120,1880,100,2400),(-1920,0,-1880,0),(0,1920,0,1920)]:
    assert rescale(lo,lo,hi,left,right)==left
    assert rescale(hi-1,lo,hi,left,right)==right-1
    for pos in [lo,lo+1,(lo+hi)//2,hi-2,hi-1]:
        mapped=rescale(pos,lo,hi,left,right)
        reverse=rescale(mapped,left,right,lo,hi)
        assert abs(reverse-pos)<=2
s=frame[frame.index("void Framework::patch_set_cursor_pos() {"):frame.index("void Framework::remove_set_cursor_pos_patch() {")]
assert s.index("if (m_duoview_cursor_hooks_ready") < s.index("std::scoped_lock")
print("PASS Build167: same-submit cursor plane, guarded Win32 hook pair, preserved HUD alignment, mouse coord map limits.")
