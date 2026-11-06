#!/usr/bin/env python3
"""B24: guarded TriView OpenXR restart through existing mode-transition retirement.

This patch is deliberately last-in-chain. It must fail on unexpected generated
source, not silently skip safety changes. No performance change in steady state.
"""
from pathlib import Path
import re
import sys

def one(s, before, after, label):
    n = s.count(before)
    if n != 1:
        raise RuntimeError(f"B24 {label}: expected one generated anchor, got {n}")
    return s.replace(before, after, 1)


def apply_vr_header(s):
    s = one(s,
        "    int m_triview_autostart_stage{0};",
        """    int m_triview_autostart_stage{0};
    // 0=idle, 1=requested, 2=Native Stereo transition, 3=drain/restart,
    // 4=XR re-created and Native Stereo warming, 5=TriView return requested.
    std::atomic<int> m_triview_restart_phase{0};
    uintptr_t m_triview_resize_world_identity{}; // B25 world reload invalidates B14 resize cache.
    bool m_triview_restart_saved_native_fix{false};
    std::chrono::steady_clock::time_point m_triview_restart_ready_since{};
    std::chrono::steady_clock::time_point m_triview_restart_resume_since{};
    """.rstrip(), "state members")
    s = one(s,
        "    bool is_quadview_mode_selected() const { return m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO; }",
        """    bool is_quadview_mode_selected() const { return m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO; }
    int triview_restart_phase() const noexcept {
        return m_triview_restart_phase.load(std::memory_order_acquire);
    }""", "phase accessor")
    s = one(s,
        """        if (m_is_d3d12) {
            m_d3d12.openxr().destroy_swapchains();
        } else {
            m_d3d11.openxr().destroy_swapchains();
        }

        m_openxr.reset();""",
        """        if (m_is_d3d12) {
            // The old void path could refuse GPU teardown but still destroy
            // XrSession. Never advance after a veto or partial destruction.
            if (!m_d3d12.openxr().destroy_swapchains()) {
                spdlog::warn("[TriView][Restart] XR resource retirement refused; preserving old runtime");
                return std::string{"OpenXR teardown unsafe/pending; old session retained"};
            }
        } else {
            m_d3d11.openxr().destroy_swapchains();
        }

        m_openxr.reset();""", "propagate teardown veto")
    # A nullopt from initialize_openxr is not sufficient proof of success:
    # some original initialize_* error paths return nullopt but set loaded=false.
    s=one(s,
        "        auto e = initialize_openxr();\n\n        if (e) {",
        "        auto e = initialize_openxr();\n"
        "        if (!e && (!m_openxr || !m_openxr->loaded || !m_runtime || !m_runtime->loaded))\n"
        "            e = std::string{\"New OpenXR runtime did not become loaded after restart\"};\n\n"
        "        if (e) {",
        "check new XR loaded")
    return s


