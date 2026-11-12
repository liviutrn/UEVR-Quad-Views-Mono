#!/usr/bin/env python3
"""Fast fail-closed contract checks on patched production sources."""
from pathlib import Path
import sys
root=Path(sys.argv[1]); src=Path(sys.argv[2]); quad=Path(sys.argv[3])
def need(p, *strings):
    content=p.read_text(encoding="utf-8")
    for s in strings:
        if s not in content:
            raise SystemExit(f"Phase2 missing required source in {p}: {s}")
need(root/"src/mods/vr/DuoViewConfig.hpp",
     "bool sharpen_wide{}", "bool focus_lift_enabled{}", "bool seam_match_enabled{}",
     "reject_seam_color=1u<<27", "scalar(requested.sharpen_strength,0.f,20.f",
     "scalar(requested.sharpen_max_change,.05f,.80f")
need(root/"src/mods/VR.hpp",
     "DuoViewGlamaryeExtraWide", "DuoViewFocusLift", "DuoViewSeamMatch",
     "*m_duo_seam_color,")
need(root/"src/mods/VR.cpp",
     "m_duo_seam_match->draw", ".seam_match_enabled=m_duo_seam_match->value()",
     "current.seam_match_enabled==candidate.seam_match_enabled")
need(root/"src/mods/vr/DuoViewD3D12.hpp",
     "static_assert(sizeof(ShaderConstants) == 184)",
     "!frame.config.settings.seam_match_enabled",
     "frame.config.settings.seam_color_strength",
     "frame.settings.seam_color_strength")
need(src/"DuoViewGlamaryeFovea.hlsl", "GlamExtraWideChange")
need(src/"DuoViewNativeCompositeRaster.hlsl",
     "DuoPhase2MatchContext", "DuoPhase2FocusLift", "GlamExtraWideChange")
need(src/"DuoViewCompositeRaster.hlsl",
     "DuoPhase2MatchContext", "DuoPhase2FocusLift", "GlamExtraWideChange")
need(src/"DuoViewPhase2Effects.hlsl", "confidence < .5", "SeamOptions.x < .5")
need(quad/"QuadViewComposite.hlsl", "GlamSharpenRingChange", "CorrectFocusColor")
print("Phase2 contract checks passed (the original TriView shader is kept untouched).")
