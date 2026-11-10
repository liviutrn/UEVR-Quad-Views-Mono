#!/usr/bin/env python3
"""B42 over B41.1: VRAM safety.

Headset (9-10 Nov 2026): BSOD 0x139 when the game's VRAM reaches its DXGI
budget. Growth comes from Unreal's per-view-size scene buffers that each new
TriView source size allocates while the old set is still alive.

1. VRAM guard: a settled resize builds a new set only if "used + estimate"
   stays under a menu limit (default 85 % of the DXGI budget). A refused build
   keeps the live set (no black, no crash) and is shown in the menu.
2. Fewer distinct sizes: focus width/height, periphery scale and density snap
   to 0.05 steps.
3. One rebuild at a time plus a 1.5 s pause after each published set
   (ResizeGate cooldown, QuadViewGeometry.hpp).
4. Low-resolution start: with TriView saved, the headset starts at a low
   OpenXR scale (menu, default 0.3) and switches once to the saved scale when
   TriView runs with a published set for 3 s AND the guard allows it. The
   saved OpenXR_ResolutionScale is never written.
5. Logs: VRAM every 2 s (+ periphery depth pool), VRAM on every set build and
   publication, every allowed/refused build.

Pure logic: TriViewVramGuard.hpp (TriViewVramGuardTests.cpp). Run after
apply_triview_b41.py and before apply_liviu_defaults.py.
"""
from pathlib import Path
import shutil
import sys


def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"B42 anchor '{label}' found {n} times: {old[:100]!r}")
    return s.replace(old, new, 1)


def edit(path, fn):
    s = path.read_text(encoding='utf-8')
    s = fn(s)
    path.write_text(s, encoding='utf-8', newline='\n')


