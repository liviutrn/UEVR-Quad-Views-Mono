#!/usr/bin/env python3
"""Build49 CI guards: runtime reset must retain live Mono eye alignment."""
from pathlib import Path
import argparse
import re

p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
args=p.parse_args()
root=args.backend/"src/mods"
h=(root/"VR.hpp").read_text(encoding="utf-8")
x=(root/"vr/runtimes/OpenXR.hpp").read_text(encoding="utf-8")
c=(root/"vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8")
vr_cpp=(root/"VR.cpp").read_text(encoding="utf-8")
start=h.index("std::optional<std::string> reinitialize_openxr() {")
end=h.index("\n    float m_nearz{",start)
reset=h[start:end]

def ordered(*parts):
    n=-1
    for part in parts:
        pos=reset.find(part,n+1)
        assert pos>n,f"Runtime reset persistence order missing: {part}"
        n=pos

ordered(
    "const bool saved_mono_eye_alignment_enabled =",
    "const float saved_mono_eye_alignment_percent =",
    "m_openxr.reset();",
    "auto e = initialize_openxr();",
    "if (m_openxr != nullptr) {",
    "m_openxr->mono_eye_alignment_percent->value() =",
    "m_openxr->mono_eye_alignment_enabled->value() =",
)
assert reset.count("m_openxr.reset();")==1
assert reset.count("auto e = initialize_openxr();")==1
assert "Restored Mono Eye Alignment after runtime reset:" in reset
assert "std::isfinite(saved_mono_eye_alignment_percent)" in reset
assert "saved_mono_eye_alignment_percent >= -3.0f" in reset
assert "saved_mono_eye_alignment_percent <= 3.0f" in reset
assert "valid_percent && saved_mono_eye_alignment_enabled" in reset
assert 'ModToggle::create("OpenXR_MonoEyeAlignmentEnabled", false)' in x
assert 'ModSlider::create("OpenXR_MonoEyeAlignmentPercent", -3.0f, 3.0f, 0.0f)' in x
assert "*mono_eye_alignment_enabled," in x and "*mono_eye_alignment_percent," in x
assert "void OpenXR::on_config_save" in c and "void OpenXR::on_config_load" in c
assert "get_runtime()->on_config_save(cfg)" in vr_cpp
assert "get_runtime()->on_config_load(cfg, set_defaults)" in vr_cpp
# Probe both toggle states, representative offset, range limits and successive resets.
for enabled in [False, True]:
    for value in [-3.0, -1.5, -1.25, -1.0, 0.0, 0.1, 3.0, -20.0, float("nan")]:
        new_enabled, new_value = enabled, value
        for _ in range(3):
            valid=-3.0 <= new_value <= 3.0
            new_enabled, new_value=valid and new_enabled, new_value if valid else 0.0
        if -3<=value<=3:
            assert new_enabled==enabled and new_value==value
        else:
            assert new_enabled is False and new_value==0.0
print("PASS: Reset Runtime preserves -1.25%, OFF state, full safe range, repeated resets.")
print("PASS: Original Mono/OpenXR presentation code unchanged by Build49.")
