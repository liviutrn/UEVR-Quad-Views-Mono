#!/usr/bin/env python3
"""Build52: closed-admission maintenance and transactional STALKER 2 mode changes.

No ledger is cleared to unblock a transition; CPU owner and GPU fence checks
remain mandatory. Maintenance callbacks carry generation/request identity and
cannot publish images or acknowledge resource retirement.
"""
from pathlib import Path
import shutil
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Transition overlay expected one anchor: {old[:110]!r}")
    return text.replace(old, new, 1)


def main():
    root = Path(sys.argv[1])
    base = root / "src/mods/vr"
    paths = {name: root / name for name in (
        "src/mods/VR.cpp", "src/mods/vr/MonoRenderingPolicy.hpp",
        "src/mods/vr/FFakeStereoRenderingHook.cpp")}
    text = {name: path.read_text(encoding="utf-8-sig") for name, path in paths.items()}
    policy = text["src/mods/vr/MonoRenderingPolicy.hpp"]
    policy = once(policy, "    void request(int32_t value) {", """    void set_defer_all_transitions(bool enabled) {
        std::scoped_lock lock{m_mutex};
        m_defer_all_transitions = enabled;
    }
    bool cancel_request(uint64_t token) {
        std::scoped_lock lock{m_mutex};
        if (request_token()!=token || !pending()) return false;
        request_locked(active());
        return true;
    }
    void request(int32_t value) {""")
    policy = once(policy, "        if (!is_deferred_family(active()) && !is_deferred_family(value)) {",
        "        if (!m_defer_all_transitions && !is_deferred_family(active()) && !is_deferred_family(value)) {")
    policy = once(policy, "    bool m_initialized{};", "    bool m_initialized{};\n    bool m_defer_all_transitions{};")
    text["src/mods/vr/MonoRenderingPolicy.hpp"] = policy

    c = text["src/mods/VR.cpp"]
    c = once(c, "void VR::on_config_load(const utility::Config& cfg, bool set_defaults) {\n    ZoneScopedN(__FUNCTION__);",
        "void VR::on_config_load(const utility::Config& cfg, bool set_defaults) {\n    ZoneScopedN(__FUNCTION__);\n"
        "    m_rendering_method->selection().set_defer_all_transitions(is_quadview_supported_title());")
    c = once(c, "void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {\n    service_mono_transition_game_thread();",
        "void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {\n"
        "    m_rendering_method->selection().set_defer_all_transitions(is_quadview_supported_title());\n"
        "    service_mono_transition_game_thread();")
    # Invalid destinations must not leave the working ID7 renderer closed.
    anchor = """    if (!selection.pending()) { return; }
    if (uevr::mono::is_mono_family(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }
    if (selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO && quadview_unavailable_reason() != nullptr) return;"""
    c = once(c, anchor, """    if (!selection.pending()) { return; }
    const auto rejected_token=selection.request_token();
    const auto requested=static_cast<int32_t>(rejected_token);
    const char* rejected = !m_rendering_method->is_available(requested)
        ? "Unsupported requested rendering method" : nullptr;
    if (!rejected && uevr::mono::is_mono_family(requested)) rejected = mono_unavailable_reason();
    if (!rejected && requested == RenderingMethod::QUAD_VIEWS_STEREO) rejected = quadview_unavailable_reason();
    // Initial ID7 hook warmup is deliberately allowed to keep waiting. A
    // rejected live exit/entry leaves its previous renderer available.
    if (rejected && is_quadview_supported_title() &&
        (selection.active() == RenderingMethod::QUAD_VIEWS_STEREO ||
         requested != RenderingMethod::QUAD_VIEWS_STEREO ||
         (quadview_unavailable_reason() && std::string_view{quadview_unavailable_reason()}.find("warming up") == std::string_view::npos))) {
        if (selection.cancel_request(rejected_token)) {
            SPDLOG_WARNING_EVERY_N_SEC(2, "[QuadViews][Transition] rejected method={} active={} reason={}",
                requested, selection.active(), rejected);
            set_mono_status(rejected);
        }
        return;
    }
    if (rejected) return;""")
    anchor = """        set_quadview_status(quadview_transition_draw_closed()
            ? "Waiting for tracked render-thread/RHI owners to execute at mode commit"""
    c = once(c, anchor, """        if (m_fake_stereo_hook) {
            const auto engine=m_fake_stereo_hook->quadview_delivery.diagnostics_snapshot(mono_generation());
            const auto native=m_fake_stereo_hook->quadview_native_delivery.diagnostics_snapshot(mono_generation());
            SPDLOG_INFO_EVERY_N_SEC(1, "[QuadViews][Transition] active={} requested={} generation={} token={} closed={} engine_pending={} source_incomplete={} overflow={} native_slots={} native_tails={} oldest={} rendered={} hooked={} executed={} written={}",
                selection.active(),selection.requested(),mono_generation(),selection.request_token(),quadview_transition_draw_closed(),
                engine.pending_engine_tickets,engine.incomplete_source_slots,engine.engine_tracking_overflowed,
                native.occupied_slots,native.active_tails,native.oldest_retained_serial,
                unsigned(native.oldest_retained_rendered),unsigned(native.oldest_retained_hooked),
                unsigned(native.oldest_retained_executed),unsigned(native.oldest_retained_written));
        }
        set_quadview_status(quadview_transition_draw_closed()
            ? "Waiting for tracked render-thread/RHI owners to execute at mode commit"""
    )
    text["src/mods/VR.cpp"] = c

    f = text["src/mods/vr/FFakeStereoRenderingHook.cpp"]
    f = once(f, '#include <stdexcept>', '#include <stdexcept>\n#include "QuadViewTransition.hpp"')
    anchor = "    static inline std::unordered_map<sdk::FRHICommandBase_New*,QuadDrainBatch> quad_drain_commands{};"
    f = once(f, anchor, anchor + "\n    static inline std::unordered_map<sdk::FRHICommandBase_New*,uevr::quadview::TransitionCallbackTicket> quad_transition_commands{};")
    anchor = '        if (vr->is_quadview_mode_selected() && !quad_native && !quad_engine && !quad_source) { qv_trace(64,"HOOK_REJECT","quad_without_owner",vr->quadview_status()); return; }'
    f = once(f, anchor, """        const auto transition_scope=uevr::quadview::NativeDrainScope::current();
        const bool qv_transition_callback=uevr::quadview::allow_transition_callback(
            vr->is_quadview_mode_selected() && vr->is_quadview_supported_title() && !vr->has_unsupported_rendering_method(),
            vr->is_mono_transition_pending(),vr->quadview_transition_draw_closed(),
            bool(quad_native)||bool(quad_engine)||bool(quad_source)||bool(duo_source),
            transition_scope.id!=0 && transition_scope.immediate_list!=0);
        if (vr->is_quadview_mode_selected() && !quad_native && !quad_engine && !quad_source && !qv_transition_callback) {
            qv_trace(64,"HOOK_REJECT","quad_without_owner",vr->quadview_status()); return;
        }
        const uevr::quadview::TransitionCallbackTicket transition_ticket=qv_transition_callback
            ? uevr::quadview::TransitionCallbackTicket{vr->mono_generation(),vr->mono_request_token()}
            : uevr::quadview::TransitionCallbackTicket{};
        if (qv_transition_callback && quad_transition_commands.size()>=8) {
            qv_trace(34,"HOOK_REJECT","transition_callback_capacity"); return;
        }""")
    # Use the same readable, bounded tail walk as owned engine callbacks.
    f = once(f, "        if (quad_engine || quad_native) {", "        if (quad_engine || quad_native || qv_transition_callback) {")
    anchor = '        *(void***)last_command = (void**)new_vtable.data();\n        qv_trace(6,"HOOK_INSTALLED","vtable_replaced");'
    f = once(f, anchor, """        if (transition_ticket) {
            quad_transition_commands.emplace(last_command,transition_ticket);
            qv_trace(32,"TRANSITION_HOOK","maintenance_only");
        }
""" + anchor)
    anchor = '        const auto quad_drain=quad_drain_it!=quad_drain_commands.end() ? quad_drain_it->second : QuadDrainBatch{};'
    f = once(f, anchor, anchor + """
        const auto transition_it=quad_transition_commands.find(cmd);
        const auto transition_ticket=transition_it!=quad_transition_commands.end()
            ? transition_it->second : uevr::quadview::TransitionCallbackTicket{};
        // A maintenance callback never assigns poses, begins/synchronizes XR,
        // or publishes a source, even after its request is canceled or superseded.
        const auto qv_runtime_allowed=[&]() { return !transition_ticket; };""")
    f = once(f, "        quad_drain_commands.erase(cmd);", "        quad_drain_commands.erase(cmd);\n        quad_transition_commands.erase(cmd);")
    anchor = "if ((quad_native ? quad_native_runtime_claimed : quad_drain.allows_runtime(vr->mono_generation(),quad_engine)) &&"
    if f.count(anchor) != 2: raise RuntimeError("Expected both runtime cadence gates")
    f = f.replace(anchor, "if (qv_runtime_allowed() && (quad_native ? quad_native_runtime_claimed : quad_drain.allows_runtime(vr->mono_generation(),quad_engine)) &&")
    # Suppress the generic pose fallback in hook installation as well as at
    # execution. Existing owned callbacks keep their exact original behavior.
    start=f.index("    static void hook_new_rhi_command(")
    end=f.index("    static void hook_old_rhi_command(",start)
    hook=f[start:end]
    hook=hook.replace("if (!quad_native) runtime->on_pre_render_render_thread(frame_count);",
        "if (!quad_native && !qv_transition_callback) runtime->on_pre_render_render_thread(frame_count);")
    hook=hook.replace("if (!quad_native) runtime->enqueue_render_poses(frame_count);",
        "if (!quad_native && !qv_transition_callback) runtime->enqueue_render_poses(frame_count);")
    f=f[:start]+hook+f[end:]
    anchor='        qv_emit_rhi(16,"WORKER_ENTER","rhi_worker");'
    f=once(f,anchor,"""        if (transition_ticket) qv_emit_rhi(33,"TRANSITION_RHI","maintenance_only",0,
            transition_ticket.current(vr->mono_generation(),vr->mono_request_token(),
                vr->is_quadview_mode_selected(),vr->is_mono_transition_pending(),vr->quadview_transition_draw_closed())?1:0);
"""+anchor)
    f=once(f, "if (g_hook != nullptr) { g_hook->note_nascar25_render_pose_handoff(frame_count); }",
        "if (qv_runtime_allowed() && g_hook != nullptr) { g_hook->note_nascar25_render_pose_handoff(frame_count); }")
    f=once(f, "if (g_hook != nullptr) { g_hook->note_stalker2_rhi_handoff(frame_count); }",
        "if (qv_runtime_allowed() && g_hook != nullptr) { g_hook->note_stalker2_rhi_handoff(frame_count); }")
    text["src/mods/vr/FFakeStereoRenderingHook.cpp"] = f
    for name, path in paths.items(): path.write_text(text[name], encoding="utf-8", newline="")
    shutil.copyfile(Path(__file__).with_name("QuadViewTransition.hpp"),base / "QuadViewTransition.hpp")
    print("Applied guarded transition maintenance; preserved CPU ownership and GPU retirement gates.")


if __name__ == "__main__": main()