def main():
    backend = Path(sys.argv[1])
    here = Path(__file__).resolve().parent
    mods = backend / 'src/mods'
    shutil.copyfile(here / 'TriViewVramGuard.hpp', mods / 'vr/TriViewVramGuard.hpp')

    # --- OpenXR: low-resolution start scale (never saved) -------------------
    def openxr_hpp(s):
        return once(s, '    uint32_t get_width_for_scale(float scale) const;\n',
            '    uint32_t get_width_for_scale(float scale) const;\n'
            '    // B42: TriView low-resolution start. > 0 = this scale is used instead of the\n'
            '    // saved OpenXR_ResolutionScale (which is never changed). Ends once.\n'
            '    static inline std::atomic<float> triview_warmup_scale{0.f};\n'
            '    bool finish_triview_warmup(const char* reason);\n', 'OpenXR decl')
    edit(mods / 'vr/runtimes/OpenXR.hpp', openxr_hpp)

    def openxr_cpp(s):
        for fn in ('width', 'height'):
            s = once(s, f'uint32_t OpenXR::get_{fn}() const {{\n    if (this->view_configs.empty()) {{\n        return 0;\n    }}\n',
                f'uint32_t OpenXR::get_{fn}() const {{\n    if (this->view_configs.empty()) {{\n        return 0;\n    }}\n'
                f'    if (const float warm = triview_warmup_scale.load(std::memory_order_relaxed); warm > 0.f) {{\n'
                f'        return this->get_{fn}_for_scale(warm); // B42 low-resolution start\n'
                f'    }}\n', f'get_{fn}')
        s = once(s, '            this->last_applied_resolution_scale = this->resolution_scale->value();\n'
                    '            this->last_applied_resolution_width = this->get_width();\n',
            '            {   // B42: during the low-resolution start the live scale is the warm-up scale\n'
            '                const float warm = triview_warmup_scale.load(std::memory_order_relaxed);\n'
            '                this->last_applied_resolution_scale = warm > 0.f ? warm : this->resolution_scale->value();\n'
            '            }\n'
            '            this->last_applied_resolution_width = this->get_width();\n', 'UI init')
        s = once(s, '            this->resolution_scale_reconfigure_pending = false;\n\n            if (auto vr = VR::get(); vr != nullptr) {\n',
            '            this->resolution_scale_reconfigure_pending = false;\n'
            '            if (triview_warmup_scale.exchange(0.f) > 0.f) {\n'
            '                spdlog::info("[TriView][LowStart] resolution slider moved by the user: low-resolution start ended");\n'
            '            }\n\n'
            '            if (auto vr = VR::get(); vr != nullptr) {\n', 'UI apply')
        s = once(s, 'uint32_t OpenXR::get_width() const {\n',
            '''// B42: one-shot switch from the low-resolution start to the saved scale, same
// path as the menu slider (VR::on_openxr_resolution_scale_changed).
bool OpenXR::finish_triview_warmup(const char* reason) {
    if (this->view_configs.empty()) return false; // keep the warm-up until sizes are known
    const float warm = triview_warmup_scale.exchange(0.f);
    if (warm <= 0.f) return false;
    const float full = this->resolution_scale->value();
    const auto old_w = this->get_width_for_scale(warm), old_h = this->get_height_for_scale(warm);
    const auto new_w = this->get_width_for_scale(full), new_h = this->get_height_for_scale(full);
    spdlog::info("[TriView][LowStart] {}: resolution scale {:.2f} -> {:.2f} [{}x{}] -> [{}x{}]",
        reason ? reason : "", warm, full, old_w, old_h, new_w, new_h);
    if (old_w == new_w && old_h == new_h) return true;
    auto vr = VR::get();
    const bool live = vr != nullptr && vr->on_openxr_resolution_scale_changed(old_w, old_h, new_w, new_h);
    if (live) {
        this->resolution_scale_live_apply_deferred = false;
        this->last_applied_resolution_scale = full;
        this->last_applied_resolution_width = new_w;
        this->last_applied_resolution_height = new_h;
    } else {
        this->resolution_scale_live_apply_deferred = true;
        this->last_applied_resolution_scale = warm;
        this->last_applied_resolution_width = old_w;
        this->last_applied_resolution_height = old_h;
        spdlog::warn("[TriView][LowStart] live resolution change not allowed; staying at {:.2f} until the next start", warm);
    }
    return live;
}

uint32_t OpenXR::get_width() const {
''', 'finish fn')
        return s
    edit(mods / 'vr/runtimes/OpenXR.cpp', openxr_cpp)

    # --- VR.hpp: options, state ---------------------------------------------
    def vr_hpp(s):
        s = once(s, '    const ModCombo::Ptr m_quadview_b40_stability{',
            '    const ModSlider::Ptr m_triview_b42_vram_limit{ModSlider::create(generate_name("QuadViewB42VramLimitPercent"), 60.f, 95.f, 85.f)};\n'
            '    const ModToggle::Ptr m_triview_b42_low_start{ModToggle::create(generate_name("QuadViewB42LowResStart"), true)};\n'
            '    const ModSlider::Ptr m_triview_b42_low_start_scale{ModSlider::create(generate_name("QuadViewB42LowResStartScale"), .1f, 1.f, .3f)};\n'
            '    std::array<uint32_t,2> m_triview_b42_guard_eye{};\n'
            '    std::optional<uevr::quadview::SourceExtents> m_triview_b42_inflight{}; // allowed build not yet published\n'
            '    uint64_t m_triview_b42_inflight_ms{}; // when it was allowed (expires with the gate latch)\n'
            '    const ModCombo::Ptr m_quadview_b40_stability{', 'B42 members')
        s = once(s, '*m_quadview_b41_hold_ms, *m_quadview_b41_reach_scale,',
            '*m_quadview_b41_hold_ms, *m_quadview_b41_reach_scale,\n'
            '            *m_triview_b42_vram_limit, *m_triview_b42_low_start, *m_triview_b42_low_start_scale,', 'saved options')
        s = once(s, '    std::atomic<uint64_t> m_triview_vram_used{0}, m_triview_vram_budget{0}, m_triview_vram_system{0};\n',
            '    std::atomic<uint64_t> m_triview_vram_used{0}, m_triview_vram_budget{0}, m_triview_vram_system{0};\n'
            '    // B42 VRAM guard / low-resolution start state (MB values for the menu and logs).\n'
            '    std::atomic<uint64_t> m_triview_b42_refusals{0};\n'
            '    std::atomic<uint32_t> m_triview_b42_last_used_mb{0}, m_triview_b42_last_need_mb{0}, m_triview_b42_last_limit_mb{0};\n'
            '    std::atomic<int> m_triview_b42_low_start_state{0}; // 0 unused, 1 waiting, 2 refused by guard, 3 switched\n'
            '    void service_triview_low_start(); // present thread, every frame\n', 'B42 public state')
        return s
    edit(mods / 'VR.hpp', vr_hpp)

    # --- VR.cpp ---------------------------------------------------------------
    def vr_cpp(s):
        s = once(s, '#include "vr/TriViewHold.hpp"\n', '#include "vr/TriViewHold.hpp"\n#include "vr/TriViewVramGuard.hpp"\n', 'include')
        # 2. snap sizes
        s = once(s, '''            requested.crop_width=m_quadview_crop_width->value();
            requested.crop_height=m_quadview_crop_height->value();
            requested.context_scale=m_quadview_context_scale->value();
            requested.foveal_density=m_quadview_foveal_density->value();
''', '''            // B42: snap to 0.05 steps -> few distinct view sizes for Unreal to allocate.
            requested.crop_width=uevr::quadview::vram::snap_fraction(m_quadview_crop_width->value(),.05f,1.f);
            requested.crop_height=uevr::quadview::vram::snap_fraction(m_quadview_crop_height->value(),.05f,1.f);
            requested.context_scale=uevr::quadview::vram::snap_fraction(m_quadview_context_scale->value(),.05f,.50f);
            requested.foveal_density=uevr::quadview::vram::snap_fraction(m_quadview_foveal_density->value(),.25f,4.f);
''', 'snap settings')
        s = once(s, '''                    m_triview_resize_gate.reset();
                    SPDLOG_INFO("[TriView][Resize] published world identity changed; discard prior-size cache");''',
            '''                    m_triview_resize_gate.reset();
                    m_triview_b42_inflight.reset(); // B42
                    SPDLOG_INFO("[TriView][Resize] published world identity changed; discard prior-size cache");''', 'world reset')
        # 3. cooldown + 1. guard
        s = once(s, '''                    const auto decision=m_triview_resize_gate.update(''',
            '''                    m_triview_resize_gate.set_cooldown_ms(1500); // B42: pause after each new set
                    const auto decision=m_triview_resize_gate.update(''', 'gate cooldown')
        s = once(s, '''                    if (decision.request) {
                        m_triview_pending_extents=decision.request_extents;
                        m_triview_pending_extents_valid=true;
                    }''', '''                    if (decision.request) {
                        // B42 VRAM guard: build the new set only if VRAM stays below the limit.
                        namespace vram=uevr::quadview::vram;
                        const auto used=m_triview_vram_used.load(std::memory_order_relaxed);
                        const auto budget=m_triview_vram_budget.load(std::memory_order_relaxed);
                        const float limit_percent=m_triview_b42_vram_limit->value();
                        const auto estimate=vram::build_estimate(decision.request_extents);
                        const auto live_px=m_triview_hold_set ? vram::source_pixels(m_triview_hold_set->extents) : 0;
                        // A smaller set may still be built up to 95 % (it lowers what stays alive).
                        const bool shrinks=live_px!=0 && vram::source_pixels(decision.request_extents)<live_px;
                        const std::array<uint32_t,2> eye{static_cast<uint32_t>(width),static_cast<uint32_t>(height)};
                        if (m_triview_b42_guard_eye[0]==0) m_triview_b42_guard_eye=eye;
                        // Headset resolution changed (low-res start switch, checked there; or the
                        // user's menu slider): the set must follow the new eye size, so no refusal.
                        const bool eye_changed=m_triview_b42_guard_eye!=eye;
                        // The gate re-requests an in-flight build every 2 s: already allowed, its own
                        // allocations raise "used", so it must not be judged (and cancelled) again.
                        if (m_triview_b42_inflight && m_triview_hold_set && m_triview_hold_set->extents==*m_triview_b42_inflight)
                            m_triview_b42_inflight.reset();
                        if (m_triview_b42_inflight && now-m_triview_b42_inflight_ms>uevr::quadview::ResizeGate::latch_timeout_ms)
                            m_triview_b42_inflight.reset();
                        const bool retry=m_triview_b42_inflight && *m_triview_b42_inflight==decision.request_extents;
                        const bool allowed=retry || eye_changed || vram::allows(used,budget,estimate,limit_percent) ||
                            (shrinks && (budget==0 || used<=vram::limit_bytes(budget,95.f)));
                        const auto mb=[](uint64_t b) { return static_cast<uint32_t>(b>>20); };
                        if (allowed && retry) {
                            m_triview_pending_extents=decision.request_extents;
                            m_triview_pending_extents_valid=true;
                        } else if (allowed) {
                            m_triview_b42_guard_eye=eye;
                            m_triview_b42_inflight=decision.request_extents;
                            m_triview_b42_inflight_ms=now;
                            m_triview_pending_extents=decision.request_extents;
                            m_triview_pending_extents_valid=true;
                            SPDLOG_INFO("[TriView][VRAM] build allowed {}x{} / {}x{}: used {} MB + estimate {} MB, limit {} MB ({:.0f}% of {} MB budget){}",
                                decision.request_extents[0][0],decision.request_extents[0][1],
                                decision.request_extents[2][0],decision.request_extents[2][1],
                                mb(used),mb(estimate),mb(vram::limit_bytes(budget,limit_percent)),limit_percent,mb(budget),
                                eye_changed ? " (headset resolution changed: guard skipped)" : shrinks && !vram::allows(used,budget,estimate,limit_percent) ? " (smaller set, allowed up to 95%)" : "");
                        } else {
                            m_triview_resize_gate.cancel_latch();
                            m_triview_b42_refusals.fetch_add(1,std::memory_order_relaxed);
                            m_triview_b42_last_used_mb.store(mb(used),std::memory_order_relaxed);
                            m_triview_b42_last_need_mb.store(mb(estimate),std::memory_order_relaxed);
                            m_triview_b42_last_limit_mb.store(mb(vram::limit_bytes(budget,limit_percent)),std::memory_order_relaxed);
                            SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][VRAM] resize REFUSED {}x{} / {}x{}: used {} MB + estimate {} MB > limit {} MB ({:.0f}% of {} MB budget); keeping the live set (refusals {})",
                                decision.request_extents[0][0],decision.request_extents[0][1],
                                decision.request_extents[2][0],decision.request_extents[2][1],
                                mb(used),mb(estimate),mb(vram::limit_bytes(budget,limit_percent)),limit_percent,mb(budget),
                                m_triview_b42_refusals.load(std::memory_order_relaxed));
                        }
                    }''', 'guard')
        # menu
        s = once(s, '                ImGui::TextWrapped("If a frame is missing, keep showing the last image (it still follows your head) for up to this long instead of black. 250 = B41 default, 100 = B40.");\n',
            '''                ImGui::TextWrapped("If a frame is missing, keep showing the last image (it still follows your head) for up to this long instead of black. 250 = B41 default, 100 = B40.");
                m_triview_b42_vram_limit->draw("VRAM limit for resizes (% of budget)");
                ImGui::TextWrapped("A new focus/periphery size is only built while the game's video memory stays below this share of its budget. Higher = more freedom, closer to the crash point. Sizes snap to 0.05 steps.");
                if (const auto refusals=m_triview_b42_refusals.load(std::memory_order_relaxed); refusals!=0)
                    ImGui::TextWrapped("Resize refused %llu times (last: %u MB used + %u MB needed > %u MB limit). Lower the focus size or the resolution.",
                        static_cast<unsigned long long>(refusals),m_triview_b42_last_used_mb.load(),m_triview_b42_last_need_mb.load(),m_triview_b42_last_limit_mb.load());
                m_triview_b42_low_start->draw("Start TriView at low resolution");
                m_triview_b42_low_start_scale->draw("Start resolution scale");
                ImGui::TextWrapped("Takes effect at the next game start. Switches once to your normal resolution when TriView runs and the VRAM limit allows it. Your saved resolution is never changed.");
                {
                    const float warm=runtimes::OpenXR::triview_warmup_scale.load(std::memory_order_relaxed);
                    const int state=m_triview_b42_low_start_state.load(std::memory_order_relaxed);
                    if (warm>0.f && state==2)
                        ImGui::TextWrapped("Low-resolution start: staying at %.2f (switch needs %u MB, used %u MB, limit %u MB)",
                            warm,m_triview_b42_last_need_mb.load(),m_triview_b42_last_used_mb.load(),m_triview_b42_last_limit_mb.load());
                    else if (warm>0.f) ImGui::TextWrapped("Low-resolution start: running at %.2f, waiting for TriView", warm);
                    else if (state==4) ImGui::TextWrapped("Low-resolution start: UEVR could not switch the resolution live; staying low until restart. Low start is now OFF.");
                    else if (state==3) ImGui::TextUnformatted("Low-resolution start: done, normal resolution in use");
                }
''', 'menu')
        # 4. start low: set before OpenXR swapchains are created
        s = once(s, '    if (get_runtime() != nullptr && get_runtime()->loaded) {\n        get_runtime()->on_config_load(cfg, set_defaults);\n',
            '''    // B42.1: a saved ID7 loads as a REQUEST (active stays Native Stereo until the
    // autostart commits), so value() is not 7 here - check the request too.
    if (m_first_config_load && m_triview_b42_low_start->value() &&
        (m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO ||
         m_rendering_method->requested_value() == RenderingMethod::QUAD_VIEWS_STEREO)) {
        // B42: TriView saved -> start the headset at a low resolution (before swapchains exist).
        const float warm = std::clamp(m_triview_b42_low_start_scale->value(), .1f, 1.f);
        if (warm < .999f && runtimes::OpenXR::triview_warmup_scale.exchange(warm) != warm) {
            m_triview_b42_low_start_state.store(1, std::memory_order_relaxed);
            spdlog::info("[TriView][LowStart] TriView saved: starting at resolution scale {:.2f} until TriView is loaded", warm);
        }
    }
    if (get_runtime() != nullptr && get_runtime()->loaded) {
        get_runtime()->on_config_load(cfg, set_defaults);
''', 'config load')
        s = once(s, 'uint32_t VR::get_hmd_width() const {\n', '''// B42: end the low-resolution start once TriView is loaded and VRAM allows it.
void VR::service_triview_low_start() {
    using clock = std::chrono::steady_clock;
    const float warm = runtimes::OpenXR::triview_warmup_scale.load(std::memory_order_acquire);
    if (warm <= 0.f || m_openxr == nullptr || get_runtime() == nullptr || !get_runtime()->loaded || !get_runtime()->is_openxr()) return;
    static clock::time_point first{}, set_since{};
    const auto now = clock::now();
    if (first == clock::time_point{}) first = now;
    const int stage = m_triview_autostart_stage;
    const bool transitioning = stage == 1 || stage == 2 || is_mono_transition_pending() ||
        m_triview_restart_phase.load(std::memory_order_acquire) != 0; // B42.2: runtime restart in progress
    const bool triview = is_quadview_mode_selected();
    if (transitioning) { set_since = {}; return; }
    if (!triview) {
        if (stage == 3 || now - first > std::chrono::seconds(90)) {
            if (m_openxr->finish_triview_warmup("TriView is not running"))
                m_triview_b42_low_start_state.store(3, std::memory_order_relaxed);
        }
        return;
    }
    const auto rtm = m_fake_stereo_hook ? m_fake_stereo_hook->get_render_target_manager() : nullptr;
    const auto set = rtm ? rtm->get_quadview_native_target_set() : nullptr;
    if (!set || !set->complete()) { set_since = {}; return; }
    if (set_since == clock::time_point{}) set_since = now;
    if (now - set_since < std::chrono::seconds(3)) return;
    namespace vram = uevr::quadview::vram;
    const float full = m_openxr->resolution_scale->value();
    const auto old_w = m_openxr->get_width_for_scale(warm), old_h = m_openxr->get_height_for_scale(warm);
    const auto new_w = m_openxr->get_width_for_scale(full), new_h = m_openxr->get_height_for_scale(full);
    const auto estimate = vram::resolution_switch_estimate(old_w, old_h, new_w, new_h,
        vram::snap_fraction(m_quadview_crop_width->value(), .05f, 1.f), vram::snap_fraction(m_quadview_crop_height->value(), .05f, 1.f),
        vram::snap_fraction(m_quadview_context_scale->value(), .05f, .50f), vram::snap_fraction(m_quadview_foveal_density->value(), .25f, 4.f));
    const auto used = m_triview_vram_used.load(std::memory_order_relaxed);
    const auto budget = m_triview_vram_budget.load(std::memory_order_relaxed);
    const float limit_percent = m_triview_b42_vram_limit->value();
    const auto mb = [](uint64_t b) { return static_cast<uint32_t>(b >> 20); };
    if (budget == 0) return; // wait for the first DXGI reading
    if (!vram::allows(used, budget, estimate, limit_percent)) {
        m_triview_b42_low_start_state.store(2, std::memory_order_relaxed);
        m_triview_b42_last_used_mb.store(mb(used), std::memory_order_relaxed);
        m_triview_b42_last_need_mb.store(mb(estimate), std::memory_order_relaxed);
        m_triview_b42_last_limit_mb.store(mb(vram::limit_bytes(budget, limit_percent)), std::memory_order_relaxed);
        SPDLOG_WARNING_EVERY_N_SEC(10, "[TriView][LowStart] staying at {:.2f}: switch to {:.2f} needs ~{} MB, used {} MB, limit {} MB ({:.0f}% of {} MB)",
            warm, full, mb(estimate), mb(used), mb(vram::limit_bytes(budget, limit_percent)), limit_percent, mb(budget));
        return;
    }
    spdlog::info("[TriView][VRAM] before resolution switch: used {} MB / budget {} MB, estimate {} MB", mb(used), mb(budget), mb(estimate));
    if (m_openxr->finish_triview_warmup("TriView loaded and VRAM allows it")) {
        m_triview_b42_low_start_state.store(3, std::memory_order_relaxed);
    } else if (runtimes::OpenXR::triview_warmup_scale.load(std::memory_order_relaxed) <= 0.f) {
        // Live switch not allowed by UEVR for this engine: stay low now, and do not
        // start low again next time (the user would otherwise be stuck low).
        m_triview_b42_low_start->value() = false;
        m_triview_b42_low_start_state.store(4, std::memory_order_relaxed);
        spdlog::warn("[TriView][LowStart] live switch refused by UEVR; low-resolution start turned OFF for next starts");
    }
}

uint32_t VR::get_hmd_width() const {
''', 'service fn')
        # B42.2: a runtime restart (UEVR "Reinitialize Runtime", e.g. after a SteamVR
        # resolution change) also comes back at the low start scale; the checked
        # switch-up then runs once TriView is loaded again.
        s = once(s, '''            const uint64_t old_serial=m_fake_stereo_hook ?
                m_fake_stereo_hook->native_stereo_publication_serial() : 0;
            if (const auto error=reinitialize_openxr()) {''', '''            const uint64_t old_serial=m_fake_stereo_hook ?
                m_fake_stereo_hook->native_stereo_publication_serial() : 0;
            // B42.2: arm the low start inside reinitialize_openxr, only after the old
            // session is really destroyed (it may refuse and keep running at its size).
            m_triview_b42_arm_on_reinit=m_triview_b42_low_start->value();
            if (const auto error=reinitialize_openxr()) {''', 'restart re-arm')
        # build identity
        s = once(s, 'spdlog::info("[TriView][Build] B41.1 (B40 + device-race fix + hold window, rejection diagnostics, queue pin 4-6, blend distance)");',
            'spdlog::info("[TriView][Build] B42.3 (B42.2 + safe recovery drain when the headset is taken off)");',
            'build log')
        return s
    edit(mods / 'VR.cpp', vr_cpp)

    # B42.2: arm the low start between old-session teardown and new-session creation.
    def vr_hpp_reinit(s):
        s = once(s, '        m_openxr.reset();\n        m_runtime.reset();\n        m_runtime = std::make_shared<VRRuntime>();',
            '        m_openxr.reset();\n        m_runtime.reset();\n        m_runtime = std::make_shared<VRRuntime>();\n'
            '        if (m_triview_b42_arm_on_reinit) { // B42.2: old session is gone\n'
            '            m_triview_b42_arm_on_reinit = false;\n'
            '            float warm = m_triview_b42_low_start_scale->value();\n'
            '            warm = warm < .1f ? .1f : (warm > 1.f ? 1.f : warm);\n'
            '            if (warm < .999f) {\n'
            '                runtimes::OpenXR::triview_warmup_scale.store(warm);\n'
            '                m_triview_b42_low_start_state.store(1, std::memory_order_relaxed);\n'
            '                spdlog::info("[TriView][LowStart] runtime restart: new XR session starts at resolution scale {:.2f} until TriView is loaded", warm);\n'
            '            }\n'
            '        }', 'reinit arm')
        s = once(s, "    void service_triview_low_start(); // present thread, every frame\n",
            "    void service_triview_low_start(); // present thread, every frame\n"
            "    bool m_triview_b42_arm_on_reinit{}; // B42.2: set by the TriView restart, consumed in reinitialize_openxr\n", 'arm flag')
        return s
    edit(mods / 'VR.hpp', vr_hpp_reinit)

    # --- depth pool usage -----------------------------------------------------
    def depth(s):
        return once(s, '    static PeripheryDepth& self() {',
            '''    // B42: slots and texture payload of the depth snapshot pool (for the VRAM log).
    std::pair<uint32_t, uint64_t> pool_usage() {
        std::scoped_lock lock(mutex_);
        uint64_t bytes = 0;
        for (const auto& slot : pool_) {
            if (!slot || !slot->texture) continue;
            const auto d = slot->texture->GetDesc();
            bytes += d.Width * d.Height * (d.Format == DXGI_FORMAT_R32G8X24_TYPELESS ? 8ull : 4ull);
        }
        return {static_cast<uint32_t>(pool_.size()), bytes};
    }
    static PeripheryDepth& self() {''', 'depth pool usage')
    edit(mods / 'vr/QuadViewNgxDepth.hpp', depth)

    # --- D3D12Component: VRAM log every 2 s, low-start service ----------------
    def d3d(s):
        s = once(s, '''    SPDLOG_INFO_EVERY_N_SEC(10, "[QuadViews][VRAM] game process: {} MB used / {} MB budget; in system memory {} MB",
        local.CurrentUsage >> 20, local.Budget >> 20, system.CurrentUsage >> 20);''',
            '''    {   // B42: every 2 s, with the periphery depth snapshot pool.
        const auto depth_usage = uevr::quadview::ngx::PeripheryDepth::self().pool_usage();
        SPDLOG_INFO_EVERY_N_SEC(2, "[QuadViews][VRAM] game process: {} MB used / {} MB budget ({:.0f}%); in system memory {} MB; depth pool {} slots {} MB",
            local.CurrentUsage >> 20, local.Budget >> 20, local.Budget ? 100.0 * double(local.CurrentUsage) / double(local.Budget) : 0.0,
            system.CurrentUsage >> 20, depth_usage.first, depth_usage.second >> 20);
    }''', 'vram log')
        s = once(s, 'vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n    sample_triview_vram(vr);\n',
            'vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n    sample_triview_vram(vr);\n'
            '    if (vr != nullptr) vr->service_triview_low_start(); // B42\n', 'on_frame')
        return s
    edit(mods / 'vr/D3D12Component.cpp', d3d)

    # --- VRAM on every set build / publication ---------------------------------
    def hook(s):
        # B42.3: the recovery drain (incomplete producer snapshot, e.g. headset taken
        # off -> XR session loses focus) used to hand Unreal the raw 4-view family,
        # including the never-rendered placeholder role -> crash ~50 ms later (log
        # 10 Nov 12:22). Drain with view 0 only (a plain singleton render, same
        # count mutation + restore as dispatch_main_views); never published.
        s = once(s, '''                    SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][Recovery] drain-only generation={} serial={} views={}",
                        key.generation,key.draw_serial,identities[drain_route.index].view_count);
                    call_original(); return;''', '''                    SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][Recovery] drain-only generation={} serial={} views={} (B42.3: rendering view 0 only)",
                        key.generation,key.draw_serial,identities[drain_route.index].view_count);
                    auto* drain_family=view_families[drain_route.index];
                    auto drain_views=drain_family ? drain_family->get_views() : nullptr;
                    if (drain_views!=nullptr && drain_views->data!=nullptr && drain_views->count>1 &&
                        drain_views->count<=16 && drain_views->data[0]!=nullptr) {
                        const int32_t drain_saved_count=drain_views->count;
                        drain_views->count=1;
                        utility::ScopeGuard restore_drain_count{[&]() { drain_views->count=drain_saved_count; }};
                        call_original();
                        return;
                    }
                    call_original(); return;''', 'drain view 0 only')
        s = once(s, '''    SPDLOG_INFO("[TriView][Resources] build={} reuse_mask={} new_color_mib={:.1f} (payload estimate)",
        build->generation,unsigned(build->reuse_plan.reuse_mask),double(build->reuse_plan.new_color_bytes)/(1024.0*1024.0));''',
            '''    {   // B42: VRAM (last 1 s DXGI sample) at every set build.
        const auto vr_vram=VR::get();
        SPDLOG_INFO("[TriView][Resources] build={} reuse_mask={} new_color_mib={:.1f} (payload estimate) vram_used={} MB budget={} MB",
            build->generation,unsigned(build->reuse_plan.reuse_mask),double(build->reuse_plan.new_color_bytes)/(1024.0*1024.0),
            vr_vram ? vr_vram->m_triview_vram_used.load(std::memory_order_relaxed)>>20 : 0,
            vr_vram ? vr_vram->m_triview_vram_budget.load(std::memory_order_relaxed)>>20 : 0);
    }''', 'build log')
        s = once(s, '''        SPDLOG_INFO("[TriView][NativeFix] Published THREE independent UE5.5 source targets {}x{} (unused: {}x{}) {}x{} {}x{} generation={}",
            build->extents[0][0],build->extents[0][1],build->extents[1][0],build->extents[1][1],
            build->extents[2][0],build->extents[2][1],build->extents[3][0],build->extents[3][1],build->generation);''',
            '''        {
            const auto vr_vram=VR::get();
            SPDLOG_INFO("[TriView][NativeFix] Published THREE independent UE5.5 source targets {}x{} (unused: {}x{}) {}x{} {}x{} generation={} vram_used={} MB budget={} MB",
                build->extents[0][0],build->extents[0][1],build->extents[1][0],build->extents[1][1],
                build->extents[2][0],build->extents[2][1],build->extents[3][0],build->extents[3][1],build->generation,
                vr_vram ? vr_vram->m_triview_vram_used.load(std::memory_order_relaxed)>>20 : 0,
                vr_vram ? vr_vram->m_triview_vram_budget.load(std::memory_order_relaxed)>>20 : 0);
        }''', 'publish log')
        return s
    edit(mods / 'vr/FFakeStereoRenderingHook.cpp', hook)
    print('Applied B42: VRAM guard, size snapping, rebuild pause, low-resolution start, VRAM logs')


if __name__ == '__main__':
    main()
