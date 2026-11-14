#!/usr/bin/env python3
"""Static contracts for M5 (six per-eye sharpening sliders)."""
import re
import sys
from pathlib import Path

failures = []


def need(text, snippet, why, count=1):
    n = text.count(snippet)
    if n != count:
        failures.append(f"{why}: expected {count}x, found {n}x: {snippet[:90]!r}")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: test_duoview_m5_generated.py <backend> <shaders>")
    mods = Path(sys.argv[1])/"src/mods"
    sh = Path(sys.argv[2])
    glam = (sh/"DuoViewGlamaryeFovea.hlsl").read_text(encoding="utf-8")
    hlsl = (sh/"DuoViewM1Stereo.hlsl").read_text(encoding="utf-8")
    raster = (sh/"DuoViewNativeCompositeRaster.hlsl").read_text(encoding="utf-8")
    m1 = (mods/"vr/DuoViewM1D3D12.hpp").read_text(encoding="utf-8")
    cfg = (mods/"vr/DuoViewConfig.hpp").read_text(encoding="utf-8")
    vrcpp = (mods/"VR.cpp").read_text(encoding="utf-8")

    need(glam, "SharpenMaxChange)", "no limiter bypasses the per-eye value", 0)
    need(glam, "GlamMaxChange());", "both limiters use the per-eye value", 2)
    need(raster, "GlamEyeMaxChange=rightEye ? M5Sharpen.y : M5Sharpen.x;", "eye selects its limiter")
    if not (0 < hlsl.find("float4 M4Flags;") < hlsl.find("float4 M5Sharpen;") < hlsl.find("};", hlsl.find("float4 M4Flags;"))):
        failures.append("HLSL cbuffer: M5Sharpen must follow M4Flags")
    if not (0 < m1.find("float m4_flags[4]{};") < m1.find("float m5_sharpen[4]{};")):
        failures.append("C++ M1Constants: m5_sharpen must follow m4_flags")
    need(m1, "static_assert(sizeof(M1Constants) == 368);", "constants grew by one row")
    need(vrcpp, ".m2_unlinked_sharpen=true,", "normal sharpen always per eye")
    need(vrcpp, ".m23_wide_unlinked=true,", "wide sharpen always per eye")
    need(vrcpp, ".sharpen_wide=m_duo_m23_wide_left->value()>0.f || m_duo_m23_wide_right->value()>0.f,", "wide on when either eye > 0")
    for gone in ('m_duo_sharpen->draw(', 'm_duo_sharpen_max->draw(', 'm_duo_sharpen_wide->draw(',
                 'm_duo_m23_wide->draw(', 'm_duo_m23_unlinked_wide->draw(', 'm_duo_m2_unlinked->draw('):
        need(vrcpp, gone, "old linked/toggle control hidden", 0)
    for shown in ('m_duo_m5_left_max->draw(', 'm_duo_m5_right_max->draw(', 'm_duo_m2_left->draw(',
                  'm_duo_m2_right->draw(', 'm_duo_m23_wide_left->draw(', 'm_duo_m23_wide_right->draw(',
                  'm_duo_m24_distance->draw(', 'm_duo_m24_near->draw(', 'm_duo_m24_far->draw(',
                  'm_duo_m24_regular_pct->draw(', 'm_duo_m24_wide_pct->draw('):
        need(vrcpp, shown, "menu control present")

    # MSVC C7560: designated initializers must follow declaration order.
    struct = cfg[cfg.find("struct Settings {"):]
    struct = re.sub(r"//[^\n]*", "", struct[:struct.find("\n};")])
    declared = re.findall(r"(\w+)\{[^{};]*\}\s*[,;]", struct)
    start = vrcpp.find("uevr::duoview::Settings candidate{")
    block = vrcpp[start:vrcpp.find("\n    };", start)]
    used = re.findall(r"(?:^|[\s,{])\.([A-Za-z_]\w*)=(?!=)", block, re.M)
    if len(declared) < 30 or len(used) < 30:
        failures.append(f"settings parse failed: declared={len(declared)} used={len(used)}")
    pos = [declared.index(n) for n in used if n in declared]
    if pos != sorted(pos):
        bad = [used[i] for i in range(1, len(pos)) if pos[i] < pos[i-1]]
        failures.append(f"designated initializers out of declaration order near: {bad[:3]}")
    for name in ("m5_left_max", "m5_right_max"):
        if name not in declared or name not in used:
            failures.append(f"{name} not declared and initialised")

    if failures:
        print("\n".join("FAIL " + f for f in failures))
        raise SystemExit(1)
    print("PASS: M5 six per-eye sharpening sliders (limiter, menu, settings order)")


if __name__ == "__main__":
    main()