def apply_vr_cpp(s):
    anchor = """void VR::service_mono_transition_game_thread() {
    auto& selection = m_rendering_method->selection();
"""
    injection = """void VR::service_mono_transition_game_thread() {
    auto& selection = m_rendering_method->selection();
    // TriView B24: use the EXISTING tracked ID7->Native transition as the
    // producer quiesce. Never flip the view count within an active family.
    const auto restart_phase=m_triview_restart_phase.load(std::memory_order_acquire);
    if (restart_phase==1 && !selection.pending() &&
        selection.active()==RenderingMethod::QUAD_VIEWS_STEREO) {
        m_triview_restart_saved_native_fix=m_native_stereo_fix->value();
        m_native_stereo_fix->value()=true;
        m_rendering_method->set_save_override(RenderingMethod::QUAD_VIEWS_STEREO);
        selection.request(RenderingMethod::NATIVE_STEREO);
        m_triview_restart_phase.store(2,std::memory_order_release);
        spdlog::info("[TriView][Restart] phase=2 native-mode retirement requested");
    } else if (restart_phase==2 && !selection.pending() &&
               selection.active()==RenderingMethod::NATIVE_STEREO) {
        // The mode commit already checked the old generation's engine tails
        // and retired its producer/target publication. GPU retirement follows.
        m_triview_restart_phase.store(3,std::memory_order_release);
        spdlog::info("[TriView][Restart] phase=3 awaiting native owner/depth/GPU retirement");
    } else if (restart_phase==4) {
        const auto now=std::chrono::steady_clock::now();
        if (m_triview_restart_resume_since==std::chrono::steady_clock::time_point{})
            m_triview_restart_resume_since=now;
        if (!selection.pending() && selection.active()==RenderingMethod::NATIVE_STEREO &&
            get_runtime() && get_runtime()->loaded) {
            const bool ready=get_runtime()->got_first_poses && m_fake_stereo_hook &&
                m_fake_stereo_hook->is_native_stereo_fix_state_ready();
            if (ready && m_triview_restart_ready_since==std::chrono::steady_clock::time_point{})
                m_triview_restart_ready_since=now;
            if (!ready) m_triview_restart_ready_since={};
            // Only restore after the newly created XR runtime has a genuine
            // Native Stereo Fix pair. Do not use an unconditional timeout.
            if (ready && now-m_triview_restart_ready_since>=std::chrono::seconds(2)) {
                selection.request(RenderingMethod::QUAD_VIEWS_STEREO);
                m_triview_restart_phase.store(5,std::memory_order_release);
                spdlog::info("[TriView][Restart] phase=5 new XR pose/pair ready; returning to TriView");
            } else if (now-m_triview_restart_resume_since>std::chrono::seconds(25)) {
                SPDLOG_WARNING_EVERY_N_SEC(5,"[TriView][Restart] New XR Native Fix pair not ready; preserving Native Stereo, no unsafe fallback to ID7");
            }
        }
    } else if (restart_phase==5 && !selection.pending() &&
               selection.active()==RenderingMethod::QUAD_VIEWS_STEREO) {
        m_native_stereo_fix->value()=m_triview_restart_saved_native_fix;
        m_rendering_method->set_save_override(-1);
        m_triview_restart_ready_since={};
        m_triview_restart_resume_since={};
        m_triview_restart_phase.store(0,std::memory_order_release);
        spdlog::info("[TriView][Restart] phase=0 TriView restored with new OpenXR session");
    }
"""
    s=one(s,anchor,injection,"GT lifecycle")
    # B14 keeps resize sizes across draws but its key was only physical extents.
    # Save-game world replacement can give the SAME extents with a NEW owner.
    # Reset stale size assumptions when the published native world changes.
    s=one(s,
        "                if (m_triview_hold_set && !m_triview_hold_set->complete()) m_triview_hold_set.reset();\n"
        "                auto wanted=uevr::quadview::make_layout(",
        "                if (m_triview_hold_set && !m_triview_hold_set->complete()) m_triview_hold_set.reset();\n"
        "                const uintptr_t new_world=m_triview_hold_set ? m_triview_hold_set->world_identity : 0;\n"
        "                if (new_world!=m_triview_resize_world_identity) {\n"
        "                    m_triview_resize_world_identity=new_world;\n"
        "                    m_triview_resize_gate.reset();\n"
        "                    SPDLOG_INFO(\"[TriView][Resize] published world identity changed; discard prior-size cache\");\n"
        "                }\n"
        "                auto wanted=uevr::quadview::make_layout(",
        "invalidate resize sizes on world change")
    # A B14 held-set shared_ptr is a lease on each old native source owner.
    # Transition can stop calling quadview_begin_frame(), so its ordinary
    # end-of-draw reset might never run. Explicitly release it at the mode
    # commit boundary AFTER the production engine-tail retirement check.
    s=one(s,
        "    m_quadview.retire_generation(retired_generation);",
        "    m_quadview.retire_generation(retired_generation);\n"
        "    m_triview_hold_set.reset();\n"
        "    m_triview_resize_gate.reset();\n"
        "    m_triview_resize_world_identity=0;\n"
        "    m_triview_pending_extents_valid=false;",
        "release B14 held source at mode transition")
    start=s.index("    if (runtime->wants_reinitialize) {",s.index("void VR::on_post_present() {"))
    end=s.index("\n}\n\nuint32_t VR::get_hmd_width()",start)
    old=s[start:end]
    expected = """    if (runtime->wants_reinitialize) {
        std::scoped_lock _{m_reinitialize_mtx};

        if (runtime->is_openvr()) {
            m_openvr->wants_reinitialize = false;
            reinitialize_openvr();
        } else if (runtime->is_openxr()) {
            m_openxr->wants_reinitialize = false;
            reinitialize_openxr();
        }
    }"""
    if old.count("            const auto error = reinitialize_openxr();")!=1 or old.count("m_openxr->wants_reinitialize = false;")!=1:
        raise RuntimeError(f"B24 reset source mismatch: {old[-2300:]!r}")
    new = """    if (runtime->wants_reinitialize) {
        std::scoped_lock restart_lock{m_reinitialize_mtx};
        if (runtime->is_openvr()) {
            m_openvr->wants_reinitialize = false;
            reinitialize_openvr();
        } else if (runtime->is_openxr()) {
            m_openxr->wants_reinitialize = false;
            if (m_is_d3d12 && is_quadview_mode_selected() &&
                m_triview_restart_phase.load(std::memory_order_acquire)==0) {
                // Do NOT destroy any XR resource while ID7 producers are live.
                m_triview_restart_phase.store(1,std::memory_order_release);
                spdlog::info("[TriView][Restart] phase=1 requested; transitioning to Native Stereo first");
            } else if (m_triview_restart_phase.load(std::memory_order_acquire)==0) {
                // All other modes retain the existing user-visible behavior,
                // with the new checked teardown instead of a void veto.
                if (const auto error=reinitialize_openxr())
                    spdlog::warn("[OpenXR][Restart] {}",*error);
            } else {
                spdlog::info("[TriView][Restart] Duplicate request coalesced");
            }
        }
    }
    if (m_is_d3d12 && m_triview_restart_phase.load(std::memory_order_acquire)==3 &&
        runtime->is_openxr() && !is_quadview_mode_selected()) {
        std::scoped_lock restart_lock{m_reinitialize_mtx};
        // Missing manager is UNKNOWN, not proof of retired engine owners.
        bool native_owners_retired=false;
        if (m_fake_stereo_hook) if (auto* rtm=m_fake_stereo_hook->get_render_target_manager()) {
            const auto d=rtm->get_quadview_native_retirement_diagnostics();
            native_owners_retired=!d.busy && !d.pending.count && !d.pending.truncated &&
                !d.staged.count && !d.staged.truncated &&
                !d.in_flight.count && !d.in_flight.truncated &&
                !d.ready.count && !d.ready.truncated;
        }
        // The periphery NGX copy pool can submit on a different DIRECT queue.
        // Do not confuse the compositor's completed fence with its producer fence.
        const bool depth_retired=m_d3d12.openxr().depth_quiescent_for_restart();
        if (!native_owners_retired || !depth_retired) {
            SPDLOG_INFO_EVERY_N_SEC(2,"[TriView][Restart] waiting native_owners={} depth_queues={}",
                native_owners_retired,depth_retired);
        } else if (const auto error=reinitialize_openxr()) {
            SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][Restart] checked swapchain teardown pending: {}",*error);
        } else {
            m_triview_restart_phase.store(4,std::memory_order_release);
            spdlog::info("[TriView][Restart] phase=4 fresh OpenXR runtime created; waiting for stereo pair");
        }
    }"""
    # Other overlay callbacks may appear before/after the original reset
    # branch. Preserve them byte-for-byte: change only this one XR call.
    replacement="""            const auto error = [&]() -> std::optional<std::string> {
                if (m_is_d3d12 && is_quadview_mode_selected() &&
                    m_triview_restart_phase.load(std::memory_order_acquire)==0) {
                    m_triview_restart_phase.store(1,std::memory_order_release);
                    spdlog::info("[TriView][Restart] phase=1 queued via native-mode transition");
                    return std::string{"TriView restart queued; engine owners must retire first"};
                }
                if (m_triview_restart_phase.load(std::memory_order_acquire)!=0) {
                    spdlog::info("[TriView][Restart] duplicate request coalesced");
                    return std::string{"TriView restart already pending"};
                }
                return reinitialize_openxr();
            }();"""
    changed=old.replace("            const auto error = reinitialize_openxr();",replacement,1)
    stage3=new[new.index("    if (m_is_d3d12 && m_triview_restart_phase"):]
    return s[:start]+changed+"\n"+stage3+s[end:]


