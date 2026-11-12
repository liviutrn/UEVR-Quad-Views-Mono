#!/usr/bin/env python3
"""v208b: user-adjustable Glamarye fovea "max change per pixel" limiter.

Applies AFTER apply_v208_shared_eye_vram.py on the already patched tree.

The settings field Settings::sharpen_max_change (default 0.10f = v208 output,
range 0.05..0.30) and reject_sharpen_max are declared in the duoview/ sources
copied by apply_stage234.py. This script wires the menu slider only:
  VR.hpp: slider declaration, persisted-controls list
  VR.cpp: restore-defaults reset, draw call, reject label, candidate settings,
          change-detection equality
Every anchor must occur exactly once; any mismatch stops the build.
Shader math and the 0.02f FXAA bias are not touched.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_v208b_sharpen_max_change.py <backend>")
root = Path(sys.argv[1])
files = {}


def load(rel):
    if rel not in files:
        files[rel] = (root / rel).read_text(encoding="utf-8-sig")
    return files[rel]


def replace(rel, old, new, count=1, label=""):
    text = load(rel)
    found = text.count(old)
    if found != count:
        raise SystemExit(f"v208b anchor mismatch in {rel} ({label or old[:60]!r}): found {found}, expected {count}")
    files[rel] = text.replace(old, new)


# Precondition: the copied settings header must already carry the new field
# and reject bit (they come from duoview/DuoViewConfig.hpp via apply_stage234).
CFG = "src/mods/vr/DuoViewConfig.hpp"
for token in ("float sharpen_max_change{.10f};", "reject_sharpen_max=1u<<18",
              "scalar(requested.sharpen_max_change,.05f,.30f,reject_sharpen_max"):
    if token not in load(CFG):
        raise SystemExit(f"v208b precondition missing in {CFG}: {token}")

VRH = "src/mods/VR.hpp"
# The strength slider's range differs between upstream builds (2.f in some
# trees, 5.f in the current one), so anchor on the line prefix and require
# exactly one such line.
SLIDER_PREFIX = '    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength")'
lines = load(VRH).split("\n")
hits = [i for i, line in enumerate(lines) if line.startswith(SLIDER_PREFIX)]
if len(hits) != 1:
    raise SystemExit(f"v208b anchor mismatch in {VRH} (declare slider): found {len(hits)}, expected 1")
lines.insert(hits[0] + 1,
    '    const ModSlider::Ptr m_duo_sharpen_max{ModSlider::create(generate_name("DuoViewGlamaryeFoveaMaxChange"), 0.05f, 0.30f, 0.10f)};')
files[VRH] = "\n".join(lines)
replace(VRH, "            *m_duo_sharp_periphery,\n",
        "            *m_duo_sharp_periphery,\n            *m_duo_sharpen_max,\n",
        label="persisted list")

VRC = "src/mods/VR.cpp"
replace(VRC, "m_duo_sharpen->value()=1.f;",
        "m_duo_sharpen->value()=1.f; m_duo_sharpen_max->value()=.10f;",
        label="restore defaults")
replace(VRC, '                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");\n',
        '                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");\n'
        '                m_duo_sharpen_max->draw("Glamarye fovea max change per pixel (default 0.10; higher = stronger on hard edges, more halo risk)");\n',
        label="draw")
replace(VRC, '                        {uevr::duoview::reject_sharpen,"Glamarye strength"},\n',
        '                        {uevr::duoview::reject_sharpen,"Glamarye strength"},\n'
        '                        {uevr::duoview::reject_sharpen_max,"Glamarye max change"},\n',
        label="reject label")
# Field order: sharpen_max_change is declared right after sharpen_strength,
# so its designated initializer goes there too (C++20 requires declaration order).
replace(VRC, ".sharpen_strength=m_duo_sharpen->value(), ",
        ".sharpen_strength=m_duo_sharpen->value(), .sharpen_max_change=m_duo_sharpen_max->value(), ",
        label="candidate settings")
replace(VRC, "current.sharpen_strength==candidate.sharpen_strength &&\n",
        "current.sharpen_strength==candidate.sharpen_strength &&\n"
        "        current.sharpen_max_change==candidate.sharpen_max_change &&\n",
        label="change detection")

for rel, text in files.items():
    (root / rel).write_text(text, encoding="utf-8", newline="")
print(f"v208b applied: Glamarye fovea max change slider (default 0.10); {len(files)} files edited")
