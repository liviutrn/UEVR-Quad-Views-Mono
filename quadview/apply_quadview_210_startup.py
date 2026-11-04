#!/usr/bin/env python3
"""STALKER 2.10 ID7 warm-start repair: publish four owned targets BEFORE mode commit.

Apply once AFTER the complete Build51 ten-overlay chain. The Build52 readback
showed independent source images at local (0,0); QuadViewD3D12.hpp corrects
their compositor addressing separately. This patch fixes the other demonstrated
control-flow gap: Build51 created its target quartet only after selecting ID7,
and retired it unconditionally during the transition into ID7.

No speculative view-state bootstrap or engine frame-counter changes are made.
"""
from pathlib import Path
import sys


def replace_once(value: str, old: str, new: str, what: str) -> str:
    n = value.count(old)
    if n != 1:
        raise RuntimeError(f"{what}: expected exactly one source anchor, found {n}")
    return value.replace(old, new, 1)


def apply(root: Path) -> None:
    vr_path = root / "src/mods/VR.cpp"
    hook_path = root / "src/mods/vr/FFakeStereoRenderingHook.cpp"
    vr = vr_path.read_text(encoding="utf-8")
    hook = hook_path.read_text(encoding="utf-8")

    # Without this, request-time calls to ensure_quadview_native_target_set
    # are rejected until ID7 is already active: the startup loop cannot warm up.
    hook = replace_once(
        hook,
        "!vr || !vr->is_quadview_mode_selected()) return false;",
        "!vr || (!vr->is_quadview_mode_selected() &&\n"
        "        vr->requested_rendering_method() != VR::RenderingMethod::QUAD_VIEWS_STEREO)) return false;",
        "request-time native target creation gate",
    )

    # This function runs on the game thread at a real mode-selection boundary.
    # Do not commit an ID7 that lacks four validated UE-owned D3D12 sources.
    # Reusing ensure_quadview_native_target_set gives the same world/size and
    # engine object lifetime checks as during the ordinary ID7 draw path.
    old_gate = (
        "    if (selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO && "
        "quadview_unavailable_reason() != nullptr) return;"
    )
    new_gate = """    if (selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO) {
        if (quadview_unavailable_reason() != nullptr) return;
        const auto eye_width = get_hmd_width();
        const auto eye_height = get_hmd_height();
        auto* qv_rtm = m_fake_stereo_hook ? m_fake_stereo_hook->get_render_target_manager() : nullptr;
        const bool native_ready = qv_rtm != nullptr && eye_width > 0 && eye_height > 0 &&
            eye_width <= 8192u && eye_height <= 8192u &&
            qv_rtm->ensure_quadview_native_target_set(eye_width * 2u, eye_height);
        const auto sources = native_ready ? qv_rtm->get_quadview_native_target_set() : nullptr;
        const bool quartet_ready = sources && sources->complete() &&
            sources->width == eye_width * 2u && sources->height == eye_height;
        if (!quartet_ready) {
            set_quadview_status("STALKER 2.10: waiting for four owned native sources before ID7 mode commit");
            SPDLOG_WARNING_EVERY_N_SEC(2,
                "[QuadViews][210Startup] deferred ID7 commit: four native sources not yet live; requested={} eye={}x{} published={}",
                static_cast<int>(selection.requested()), eye_width, eye_height,
                bool(sources));
            return;
        }
        SPDLOG_INFO_EVERY_N_SEC(2,
            "[QuadViews][210Startup] committing ID7 with live four-source set generation={} atlas={}x{}",
            sources->generation, sources->width, sources->height);
    }"""
    vr = replace_once(vr, old_gate, new_gate, "ID7 transition prewarm/commit gate")

    # CRITICAL: Build51's unconditional retirement would immediately destroy
    # the quartet we have just created. Retire on ID7 exit, but not on entry.
    old_retire = (
        "        if (auto* manager=m_fake_stereo_hook->get_render_target_manager()) "
        "manager->retire_quadview_native_target_set();"
    )
    new_retire = (
        "        if (!is_quadview_mode_selected()) {\n"
        "            if (auto* manager=m_fake_stereo_hook->get_render_target_manager())\n"
        "                manager->retire_quadview_native_target_set();\n"
        "        }"
    )
    vr = replace_once(vr, old_retire, new_retire, "preserve native targets on ID7 entry")

    assert "quadview_native_targets_live(*current)" in hook, "Build51 lifetime validation missing"
    assert "qv_rtm->quadview_native_targets_live(*qv_target_set)" in hook, "Build51 dispatch liveness missing"
    assert "quadview_native_delivery.reset();" in vr, "Build51 native delivery retirement missing"

    hook_path.write_text(hook, encoding="utf-8", newline="")
    vr_path.write_text(vr, encoding="utf-8", newline="")
    print("Applied STALKER 2.10 owned-source prewarm, guarded ID7 commit, and target retention.")


def verify(root: Path) -> None:
    vr = (root / "src/mods/VR.cpp").read_text(encoding="utf-8")
    hook = (root / "src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    needed = [
        ("prewarm gate", "qv_rtm->ensure_quadview_native_target_set(eye_width * 2u, eye_height)", vr),
        ("prewarm published set", "sources && sources->complete()", vr),
        ("prewarm blocks premature commit", "if (!quartet_ready)", vr),
        ("retain on ID7 entry", "if (!is_quadview_mode_selected()) {", vr),
        ("target retirement on ID7 exit", "manager->retire_quadview_native_target_set();", vr),
        ("request-time allocation", "vr->requested_rendering_method() != VR::RenderingMethod::QUAD_VIEWS_STEREO", hook),
        ("Build51 liveness", "qv_rtm->quadview_native_targets_live(*qv_target_set)", hook),
        ("Build51 frame pairing", "quadview_native_delivery", hook),
    ]
    for name, needle, value in needed:
        if needle not in value:
            raise RuntimeError(f"Missing post-patch contract: {name}")
    if vr.count("[QuadViews][210Startup]") != 2:
        raise RuntimeError("Unexpected prewarm diagnostic count")
    print("Verified STALKER 2.10 startup and Build51 ownership/dispatch source contracts.")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: apply_quadview_210_startup.py BACKEND [--verify]")
    backend = Path(sys.argv[1])
    if len(sys.argv) == 3:
        if sys.argv[2] != "--verify":
            raise SystemExit("Only --verify is supported")
        verify(backend)
    else:
        apply(backend)
