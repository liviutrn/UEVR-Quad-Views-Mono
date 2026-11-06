#!/usr/bin/env python3
"""B24 final GENERATED production-source contracts, not mock-only tests."""
from pathlib import Path
import sys

def exactly(s, token, n=1):
    found=s.count(token)
    if found!=n:
        raise AssertionError(f"expected {n} occurrence(s) of {token[:90]!r}; got {found}")

def main():
    mods=Path(sys.argv[1])/"src/mods"
    h=(mods/"VR.hpp").read_text(encoding="utf-8")
    vr=(mods/"VR.cpp").read_text(encoding="utf-8")
    dh=(mods/"vr/D3D12Component.hpp").read_text(encoding="utf-8")
    dx=(mods/"vr/D3D12Component.cpp").read_text(encoding="utf-8")
    depth=(mods/"vr/QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
    exactly(h,"if (!m_d3d12.openxr().destroy_swapchains())")
    exactly(dh,"bool destroy_swapchains();")
    exactly(dx,"bool D3D12Component::OpenXR::destroy_swapchains() {")
    exactly(dx,"bool D3D12Component::OpenXR::depth_quiescent_for_restart() const {")
    exactly(depth,"bool restart_quiescent() const")
    exactly(vr,'selection.request(RenderingMethod::NATIVE_STEREO);',2) # startup + restart
    exactly(vr,'m_triview_restart_phase.store(3,std::memory_order_release);')
    exactly(vr,'m_triview_restart_phase.store(4,std::memory_order_release);')
    exactly(vr,'m_triview_restart_phase.store(5,std::memory_order_release);')
    exactly(vr,'const bool depth_retired=m_d3d12.openxr().depth_quiescent_for_restart();')
    body=dx.split("bool D3D12Component::OpenXR::destroy_swapchains() {",1)[1].split(
        "bool D3D12Component::OpenXR::pre_acquire(",1)[0]
    assert "void D3D12Component::OpenXR::destroy_swapchains()" not in dx
    assert "restart_teardown_failed" in body
    assert body.index("if (restart_teardown_failed)") < body.index("this->ui_composition.reset()")
    assert body.index("this->wait_for_all_copies()") < body.index("const bool composition_retired=this->ui_composition.reset();")
    assert body.index("!commands->references_retired()") < body.index("const bool composition_retired=this->ui_composition.reset();")
    assert body.index('restart_teardown_failed=true;') > body.index("const bool composition_retired=this->ui_composition.reset();")
    assert 'return !restart_teardown_failed;' in body
    assert "if (!this->destroy_swapchains())" in dx
    assert 'xrDestroySession' not in body
    assert 'get_runtime()->got_first_poses' in vr
    assert 'slot->producer_fence->GetCompletedValue()' in depth
    assert 'm_triview_restart_phase.load(std::memory_order_acquire)==3' in vr
    print("B24 generated OpenXR restart/teardown source contracts passed")

if __name__=="__main__": main()
