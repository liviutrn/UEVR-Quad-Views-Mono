#!/usr/bin/env python3
"""Tri-view B14: settled, race-free resize of the TriView source targets.

Two defects in the B12 make-before-break resize (source-read, B13 tree):
1. Every 64 px step of a size slider started a new four-target build. Each build
   allocates four Kismet render targets; retired ones are freed only by Unreal's
   garbage collector (~once a minute), and every new view size also makes Unreal
   and DLSS allocate buffers for it. A slider drag therefore stacked VRAM.
   Fix: uevr::quadview::ResizeGate (QuadViewGeometry.hpp) - keep drawing with the
   published set's sizes while the wish changes, request ONE build after the wish
   is stable for 400 ms, keep at most one build in flight, and learn the sizes of
   each set it requested.
2. The draw read the published set three times (size hold, compact selection,
   after ensure()). The new set is published from another thread, so a publish
   between those reads left the frozen layout without a matching set and that one
   draw fell back to the legacy family path (the path the B11 resize crash was
   attributed to). Fix: one snapshot per draw (m_triview_hold_set) for all reads;
   if the published set changed under the draw, the draw keeps the held set
   (still owned and live; it retires through the normal fenced owner path).
3. Saved-ID7 autostart always waited the full 25 s timeout (B13 headset log,
   6 Nov 09:39:12 -> 09:39:37): it waited for Native Stereo Fix state Active, but
   on STALKER 2 Joey's exact pair path never reports consumption, so the fix
   stays in PairReady ("right eye rendered") while it works. B14 accepts PairReady
   or Active, held for 2 s. Expected start about 10 s instead of about 28 s.
Run after apply_triview_resize_safety.py and apply_triview_autostart.py.
"""
from pathlib import Path
import sys

VR_CPP = Path("src/mods/VR.cpp")
VR_HPP = Path("src/mods/VR.hpp")
HOOK_HPP = Path("src/mods/vr/FFakeStereoRenderingHook.hpp")


def once(text, old, new, what):
    if text.count(old) != 1:
        raise RuntimeError(f"B14 anchor ({what}) count {text.count(old)}")
    return text.replace(old, new, 1)


OLD_HOLD = r'''            m_triview_pending_extents_valid=false;
            if (m_quadview_compact_targets->value() && m_triview_live_sizes.valid) {
                const auto live_rtm=m_fake_stereo_hook->get_render_target_manager();
                const auto live=live_rtm ? live_rtm->get_quadview_native_target_set() : nullptr;
                auto wanted=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,
                    draw_config.settings.crop_height,draw_config.settings.context_scale,draw_config.settings.foveal_density,focus);
                if (wanted && live && live->complete() && uevr::quadview::apply_native_local(*wanted) &&
                    uevr::quadview::source_extents(*wanted)!=live->extents) {
                    m_triview_pending_extents=uevr::quadview::source_extents(*wanted);
                    m_triview_pending_extents_valid=true;
                    draw_config.settings.crop_width=m_triview_live_sizes.crop_width;
                    draw_config.settings.crop_height=m_triview_live_sizes.crop_height;
                    draw_config.settings.context_scale=m_triview_live_sizes.context_scale;
                    draw_config.settings.foveal_density=m_triview_live_sizes.foveal_density;
                    SPDLOG_INFO_EVERY_N_SEC(1,"[TriView][Resize] new source sizes {}x{} / {}x{} requested; drawing with the live set until it is published",
                        m_triview_pending_extents[0][0],m_triview_pending_extents[0][1],m_triview_pending_extents[2][0],m_triview_pending_extents[2][1]);
                }
            }
'''

NEW_HOLD = r'''            m_triview_pending_extents_valid=false;
            m_triview_hold_set.reset();
            if (m_quadview_compact_targets->value()) {
                // Tri-view B14: ONE read of the published set for this whole draw.
                const auto live_rtm=m_fake_stereo_hook->get_render_target_manager();
                m_triview_hold_set=live_rtm ? live_rtm->get_quadview_native_target_set() : nullptr;
                if (m_triview_hold_set && !m_triview_hold_set->complete()) m_triview_hold_set.reset();
                auto wanted=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,
                    draw_config.settings.crop_height,draw_config.settings.context_scale,draw_config.settings.foveal_density,focus);
                if (wanted && uevr::quadview::apply_native_local(*wanted)) {
                    const uevr::quadview::ResizeSizes wanted_sizes{draw_config.settings.crop_width,draw_config.settings.crop_height,
                        draw_config.settings.context_scale,draw_config.settings.foveal_density};
                    const auto decision=m_triview_resize_gate.update(
                        m_triview_hold_set ? std::optional<uevr::quadview::SourceExtents>{m_triview_hold_set->extents} : std::nullopt,
                        uevr::quadview::source_extents(*wanted),wanted_sizes,now);
                    if (decision.request) {
                        m_triview_pending_extents=decision.request_extents;
                        m_triview_pending_extents_valid=true;
                    }
                    if (decision.hold) {
                        draw_config.settings.crop_width=decision.draw.crop_width;
                        draw_config.settings.crop_height=decision.draw.crop_height;
                        draw_config.settings.context_scale=decision.draw.context_scale;
                        draw_config.settings.foveal_density=decision.draw.foveal_density;
                        SPDLOG_INFO_EVERY_N_SEC(1,"[TriView][Resize] new sizes wanted; drawing with the live set ({}). Build in flight: {}x{} / {}x{}",
                            decision.request ? "one build requested" : "waiting until the sizes stop changing",
                            m_triview_pending_extents[0][0],m_triview_pending_extents[0][1],m_triview_pending_extents[2][0],m_triview_pending_extents[2][1]);
                    }
                }
            }
'''