def apply_dx_header(s):
    return one(s,"        void destroy_swapchains();",
               "        bool destroy_swapchains();\n        bool depth_quiescent_for_restart() const;\n        bool restart_teardown_failed{false};",
               "XR header status signature")


def apply_dx_cpp(s):
    begin=s.index("void D3D12Component::OpenXR::destroy_swapchains() {")
    end=s.index("\nbool D3D12Component::OpenXR::pre_acquire(",begin)
    b=s[begin:end]
    b=one(b,"void D3D12Component::OpenXR::destroy_swapchains() {",
          "bool D3D12Component::OpenXR::destroy_swapchains() {","checked signature")
    b=one(b,
       """    const bool composition_retired = this->ui_composition.reset();
    const bool game_alpha_retired = this->game_ui_alpha.reset();
    const bool framework_alpha_retired = this->framework_ui_alpha.reset();

    if (this->contexts.empty()) {
        return;
    }""",
       """    // The preflight must run before ANY UI/compositor/swapchain mutation.
    if (restart_teardown_failed) return false;
    // Only enter original wait_for_all_copies() with all D3D12 fences
    // retired, so its inherited wait(INFINITE) is already satisfied. An
    // XR image may still be acquired: the original helper releases it.
    // New pre-acquisitions are blocked in restart phase 3.
    for (const auto& [index,context]:this->contexts) {
        for (const auto& slot:context.texture_contexts)
            if (slot && !slot->commands.references_retired()) return false;
    }
    // Compositor-map keys are raw pointers; prove that the command context
    // still belongs to the currently retained swapchain BEFORE dereferencing.
    const auto slot_live=[&](const d3d12::CommandContext* command) {
        if (!command) return false;
        for (const auto& [index,context]:this->contexts) {
            for (const auto& slot:context.texture_contexts) {
                if (slot && &slot->commands==command) return true;
            }
        }
        return false;
    };
    for (const auto& [commands, compositor] : this->quadview_compositors)
        if (compositor && (!slot_live(commands) || commands->poisoned)) return false;
    for (const auto& [commands, compositor] : this->duoview_compositors)
        if (compositor && (!slot_live(commands) || commands->poisoned)) return false;
    if (this->contexts.empty() && this->quadview_compositors.empty() &&
        this->duoview_compositors.empty()) {
        return this->ui_composition.reset() && this->game_ui_alpha.reset() &&
            this->framework_ui_alpha.reset();
    }""",
       "move UI mutation after proof")
    b=one(b,"    this->wait_for_all_copies();",
       """    this->wait_for_all_copies();
    // The original helper releases any XR images already acquired at the
    // transaction boundary. An XR release failure must veto destruction.
    for (const auto& [index,context]:this->contexts)
        if (context.num_textures_acquired != 0 || context.pre_acquired)
            return false;
    // All acquired XR contexts must be released and every GPU command-slot
    // fence proven complete before UI reset or compositor destruction.
    for (const auto& [commands, compositor] : this->quadview_compositors)
        if (compositor && (!slot_live(commands) || !commands->references_retired())) return false;
    for (const auto& [commands, compositor] : this->duoview_compositors)
        if (compositor && (!slot_live(commands) || !commands->references_retired())) return false;
    const bool composition_retired=this->ui_composition.reset();
    const bool game_alpha_retired=this->game_ui_alpha.reset();
    const bool framework_alpha_retired=this->framework_ui_alpha.reset();
    if (!composition_retired || !game_alpha_retired || !framework_alpha_retired) {
        // UI reset can partially mutate state. Do not continue rendering with
        // uncertain descriptors or pretend a successful XR restart.
        restart_teardown_failed=true;
        if (vr && vr->get_runtime()) vr->get_runtime()->loaded=false;
        spdlog::error("[TriView][Restart] UI retirement incomplete; XR rendering stopped, restart game");
        return false;
    }""","post-wait UI proof")
    b=one(b,'                spdlog::error("[VR] Failed to destroy swapchain {}.", i);',
       '                spdlog::error("[VR] Failed to destroy swapchain {}.", i);\n'
       '                restart_teardown_failed=true;\n'
       '                if (vr && vr->get_runtime()) vr->get_runtime()->loaded=false;',
       "handle XR destroy failure")
    if b.count("    this->contexts.clear();")!=1:
        raise RuntimeError("B24: final context-clear anchor not unique")
    b=one(b,"    vr->m_openxr->swapchains.clear();",
      "    vr->m_openxr->swapchains.clear();\n    return !restart_teardown_failed;",
      "checked destruction result")
    # The wait(INFINITE) in the original helper is now reachable ONLY after
    # the initial nonblocking completion/acquired-image check above.
    # Existing overlay vetoes were void and now need explicit failure values.
    b=re.sub(r"\breturn\s*;", "return false;", b)
    # Except an empty context map with successful UI teardown, all paths need
    # to reach the last checked return. No implicit successful fallthrough.
    s=s[:begin]+b+s[end:]
    s=one(s,"    this->destroy_swapchains();\n    if (!this->duoview_compositors.empty())",
       """    if (!this->destroy_swapchains())
        return "OpenXR swapchain destruction postponed: resources still live";
    if (!this->duoview_compositors.empty())""","create preflight caller")
    # Scope the interception to pre_acquire (not the other XR methods with
    # similar runtime-null checks).
    pre_start=s.index("bool D3D12Component::OpenXR::pre_acquire(")
    pre_end=s.index("\nvoid D3D12Component::OpenXR::release_acquired(",pre_start)
    pre=s[pre_start:pre_end]
    pre=one(pre,
        "    auto vr = VR::get();\n\n    if (vr == nullptr || vr->m_openxr == nullptr) {",
        "    auto vr = VR::get();\n"
        "    // During phase 3, no new async image acquisitions on the old XR session.\n"
        "    if (vr && vr->triview_restart_phase()==3) return false;\n\n"
        "    if (vr == nullptr || vr->m_openxr == nullptr) {",
        "stop async acquisitions")
    s=s[:pre_start]+pre+s[pre_end:]
    s=one(s,
        "bool D3D12Component::OpenXR::destroy_swapchains() {",
        "bool D3D12Component::OpenXR::depth_quiescent_for_restart() const {\n"
        "    return uevr::quadview::ngx::PeripheryDepth::self().restart_quiescent();\n"
        "}\n\n"
        "bool D3D12Component::OpenXR::destroy_swapchains() {",
        "D3D12 restart depth wrapper")
    return s


