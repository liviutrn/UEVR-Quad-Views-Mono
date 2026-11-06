#!/usr/bin/env python3
"""B26: prove all GPU consumers, new Native Fix frame and clean depth epoch at XR restart.

Apply LAST after B25. Exact generated-source anchors: abort on mismatches.
No per-frame new allocations or GPU waits; only the uncommon XR restart path.
"""
from pathlib import Path
import sys

def once(s, old, new, label):
    count=s.count(old)
    if count!=1:
        raise RuntimeError(f"B26 {label}: expected one anchor, found {count}: {old[:95]!r}")
    return s.replace(old,new,1)

def vr_header(s):
    s=once(s,
        "    uintptr_t m_triview_resize_world_identity{}; // B25 world reload invalidates B14 resize cache.",
        """    uintptr_t m_triview_resize_world_identity{}; // B25 world reload invalidates B14 resize cache.
    // Native Stereo Fix MUST publish a frame newer than the final old XR session.
    std::atomic<uint64_t> m_triview_restart_previous_native_serial{0};""",
        "fresh pair baseline member")
    s=once(s,
        """        if (m_is_d3d12) {
            // The old void path could refuse GPU teardown but still destroy
            // XrSession. Never advance after a veto or partial destruction.
            if (!m_d3d12.openxr().destroy_swapchains()) {""",
        """        if (m_is_d3d12) {
            // B26: on a TriView restart prove ALL UEVR D3D12 consumers have
            // completed, not just the OpenXR texture command slots. The
            // inherited teardown contains wait(INFINITE) for other slots.
            if (m_triview_restart_phase.load(std::memory_order_acquire)==3 &&
                !m_d3d12.mono_consumers_retired()) {
                return std::string{"Waiting for all D3D12 consumers before XR teardown"};
            }
            // The old void path could refuse GPU teardown but still destroy
            // XrSession. Never advance after a veto or partial destruction.
            if (!m_d3d12.openxr().destroy_swapchains()) {""",
        "all-consumer preflight")
    return s

def hook_header(s):
    # Existing monotonic packet serial is owned by the Native Stereo Fix. Do
    # not invent a second accounting mechanism or expose packet pointers.
    return once(s,
        "    uint64_t stalker2_native_epoch() const { return m_stalker2_native_packets.epoch(); }",
        """    uint64_t stalker2_native_epoch() const { return m_stalker2_native_packets.epoch(); }
    uint64_t native_stereo_publication_serial() const {
        return m_native_stereo_packet_serial.load(std::memory_order_acquire);
    }""",
        "native packet serial accessor")

def vr_cpp(s):
    s=once(s,
        """            const bool ready=get_runtime()->got_first_poses && m_fake_stereo_hook &&
                m_fake_stereo_hook->is_native_stereo_fix_state_ready();""",
        """            // Native Fix state 'PairReady' may be retained from the OLD
            // OpenXR session. A new session requires fresh poses AND a newly
            // published native stereo packet; old state is not sufficient.
            const bool fresh_native_pair=m_fake_stereo_hook &&
                m_fake_stereo_hook->native_stereo_publication_serial() >
                    m_triview_restart_previous_native_serial.load(std::memory_order_acquire);
            const bool ready=get_runtime()->got_first_poses && fresh_native_pair &&
                m_fake_stereo_hook->is_native_stereo_fix_state_ready();""",
        "new OpenXR Native Stereo pair proof")
    s=once(s,
        """        } else if (const auto error=reinitialize_openxr()) {
            SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][Restart] checked swapchain teardown pending: {}",*error);
        } else {
            m_triview_restart_phase.store(4,std::memory_order_release);
            spdlog::info("[TriView][Restart] phase=4 fresh OpenXR runtime created; waiting for stereo pair");
        }""",
        """        } else if (!m_d3d12.openxr().discard_completed_depth_on_restart()) {
            // No old depth texture may become the first input in the new XR
            // session, even when B21 permits latest submitted within 250 ms.
            SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][Restart] depth snapshots still leased; postponing XR reset");
        } else {
            const uint64_t old_serial=m_fake_stereo_hook ?
                m_fake_stereo_hook->native_stereo_publication_serial() : 0;
            if (const auto error=reinitialize_openxr()) {
                SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][Restart] checked swapchain teardown pending: {}",*error);
            } else {
                m_triview_restart_previous_native_serial.store(old_serial,std::memory_order_release);
                m_triview_restart_phase.store(4,std::memory_order_release);
                spdlog::info("[TriView][Restart] phase=4 new XR runtime created; waiting for a NEW native pair after serial {}",old_serial);
            }
        }""",
        "session epoch reset and accurate readiness")
    return s

def dx_header(s):
    return once(s,
        "        bool depth_quiescent_for_restart() const;",
        "        bool depth_quiescent_for_restart() const;\n        bool discard_completed_depth_on_restart();",
        "DX12 depth reset declaration")

def dx_cpp(s):
    return once(s,
        """bool D3D12Component::OpenXR::depth_quiescent_for_restart() const {
    return uevr::quadview::ngx::PeripheryDepth::self().restart_quiescent();
}""",
        """bool D3D12Component::OpenXR::depth_quiescent_for_restart() const {
    return uevr::quadview::ngx::PeripheryDepth::self().restart_quiescent();
}

bool D3D12Component::OpenXR::discard_completed_depth_on_restart() {
    return uevr::quadview::ngx::PeripheryDepth::self().discard_completed_for_new_xr_session();
}""",
        "DX12 depth reset wrapper")

def depth_header(s):
    anchor="    static constexpr bool capture_supported() noexcept { return true; }"
    new="""    // B26: the depth pool belongs to the game/D3D12 device, not XrSession,
    // but B21's 250 ms 'latest' policy can otherwise select OLD-session depth
    // immediately after an OpenXR reinitialization. Drop only fully completed
    // and unleased slots. Preserve NVSDK hooks, NGX feature map, device/queue
    // and monotonic recording sequence (these are NOT XR-session objects).
    bool discard_completed_for_new_xr_session() {
        if (enabled_.load(std::memory_order_acquire)) return false;
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock()) return false;
        for (const auto& slot:pool_) {
            if (!slot || slot->pending || slot.use_count()!=1) return false;
            if (slot->submitted) {
                if (!slot->producer_fence) return false;
                if (!depth_copy_complete(slot->producer_fence->GetCompletedValue(),
                                          slot->producer_fence_value)) return false;
            }
        }
        pool_.clear();
        want_w_.store(0,std::memory_order_release);
        want_h_.store(0,std::memory_order_release);
        last_used_age_us_.store(0,std::memory_order_relaxed);
        return true;
    }
"""
    return once(s,anchor,new+anchor,"depth pool session invalidation")

def main():
    root=Path(sys.argv[1])/"src/mods"
    ops={
        root/"VR.hpp":vr_header,
        root/"VR.cpp":vr_cpp,
        root/"vr/FFakeStereoRenderingHook.hpp":hook_header,
        root/"vr/D3D12Component.hpp":dx_header,
        root/"vr/D3D12Component.cpp":dx_cpp,
        root/"vr/QuadViewNgxDepth.hpp":depth_header,
    }
    updated={p:op(p.read_text(encoding="utf-8")) for p,op in ops.items()}
    for p,val in updated.items():
        p.write_text(val,encoding="utf-8",newline="\n")
    print("B26: full D3D12 quiesce preflight; depth epoch invalidation; new-session native-pair serial barrier")

if __name__=="__main__":
    main()
