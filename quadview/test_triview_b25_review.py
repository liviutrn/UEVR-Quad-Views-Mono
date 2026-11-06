#!/usr/bin/env python3
"""Adversarial generated-source regressions for B25 OpenXR restart.

Uses the production source produced by every ordered overlay, not helper fakes.
"""
from pathlib import Path
import sys

def need(s,token,n=1):
    actual=s.count(token)
    if actual!=n: raise AssertionError(f"expected {n} occurrence(s), found {actual}: {token[:110]!r}")

def before(s,a,b):
    if a not in s or b not in s or s.index(a)>=s.index(b):
        raise AssertionError(f"ordering safety requirement failed: {a[:85]!r} must precede {b[:85]!r}")

def main():
    base=Path(sys.argv[1])/"src/mods"
    vr=(base/"VR.cpp").read_text(encoding="utf-8")
    vh=(base/"VR.hpp").read_text(encoding="utf-8")
    dx=(base/"vr/D3D12Component.cpp").read_text(encoding="utf-8")
    hook=(base/"vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    depth=(base/"vr/QuadViewNgxDepth.hpp").read_text(encoding="utf-8")

    # One extra held source-owner lease must not survive a stopped ID7 draw path.
    transition=vr.split("void VR::service_mono_transition_game_thread() {",1)[1].split("\n}\n",1)[0]
    need(transition,"m_triview_hold_set.reset();")
    need(transition,"m_triview_resize_gate.reset();")
    need(transition,"m_triview_resize_world_identity=0;")
    need(vr,"if (new_world!=m_triview_resize_world_identity)")
    before(vr,"if (new_world!=m_triview_resize_world_identity)","const auto decision=m_triview_resize_gate.update(")
    before(transition,"m_quadview.retire_generation(retired_generation);","m_triview_hold_set.reset();")

    # Return to ID7 only after a new, loaded OpenXR session and new poses.
    need(vh,'New OpenXR runtime did not become loaded after restart')
    need(vr,'get_runtime()->got_first_poses')
    need(vr,'m_triview_restart_phase.store(4,std::memory_order_release);')
    need(vr,'m_triview_restart_phase.store(5,std::memory_order_release);')
    need(vr,'bool native_owners_retired=false;')
    need(vr,'m_d3d12.openxr().depth_quiescent_for_restart();')

    # Never wait INFINITE on outstanding D3D12 queues while holding XR mtx.
    destroy=dx.split("bool D3D12Component::OpenXR::destroy_swapchains() {",1)[1].split(
        "bool D3D12Component::OpenXR::pre_acquire(",1)[0]
    need(destroy,"if (context.num_textures_acquired != 0 || context.pre_acquired)")
    need(destroy,"slot && !slot->commands.references_retired()")
    before(destroy,"slot && !slot->commands.references_retired()","this->wait_for_all_copies();")
    before(destroy,"this->wait_for_all_copies();","if (context.num_textures_acquired != 0 || context.pre_acquired)")
    before(destroy,"if (context.num_textures_acquired != 0 || context.pre_acquired)","const bool composition_retired=this->ui_composition.reset();")
    before(destroy,"if (restart_teardown_failed) return false;","this->ui_composition.reset()")
    before(destroy,"const auto slot_live=","commands->poisoned")
    before(destroy,"this->wait_for_all_copies();","const bool composition_retired=this->ui_composition.reset();")
    need(destroy,"if (vr && vr->get_runtime()) vr->get_runtime()->loaded=false;",2)
    need(destroy,"return !restart_teardown_failed;")
    preacquire=dx.split("bool D3D12Component::OpenXR::pre_acquire(",1)[1].split(
        "void D3D12Component::OpenXR::release_acquired(",1)[0]
    need(preacquire,"if (vr && vr->triview_restart_phase()==3) return false;")
    need(dx,"if (!this->destroy_swapchains())")

    # Never mistake a submitted-but-uncompleted NGX copy for safe retirement.
    need(depth,"bool restart_quiescent() const")
    restart_depth=depth.split("bool restart_quiescent() const {",1)[1].split("static constexpr bool capture_supported()",1)[0]
    need(restart_depth,"slot->pending || slot.use_count()!=1")
    need(restart_depth,"slot->producer_fence->GetCompletedValue()")

    # The Native Stereo Fix engine-owned source remains fail-closed on an
    # actual owner/property/device/hook failure; log which category failed.
    need(hook,"const bool owner_live=generation_matches && current_device &&")
    need(hook,'"D3D12-device-mismatch"')
    need(hook,'"render-target-identity-mismatch"')
    need(hook,'"Unreal-owner-property-resource-or-hook-mismatch"')
    need(hook,"if (!owner_live) {")
    print("B25 generated backend: all independent restart, resize-owner, GPU preflight, and error-path source contracts passed")

if __name__=="__main__": main()
