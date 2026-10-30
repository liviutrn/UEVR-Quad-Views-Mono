"""Adapt the CI69-CI73/CI70 WARP fixtures to exercise CI76 pair recovery.

Usage: python ci76/adapt_legacy_tests.py PATH_TO_CHECKED_OUT_REPOSITORY

The edits are exact, one-time source rewrites. All target files are read and
validated before any file is written, so anchor drift cannot leave a partial
fixture update.
"""

from pathlib import Path
import sys


TARGETS = (
    "ci69/gpu_manual_tests.cpp",
    "ci70/gpu_preview_tests.cpp",
    "ci71/gpu_left_anchor_tests.cpp",
    "ci72/gpu_research_tests.cpp",
    "ci73/gpu_conservative_tests.cpp",
)


def replace_once(text: str, old: str, new: str, path: Path) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one CI76 fixture anchor, found {count}: {old[:100]!r}"
        )
    return text.replace(old, new, 1)


def adapt_text(text: str, path: Path) -> str:
    text = replace_once(
        text,
        " std::vector<ComPtr<ID3D12Resource>> inputs,staging;",
        " std::vector<ComPtr<ID3D12Resource>> inputs,staging;\n"
        " std::array<ngx::Guide,2> capture_guides{};",
        path,
    )
    text = replace_once(
        text,
        "  if(role==2){g.flags_known=false;g.create_observed=false;g.motion_extent_known=false;}\n"
        "  cap.capture_ngx_dlss(producer.cmd.Get(),depth.Get(),rgb.Get(),mv.Get(),g);inputs.push_back(depth);inputs.push_back(rgb);inputs.push_back(mv);",
        "  if(role==2){g.flags_known=false;g.create_observed=false;g.motion_extent_known=false;}\n"
        "  capture_guides[role-1]=g; // retain the post-override guide used by the real copy\n"
        "  cap.capture_ngx_dlss(producer.cmd.Get(),depth.Get(),rgb.Get(),mv.Get(),g);inputs.push_back(depth);inputs.push_back(rgb);inputs.push_back(mv);",
        path,
    )
    text = replace_once(
        text,
        ' auto pair=cap.select_preview(0,0,16,12,8,6,false,42,3);need(pair.left && pair.right,"NGX pair unavailable after real producer submission");',
        ''' auto pair=cap.select_preview(0,0,16,12,8,6,false,42,3);
 need(!pair.left && !pair.right,"initial NGX pair must wait for eight fresh Present epochs");
 // Drive seven more actual GPU captures. The first observation above is pair
 // one; only the eighth fresh producer/Present pair may resume stereo.
 for(unsigned frame=1;frame<=7;++frame){
  cap.finish_frame();consumer.flush();
  cap.arm_diagnostic_capture();
  for(unsigned role=1;role<=2;++role){
   auto g=capture_guides[role-1];g.evaluation+=2*frame;
   const size_t base=size_t(role-1)*3;
   cap.capture_ngx_dlss(producer.cmd.Get(),inputs[base].Get(),inputs[base+1].Get(),inputs[base+2].Get(),g);
  }
  producer.flush(&cap);
  auto next_pair=cap.select_preview(0,0,16,12,8,6,false,42,3);
  if(frame<7)need(!next_pair.left && !next_pair.right,"stereo resumed before eight fresh captures");
  else {need(next_pair.left && next_pair.right,"NGX pair unavailable after eight real captures");pair=next_pair;}
 }''',
        path,
    )
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python adapt_legacy_tests.py PATH_TO_CHECKED_OUT_REPOSITORY", file=sys.stderr)
        return 2
    root = Path(argv[1]).resolve()
    updates: list[tuple[Path, str]] = []
    for relative in TARGETS:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError(f"refusing target outside repository root: {relative}")
        original = path.read_bytes().decode("utf-8")
        newline = "\r\n" if "\r\n" in original else "\n"
        normalized = original.replace("\r\n", "\n")
        updated = adapt_text(normalized, Path(relative)).replace("\n", newline)
        updates.append((path, updated))
    for path, updated in updates:
        path.write_bytes(updated.encode("utf-8"))
    print(f"Adapted {len(updates)} real-GPU capture fixtures for eight-pair recovery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
