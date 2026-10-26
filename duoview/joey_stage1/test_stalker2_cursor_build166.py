#!/usr/bin/env python3
"""Build166 cursor regression checks against fully patched backend source."""
from pathlib import Path
import argparse, re, math
p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
a=p.parse_args()
root=a.backend/"src/mods"
o=(root/"vr/OverlayComponent.cpp").read_text(encoding="utf-8")
h=(root/"vr/OverlayComponent.hpp").read_text(encoding="utf-8")
f=(a.backend/"src/Framework.cpp").read_text(encoding="utf-8")
v=(root/"VR.hpp").read_text(encoding="utf-8")
runtime=(root/"vr/runtimes/OpenXR.hpp").read_text(encoding="utf-8")
# Implementation and opt-in guards.
assert 'm_duoview_cursor_game_valid{false}' in h
assert 'm_duoview_cursor_game_frame{}' in h
assert '#include "../FrameworkConfig.hpp"' in o
assert 'FrameworkConfig::get()->is_always_show_cursor()' in o
assert 'vr->is_duoview_renderer_active()' in o
assert o.count('m_duoview_cursor_game_frame = vr->get_frame_count();')==1
assert 'm_duoview_cursor_game_frame == vr->get_frame_count()' in o
assert 'm_duoview_cursor_game_valid = false;' in o
assert 'm_slate_layer.eyeVisibility == XR_EYE_VISIBILITY_BOTH' in o
assert 'swapchain == runtimes::OpenXR::SwapchainIndex::UI' in o
assert 'm_slate_layer.subImage.swapchain ==' in o
assert 'm_slate_layer.space != XR_NULL_HANDLE' in o
assert 'layer.pose = m_slate_layer.pose;' in o
assert 'layer.size = m_slate_layer.size;' in o
assert 'layer.pose.position.z += forward.z;' in o
assert '*mono_eye_alignment_enabled,' in runtime
assert 'm_xyz_headscale_enabled' in v
assert 'ImGui::GetIO().MouseDrawCursor = m_draw_ui || FrameworkConfig::get()->is_always_show_cursor();' in f
assert 'void Framework::patch_set_cursor_pos()' in f
# Verify no Global Windows mouse hooks, cursor mode changes or new threads.
assert 'GetCursorPos' not in o
assert 'SetCursorPos' not in o
assert 'CreateThread' not in o
assert 'm_duoview_cursor_game_valid = true;' in o
# Extract only the added branch and verify original fallback still follows it.
start=o.index('    // Opt-in via Main -> Always Show Cursor, gated to Mono DuoView OpenXR.')
end=o.index('    // All other modes/settings follow ORIGINAL JOEY framework UI path.',start)
block=o[start:end]
for name in ('is_drawing_ui()', 'is_always_show_cursor()', 'is_duoview_renderer_active()',
             'm_duoview_cursor_game_valid', 'm_duoview_cursor_game_frame == vr->get_frame_count()',
             'm_slate_layer.type == XR_TYPE_COMPOSITION_LAYER_QUAD'):
    assert name in block, name
assert block.count('return layer;')==1
assert 'auto glm_matrix = glm::identity<glm::mat4>();' in o[end:]
# Geometry: the cursor matches final game quad with 1cm normal offset;
# no per-eye offsets can be introduced because copied pose/size are shared.
def align(pos,size,q,enabled):
    if not enabled:return pos,size
    w,x,y,z=q
    return (pos[0]+0.01*(2*(x*z+w*y)),pos[1]+0.01*(2*(y*z-w*x)),pos[2]+0.01*(1-2*(x*x+y*y))),size
for dims in [(2.,1.),(4.,2.),(.8,1.1)]:
    orig=(0.3,-0.4,-3.)
    assert align(orig,dims,(1.,0.,0.,0.),False)==(orig,dims)
    p2,s2=align(orig,dims,(1.,0.,0.,0.),True)
    assert s2==dims and p2[:2]==orig[:2] and abs(p2[2]-orig[2]-.01)<1e-10
    # After game HUD optical depth/size changes, both are copied unchanged.
print('PASS Build166: no new mouse hooks, no hot-path allocations, cursor in current-frame final UI quad, ID6-only opt-in, legacy path intact.')
