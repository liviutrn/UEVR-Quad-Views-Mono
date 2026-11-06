#!/usr/bin/env python3
"""TriView B21: restore B15-27's user-validated depth availability policy.

Apply after B18 integration tests. Inherits B18's Reset epochs, command-list
submission sequencing, depth leases, three physical sources and UI. Does not
add a GPU queue Wait. This is not a claim of exact depth/color frame identity.
"""
from pathlib import Path
import sys

def one(src: str, before: str, after: str, name: str) -> str:
    matches = src.count(before)
    if matches != 1:
        raise RuntimeError(f"B21 {name}: expected one exact anchor, found {matches}")
    return src.replace(before, after, 1)

def patch_depth(src: str) -> str:
    src = one(src,
        """    // Explicitly approximate: size/submission prove neither UE role nor scene.
    // Reject copies recorded before this color packet was born. This temporal
    // bound prevents definite stale reuse, but is not exact source identity.
    // The compositor retains the snapshot through its own GPU retirement.
    std::shared_ptr<const DepthSnapshot> latest_approximate_since(std::chrono::steady_clock::time_point not_before) {""",
        """    // B21: restore the B15-27 selector, which was stable in the headset.
    // Use only a recently SUBMITTED peripheral snapshot (<=250 ms), not an
    // arbitrary NGX recording timestamp relative to this packet's birth.
    // Render/RHI/present work overlaps, so packet-birth time is not a reliable
    // NGX frame association. Exact depth/color provenance is NOT established.
    // B18 Reset epochs, fence checks and compositor-held leases are retained.
    std::shared_ptr<const DepthSnapshot> latest_recent_submitted() {""",
        "replace restrictive B18 packet-born selector")
    src = one(src,
        "depth_capture_in_window(slot->recorded,not_before,now) && (!best || slot->sequence > best->sequence)",
        "now >= slot->submitted_at && now - slot->submitted_at < std::chrono::milliseconds(250) && (!best || slot->sequence > best->sequence)",
        "restore B15's 250 ms submitted-age bound")
    src = one(src,
        "std::chrono::microseconds>(now - best->recorded).count()",
        "std::chrono::microseconds>(now - best->submitted_at).count()",
        "age diagnostic matches selection")
    return src

def patch_consumer(src: str) -> str:
    return one(src,
        "uevr::quadview::ngx::PeripheryDepth::self().latest_approximate_since(packet->depth_not_before)",
        "uevr::quadview::ngx::PeripheryDepth::self().latest_recent_submitted()",
        "use B15 submission selector in compositor")

def patch_vr(src: str) -> str:
    return one(src,
        'ImGui::SetTooltip("Depth is matched by size and capture time, not exact scene identity. Fast motion may show mismatch.");',
        'ImGui::SetTooltip("B21: recent submitted periphery depth (B15 policy). Exact color/depth frame identity is not proven.");',
        "truthful UI depth-status tooltip")

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_b21_depth_selector.py <backend>")
    root=Path(sys.argv[1])/"src/mods"
    transforms={
        root/"vr/QuadViewNgxDepth.hpp": patch_depth,
        root/"vr/D3D12Component.cpp": patch_consumer,
        root/"VR.cpp": patch_vr,
    }
    # Atomic authoring: validate all anchors before writing any file.
    changes={path: f(path.read_text(encoding="utf-8")) for path,f in transforms.items()}
    for path,updated in changes.items():
        path.write_text(updated,encoding="utf-8",newline="\n")
    print("B21 from B18-42: B15-27 recent-depth selection restored; no GPU waits, shader or texture changes")

if __name__ == "__main__":
    main()
