#!/usr/bin/env python3
"""Fail closed on split-eye source regressions after Build165 patch application."""
from pathlib import Path
import sys

root=Path(sys.argv[1]).resolve()
def source(p):
    return (root / p).read_text(encoding="utf-8-sig")
h=source("src/mods/VR.hpp")
c=source("src/mods/VR.cpp")
s=source("src/mods/vr/DuoViewState.hpp")
hook=source("src/mods/vr/FFakeStereoRenderingHook.cpp")
dx=source("src/mods/vr/D3D12Component.cpp")
xr=source("src/mods/vr/runtimes/OpenXR.cpp")
checks={
    "toggle default ON": 'ModToggle::create(generate_name("DuoView165NativeSplitEye"), true)' in h,
    "only split active ID6": 'return is_duoview_renderer_active() && m_duo_split_eye_frozen.load(std::memory_order_acquire);' in h,
    "fovea fixed LEFT view0": 'if (source_split) candidate.fovea_view = 0u;' in c,
    "fovea cropped in projection hook": 'uevr::duoview::apply_frame_projection(double_matrix,*frame,static_cast<unsigned>(view_index));' in hook,
    "crop occurs inside native projection function": 'uevr::duoview::apply_frame_projection(double_matrix,*frame,static_cast<unsigned>(view_index));' in hook and 'apply_foveal_crop(matrix,frame.config.layout);' in s,
    "left/right projection acquired independently": 'get_projection_matrix(VRRuntime::Eye::LEFT)' in c and 'get_projection_matrix(VRRuntime::Eye::RIGHT)' in c,
    "peripheral uses right projection, no foveal crop": '(frame.split_eye && view==1 ? frame.projection_right : frame.projection)' in s,
    "original Stage1 mono-family ID6 policy preserved": 'bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }' in h,
    "split mode exits mono eye centering before both native camera offsets": 'const bool mono = vr->is_using_mono() && !vr->is_duoview_split_eye_enabled();' in hook,
    "native camera eyes pinned UE0 LEFT UE1 RIGHT": 'true_index = view_index;' in hook and hook.count('true_index = view_index;') == 2,
    "native projection index is not zeroed in split mode": 'else if (vr->is_using_mono()) { true_index = 0; }' in hook,

    "freeze source assignment once per draw": 'm_duo_split_eye_frozen.store(m_duo_split_eye->value(), std::memory_order_release);' in h,
    "camera callbacks use frozen per-draw decision": 'm_duo_split_eye_frozen.load(std::memory_order_acquire);' in h,
    "projection source selector follows frozen draw policy": 'const bool source_split = (m_fake_stereo_hook' in c,
    "native right-eye pose is not overwritten": 'view_index == 1 && !vr->is_duoview_split_eye_enabled())' in hook,
    "native right pose is captured": 'vr->duoview_state().camera(key, 1, pose)' in hook,
    "per-eye camera source validation": 'if (!std::isfinite(distance_sq)) return {};' in s,
    "restore old mode still possible": 'm_duo_split_eye->value()=false;' in c,
    "native 0/5 unchanged by policy": 'return is_duoview_renderer_active() && m_duo_split_eye_frozen.load(std::memory_order_acquire);' in h,
    "original DX12 path retained": 'record_native(device, commands.cmd_list.Get(),' in dx,
    "original Mono XR presentation retained": 'note_duoview_copy(std::move(pose),packet_frame->config.key.generation);' in dx and 'duoview_pending_pose' in xr,
    "no stereo / DIBR GPU additions": 'DuoViewR5StereoSlot' not in dx and 'DuoViewDualR5Depth' not in dx,
}
for desc,ok in checks.items():
    print(("PASS" if ok else "FAIL")+": "+desc)
if not all(checks.values()):
    raise SystemExit("Native SplitEye Build165 contract failed")
print("SplitEye source contract OK. Correct game/view behavior still requires STALKER 2 + PSVR2 validation.")