def apply_depth(s):
    anchor="    static constexpr bool capture_supported() noexcept { return true; }"
    addition="""    // Rare runtime restart only. Tracked foreign-queue copies must actually
    // have completed; the old session's depth snapshots cannot be reused.
    bool restart_quiescent() const {
        if (enabled_.load(std::memory_order_acquire)) return false;
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock()) return false;
        for (const auto& slot:pool_) {
            if (!slot || slot->pending || slot.use_count()!=1) return false;
            if (slot->submitted) {
                if (!slot->producer_fence) return false;
                const auto completed=slot->producer_fence->GetCompletedValue();
                if (!depth_copy_complete(completed,slot->producer_fence_value)) return false;
            }
        }
        return true;
    }
"""
    return one(s,anchor,addition+anchor,"depth foreign-queue quiesce")


def main():
    root=Path(sys.argv[1])/"src/mods"
    ops={
        root/"VR.hpp":apply_vr_header,
        root/"VR.cpp":apply_vr_cpp,
        root/"vr/D3D12Component.hpp":apply_dx_header,
        root/"vr/D3D12Component.cpp":apply_dx_cpp,
        root/"vr/QuadViewNgxDepth.hpp":apply_depth,
    }
    updated={p:fn(p.read_text(encoding="utf-8")) for p,fn in ops.items()}
    for p,s in updated.items():p.write_text(s,encoding="utf-8")
    print("B24: generated backend checked XR teardown and temporary Native Stereo quiesce applied")

if __name__=="__main__": main()
