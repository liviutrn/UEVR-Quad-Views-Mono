#!/usr/bin/env python3
"""DepthBridge V1.1: expose bounded GPU-proven capture provenance, without claiming eye identity.

Runs AFTER stock_dibr/apply_ui_retirement_fix.py and integrate_r5_v1.py.
Fail closed if upstream anchors change. Zero changes to compositor output or stereo shader.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: enhance_depth_bridge_v1.py <patched-backend>")
root = Path(sys.argv[1]).resolve()

def replace_once(path: str, old: str, new: str, label: str):
    p = root / path
    s = p.read_text(encoding="utf-8-sig")
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor in {path}; got {count}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8", newline="")

depth = "src/mods/vr/d3d12/StockDibrDepth.hpp"
replace_once(depth, '#include <string>', '#include <string>\n#include <sstream>\n#include <cstdint>', "Diagnostic headers")
replace_once(depth, '    std::string observed{"none"};',
'''    std::string observed{"none"};
    // Last successfully submitted DSV/viewport proofs. Metadata only:
    // neither color matching nor a semantic camera/eye assertion.
    std::array<std::string, 4> recent_depth_proofs{};
    uint64_t recent_depth_proof_count{};''', "Bounded provenance history")
replace_once(depth, '            else ++submitted;',
'''            else {
                ++submitted;
                const auto desc = s.source->GetDesc();
                const auto& vp = s.viewport;
                std::ostringstream proof;
                proof << "#" << s.serial << " epoch=" << s.epoch
                      << " source=0x" << std::hex
                      << reinterpret_cast<std::uintptr_t>(s.source.Get()) << std::dec
                      << " allocation=" << desc.Width << "x" << desc.Height
                      << " format=" << static_cast<unsigned>(desc.Format)
                      << " viewport=(" << vp.TopLeftX << "," << vp.TopLeftY
                      << "," << vp.Width << "," << vp.Height << ")"
                      << " eyeAttribution=UNKNOWN"
                      << " queue=" << (current_queue ? "present" : "fenced-foreign");
                recent_depth_proofs[recent_depth_proof_count % recent_depth_proofs.size()] = proof.str();
                ++recent_depth_proof_count;
            }''', "Store only GPU-submitted candidate proof")
replace_once(depth, '''    std::string summary() const {
        std::scoped_lock lock{mutex};
        return last +''',
'''    std::string summary() const {
        std::scoped_lock lock{mutex};
        std::string proofs;
        const auto count = std::min<uint64_t>(recent_depth_proof_count, recent_depth_proofs.size());
        for (uint64_t index = 0; index < count; ++index) {
            const auto slot = (recent_depth_proof_count - count + index) % recent_depth_proofs.size();
            if (!proofs.empty()) proofs += " | ";
            proofs += recent_depth_proofs[slot];
        }
        if (proofs.empty()) proofs = "none submitted";
        return last +''', "Compose bounded provenance")
replace_once(depth, '''            " observed=" + observed;''',
'''            " observed=" + observed +
            " proofHistory=[" + proofs + "]";''', "Append provenance to status")
# Make depth evidence visible in the headset's existing DuoView settings window.
vr = "src/mods/VR.cpp"
replace_once(vr,
    '                m_dibr_ue5_rdg_depth_capture->draw("R5 DSV/RDG capture in DuoView (experimental, opt-in)");',
    '''                m_dibr_ue5_rdg_depth_capture->draw("R5 DSV/RDG capture in DuoView (experimental, opt-in)");
                if (m_dibr_ue5_rdg_depth_capture->value()) {
                    ImGui::TextWrapped("R5 capture is diagnostic-only: no synthetic stereo and NO proven eye assignment yet.");
                    ImGui::TextWrapped("Enable capture, exit and re-enter mode ID6 for observer activation. Compare fovea-only/periphery-only color using the source diagnostic above.");
                    const auto depth_proof = m_d3d12.get_dibr_preview_depth_trace_summary();
                    ImGui::TextWrapped("Depth DSV/queue proof: %s", depth_proof.c_str());
                    ImGui::TextWrapped("Proof means submitted GPU DSV/viewport; it does NOT guarantee association with UE0 LEFT or UE1 RIGHT.");
                }''', "In-game visible depth proof")

print("DepthBridge V1.1: bounded depth provenance and screenshot-ready in-game UI attached; output unchanged.")
