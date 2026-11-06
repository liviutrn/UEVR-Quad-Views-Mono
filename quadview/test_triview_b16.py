#!/usr/bin/env python3
"""B16 generated-backend source contracts. Production C++ compiles in the same workflow."""
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit("usage: test_triview_b16.py <backend>")
src=(Path(sys.argv[1])/"src/mods/VR.cpp").read_text(encoding="utf-8")
tests={
 "bounded settings viewport": 'ImGui::BeginChild("TriViewScrollBody"' in src,
 "viewport properly closed": src.count('ImGui::BeginChild("TriViewScrollBody"')==1 and
                              src.count('ImGui::EndChild();\n                ImGui::TreePop();')==1,
 "scroll independent from mouse wheel": "TriViewUp" in src and "TriViewDown" in src and "ImGui::SetScrollY" in src,
 "config values tracked": "m_quadview_depth_strength->value()" in src and
                          "m_quadview_sharpen_right->value()" in src and
                          "m_quadview_crop_width->value()" in src,
 "stable auto save": "tri_save_pending && tri_now-tri_change_tick>=750" in src and
                      "g_framework->deferred_save_config()" in src,
 "manual save": "Save TriView settings now" in src,
 "GPU retirement-aware resizing": "get_quadview_native_retirement_diagnostics()" in src and
                  "retired.in_flight || retired.ready" in src,
 "resize never hard caps crop": "safe_request=false" in src and
                    "m_triview_pending_extents=decision.request_extents" in src,
}
for n,ok in tests.items():
 print(("PASS" if ok else "FAIL")+" B16 "+n)
if not all(tests.values()):raise SystemExit("B16 generated source tests failed")
