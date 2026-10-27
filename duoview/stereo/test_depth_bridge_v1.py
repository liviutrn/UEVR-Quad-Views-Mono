#!/usr/bin/env python3
"""Source-level fail-closed guard for V3 plus R5 diagnostics; WARP/production CI is separate."""
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
def text(path):
    return (root / path).read_text(encoding="utf-8-sig")
dep=text("src/mods/vr/d3d12/StockDibrDepth.hpp")
ui=text("src/mods/VR.cpp")
hook=text("src/mods/vr/FFakeStereoRenderingHook.cpp")
dx=text("src/mods/vr/D3D12Component.cpp")
checks = {
 "source eye handling preserved": "is_duoview_split_eye_enabled()" in hook and "true_index = view_index;" in hook,
 "V3 fovea sourced from left": 'if (source_split) candidate.fovea_view = 0u;' in ui,
 "R5 DSV observer installed": "m_stock_dibr_depth" in dx,
 "R5 GPU proof must precede publication": "select_executed_main_binding(" in dep and "if (!provenance_ok)" in dep,
 "bounded four-entry provenance history": "std::array<std::string, 4> recent_depth_proofs" in dep,
 "depth resource and DSV viewport included": '<< " allocation="' in dep and '<< " viewport=("' in dep,
 "explicit unknown semantic eye association": "eyeAttribution=UNKNOWN" in dep,
 "headset screenshot-ready depth summary": 'ImGui::TextWrapped("Depth DSV/queue proof: %s", depth_proof.c_str());' in ui,
 "diagnostics opt-in": 'm_dibr_ue5_rdg_depth_capture->value()' in ui,
 "no second depth acquire in DuoView diagnostic path": dx.count("m_stock_dibr_depth->acquire()") == 1,
 "existing output compositor preserved": "compositor.record_native(device, commands.cmd_list.Get()," in dx,
}
for name,ok in checks.items():
    print(("PASS: " if ok else "FAIL: ")+name)
if not all(checks.values()):
    raise SystemExit("DuoView depth provenance regression failed")
print("All metadata-only depthbridge diagnostics source gates passed. Camera/depth matching remains in-game unproven.")
