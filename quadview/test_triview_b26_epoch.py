#!/usr/bin/env python3
"""B26 adversarial GENERATED backend checks; no mocked production implementations."""
from pathlib import Path
import sys

def once(s,fragment,count=1):
    n=s.count(fragment)
    if n!=count: raise AssertionError(f"Expected {count}, got {n}: {fragment[:105]!r}")

def order(s,a,b):
    if a not in s or b not in s or s.index(a)>=s.index(b):
        raise AssertionError(f"Unsafe order: {a[:95]} must precede {b[:95]}")


def check_generated_post_present_cpp(code):
    """Regression for B25's stale Python splice offset (C2065, C2001)."""
    start=code.index("void VR::on_post_present() {")
    end=code.index("\nuint32_t VR::get_hmd_width()",start)
    body=code[start:end]
    assert body.count("if (runtime->wants_reinitialize)") == 1
    assert body.count("m_triview_restart_phase.load(std::memory_order_acquire)==3") == 1
    # Shallow C++ scanner: skip comments, string/char literals and escapes.
    # A valid generated function must have balanced braces and no raw newlines
    # inside ordinary string literals. Neither B24 nor B26 uses raw strings
    # in this function.
    mode="code"
    depth=0
    i=0
    while i<len(body):
        ch=body[i]
        nx=body[i+1] if i+1<len(body) else ""
        if mode=="code":
            if ch=="/" and nx=="/": mode="line"; i+=2; continue
            if ch=="/" and nx=="*": mode="block"; i+=2; continue
            if ch=='"': mode="string"
            elif ch=="'": mode="char"
            elif ch=="{": depth+=1
            elif ch=="}":
                depth-=1
                if depth<0: raise AssertionError("extra closing brace in generated on_post_present")
        elif mode=="line":
            if ch=="\n": mode="code"
        elif mode=="block":
            if ch=="*" and nx=="/": mode="code"; i+=2; continue
        elif mode in ("string","char"):
            if ch=="\\":
                i+=2
                continue
            if ch==("\x22" if mode=="string" else "'"): mode="code"
            elif ch=="\n":
                raise AssertionError("unterminated C++ string / char in generated on_post_present")
        i+=1
    if depth!=0 or mode not in ("code","line"):
        raise AssertionError(f"invalid generated on_post_present structure: depth={depth}, mode={mode}")
    return True

def main():
    src=Path(sys.argv[1])/"src/mods"
    h=(src/"VR.hpp").read_text(encoding="utf-8")
    vr=(src/"VR.cpp").read_text(encoding="utf-8")
    hook=(src/"vr/FFakeStereoRenderingHook.hpp").read_text(encoding="utf-8")
    dx=(src/"vr/D3D12Component.cpp").read_text(encoding="utf-8")
    dh=(src/"vr/D3D12Component.hpp").read_text(encoding="utf-8")
    ngx=(src/"vr/QuadViewNgxDepth.hpp").read_text(encoding="utf-8")

    reinit=h.split("std::optional<std::string> reinitialize_openxr() {",1)[1].split("    float m_nearz{",1)[0]
    # B25 already checks every XR command-slot fence. Avoid requiring all
    # unrelated active game command queues to be idle.
    assert "!m_d3d12.mono_consumers_retired()" not in reinit
    once(reinit,"!m_d3d12.openxr().destroy_swapchains()")
    order(reinit,"!m_d3d12.openxr().destroy_swapchains()","m_openxr.reset();")

    once(hook,"uint64_t native_stereo_publication_serial() const")
    once(hook,"return m_native_stereo_packet_serial.load(std::memory_order_acquire);")
    once(h,"std::atomic<uint64_t> m_triview_restart_previous_native_serial{0};")
    once(vr,"m_triview_restart_previous_native_serial.store(old_serial,std::memory_order_release);")
    once(vr,"const bool fresh_native_pair=")
    once(vr,"m_fake_stereo_hook->native_stereo_publication_serial() >")
    once(vr,"const bool ready=get_runtime()->got_first_poses && fresh_native_pair &&")
    order(vr,"const uint64_t old_serial=m_fake_stereo_hook ?","if (const auto error=reinitialize_openxr())")
    order(vr,"m_triview_restart_previous_native_serial.store(old_serial,std::memory_order_release);",
          "m_triview_restart_phase.store(4,std::memory_order_release);")

    once(dh,"bool discard_completed_depth_on_restart();")
    once(dx,"bool D3D12Component::OpenXR::discard_completed_depth_on_restart() {")
    once(vr,"!m_d3d12.openxr().discard_completed_depth_on_restart()")
    order(vr,"!m_d3d12.openxr().discard_completed_depth_on_restart()","const uint64_t old_serial=")

    section=ngx.split("bool discard_completed_for_new_xr_session() {",1)[1].split("static constexpr bool capture_supported()",1)[0]
    once(section,"if (enabled_.load(std::memory_order_acquire)) return false;")
    once(section,"if (!lock.owns_lock()) return false;")
    once(section,"slot->pending || slot.use_count()!=1")
    once(section,"slot->producer_fence->GetCompletedValue()")
    order(section,"slot->producer_fence->GetCompletedValue()","pool_.clear();")
    order(section,"pool_.clear();","want_w_.store(0,std::memory_order_release);")
    assert "queue_.Reset()" not in section and "fence_.Reset()" not in section
    assert "execute_.reset()" not in section and "evals_" not in section
    # Old catch-up by timestamp is explicitly 250ms and can span XR session;
    # invalidating completed slots is required, not optional.
    # B21 changed the depth selector on the B18 snapshot pool; no specific
    # function name is required for the session-reset safety proof.

    check_generated_post_present_cpp(vr)
    print("B26 production-source restart contracts: XR-only fencing, fresh NativeStereo packet, session-isolated depth PASSED")

if __name__=="__main__":main()