OLD_SELECT = r'''                    const auto set=compact_rtm->get_quadview_native_target_set();
                    if (set && set->extents==uevr::quadview::source_extents(compact) && set->complete()) {
                        *candidate=compact;
                        m_triview_live_sizes={draw_config.settings.crop_width,draw_config.settings.crop_height,
                            draw_config.settings.context_scale,draw_config.settings.foveal_density,true};
                    }
'''

NEW_SELECT = r'''                    // Tri-view B14: the same snapshot the size hold looked at.
                    const auto set=m_triview_hold_set;
                    if (set && set->extents==uevr::quadview::source_extents(compact) && set->complete()) {
                        *candidate=compact;
                        m_triview_resize_gate.confirm_live(set->extents,{draw_config.settings.crop_width,draw_config.settings.crop_height,
                            draw_config.settings.context_scale,draw_config.settings.foveal_density});
                    }
'''

OLD_KEEP = r'''    else if (rtm && m_triview_pending_extents_valid) {
        // B12: the new set is still building; keep drawing from the old live set.
        const auto live=rtm->get_quadview_native_target_set();
        if (live && live->complete() && live->extents==uevr::quadview::source_extents(*layout) &&
            rtm->quadview_native_targets_live(*live)) native_target_set=live;
    }
'''

NEW_KEEP = r'''    // Tri-view B14: this draw's sizes were chosen against m_triview_hold_set. If a
    // build published (or is still building) in between, keep drawing from that
    // held set: it is still owned here and retires through the fenced owner path.
    // Same world only; with no published set (world change) the old rule applies.
    if (rtm && m_triview_hold_set &&
        (!native_target_set || native_target_set->extents!=uevr::quadview::source_extents(*layout))) {
        const auto published=rtm->get_quadview_native_target_set();
        const auto& hold=m_triview_hold_set;
        if (published && published->world_identity==hold->world_identity && hold->complete() &&
            hold->extents==uevr::quadview::source_extents(*layout) && rtm->quadview_native_targets_live(*hold)) {
            if (published.get()!=hold.get())
                SPDLOG_INFO_EVERY_N_SEC(1,"[TriView][Resize] new set published during this draw; drawing it from the held set");
            native_target_set=hold;
        }
    }
    m_triview_hold_set.reset();
'''


def vr_source(text):
    text = once(text, OLD_HOLD, NEW_HOLD, "size hold")
    text = once(text, OLD_SELECT, NEW_SELECT, "compact select")
    text = once(text, OLD_KEEP, NEW_KEEP, "keep live set")
    if "m_triview_live_sizes" in text:
        raise RuntimeError("B14: a B12 live-size read survived")
    text = once(text,
        "            const bool fix_active = m_fake_stereo_hook && m_fake_stereo_hook->is_native_stereo_fix_state_active();\n",
        "            // B14: on STALKER 2 a working Native Fix stays PairReady (never Active).\n"
        "            const bool fix_active = m_fake_stereo_hook && m_fake_stereo_hook->is_native_stereo_fix_state_ready();\n",
        "autostart readiness")
    text = once(text,
        "            const bool warm = fix_active && now - m_triview_autostart_active_since > std::chrono::seconds(3);\n",
        "            const bool warm = fix_active && now - m_triview_autostart_active_since > std::chrono::seconds(2);\n",
        "autostart hold")
    text = once(text, 'warm ? "Native Fix active for 3 s" : "25 s timeout"',
        'warm ? "Native Fix pair ready for 2 s" : "25 s timeout"', "autostart log")
    return text


def hook_header(text):
    return once(text,
        "    bool is_native_stereo_fix_state_active() const {\n"
        "        return m_native_stereo_fix_state.load(std::memory_order_acquire) == NativeStereoFixState::Active;\n"
        "    }\n",
        "    bool is_native_stereo_fix_state_active() const {\n"
        "        return m_native_stereo_fix_state.load(std::memory_order_acquire) == NativeStereoFixState::Active;\n"
        "    }\n"
        "    // Tri-view B14: Native Fix rendered its right eye (PairReady) or a pair was submitted (Active).\n"
        "    bool is_native_stereo_fix_state_ready() const {\n"
        "        const auto state = m_native_stereo_fix_state.load(std::memory_order_acquire);\n"
        "        return state == NativeStereoFixState::PairReady || state == NativeStereoFixState::Active;\n"
        "    }\n",
        "hook ready helper")


def vr_header(text):
    return once(text,
        "    bool m_triview_pending_extents_valid{false};\n",
        "    bool m_triview_pending_extents_valid{false};\n"
        "    // Tri-view B14 (game thread only): settled resize + one published-set read per draw.\n"
        "    uevr::quadview::ResizeGate m_triview_resize_gate{};\n"
        "    std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> m_triview_hold_set{};\n",
        "vr members")


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: apply_triview_b14.py <backend> [quadview-workspace]")
    root = Path(sys.argv[1])
    files = {root / VR_CPP: vr_source, root / VR_HPP: vr_header, root / HOOK_HPP: hook_header}
    out = {p: f(p.read_text(encoding="utf-8")) for p, f in files.items()}
    for p, t in out.items():
        p.write_text(t, encoding="utf-8")
    print("Tri-view B14: settled single-build resize, one published-set snapshot per draw, faster autostart")


if __name__ == "__main__":
    main()
