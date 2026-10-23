#!/usr/bin/env python3
"""Build52: port the accepted, conditional-write DuoView MPC fix to ID7 only.

Apply after all Build51 overlays. No renderer, texture ownership, geometry,
shaders, gaze or original DuoView sources are changed by this overlay.
"""
from pathlib import Path
import argparse


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Foreground MPC expected one exact anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def apply(backend):
    cpp = backend / "src/mods/VR.cpp"
    header = backend / "src/mods/VR.hpp"
    source = cpp.read_text(encoding="utf-8-sig")
    declaration = header.read_text(encoding="utf-8-sig")
    if "[QuadViews][Foreground] MPC_FOV activated" in source:
        raise RuntimeError("QuadView foreground MPC overlay already applied")
    runtime = Path(__file__).with_name("foreground_mpc_runtime.inc").read_text(encoding="utf-8")
    anchor = "    // Some Supermassive camera paths rewrite crop/aspect state during engine\n"
    source = replace_once(source, anchor, runtime + anchor)
    anchor = '                m_quadview_sharpen->draw("Fused focus sharpening strength");\n'
    source = replace_once(source, anchor, anchor +
        '                m_quadview_foreground_mpc->draw("First-person FOV parity (STALKER 2 MPC)");\n')
    anchor = '    const ModSlider::Ptr m_quadview_crop_width{'
    declaration = replace_once(declaration, anchor,
        '    const ModToggle::Ptr m_quadview_foreground_mpc{ModToggle::create(generate_name("QuadViewForegroundMPC"), true)};\n' + anchor)
    # These existing controls were omitted from m_options in Build51, so
    # saving a profile could not preserve them. Range/layout reconciliation
    # remains the original production gate after loading their requested values.
    controls = (
        "foreground_mpc", "crop_width", "crop_height", "context_scale", "foveal_density",
        "feather", "sharpen", "gpu_timing", "eye_tracking", "debug_border", "debug_mode",
        "stabilize_crop", "guard", "gaze_quant", "gaze_hold", "gaze_reacquire",
        "gaze_offset_u", "gaze_offset_v", "gaze_micro_gain", "gaze_breakout", "gaze_still", "gaze_relock")
    options = "\n".join("            *m_quadview_" + name + "," for name in controls)
    declaration = replace_once(declaration, '        m_options = {', '        m_options = {\n' + options)
    # Resolve all anchors before writing either file; ambiguous input fails closed.
    cpp.write_text(source, encoding="utf-8", newline="")
    header.write_text(declaration, encoding="utf-8", newline="")
    print("Applied ID7-only MPC parity: cached reads, conditional writes, saved rollback toggle.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    apply(parser.parse_args().backend)
