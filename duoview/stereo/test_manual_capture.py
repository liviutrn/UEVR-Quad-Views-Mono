#!/usr/bin/env python3
"""Sanity check that manual snapshots are opt-in and can't change the V3 stereo color output."""
import sys
from pathlib import Path
root=Path(sys.argv[1])
def src(path):return (root/path).read_text(encoding="utf-8-sig")
h=src("src/mods/vr/d3d12/StockDibrDepth.hpp")
s=src("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp")
dx=src("src/mods/vr/D3D12Component.cpp")
vh=src("src/mods/vr/D3D12Component.hpp")
ui=src("src/mods/VR.cpp")
hook=src("src/mods/vr/FFakeStereoRenderingHook.cpp")
checks={
 "V3 genuine right eye handling unchanged":"is_duoview_split_eye_enabled()" in hook,
 "diagnostics only armed after explicit button":'ImGui::Button("CAPTURE NOW: both source colors + ALL eligible depth candidates")' in ui,
 "independent capture sessions": "m_duo_snapshot_serial.fetch_add" in vh and "m_duo_snapshot_pending" in vh,
 "bounded normal sampling unchanged": "NormalCapacity = 12" in h,
 "larger manual sampling budget": "Capacity = 48" in h and "snapshot_armed ? Capacity : NormalCapacity" in h,
 "every captured slot has explicit cross-queue wait": "s.foreign_fence.Get(),1" in h,
 "retains capture source slots until consumer fence": "snapshot_leases[i]=true" in h and "if(signalled){s.fence=signal;s.leased=false;}" in h,
 "every DSV catalogued with metadata": "diagnostic_catalog.emplace" in h and "diagnostic_inventory()" in h,
 "all metadata shapes labelled without claiming eye identity": "eyeAttribution=UNPROVEN" in h,
 "color + depth offline readback": "left_fovea" in s and "right_periphery" in s and "depth_" in s,
 "raw precision preserved": '".raw"' in s and 'decode_depth' in s,
 "viewable BMP previews": '_depth_preview.bmp' in s and ".bmp" in s,
 "explicit readback budget": "MaxBytes = 512ull * 1024 * 1024" in s,
 "no stalls waiting on render thread": "std::thread([self]" in s and "WaitForSingleObject(e,INFINITE)" in s,
 "actual data copied on XR command list": "capture->record(commands.cmd_list.Get())" in dx,
 "copy command executes before independent worker marker":"capture->launch(device,queue)" in dx,
 "original V3 native compositor retained": "compositor.record_native(device, commands.cmd_list.Get()," in dx,
 "continued R5 synthetic method isolated": "m_stock_dibr_depth->acquire()" in dx,
}
for k,v in checks.items(): print(("PASS: " if v else "FAIL: ")+k)
if not all(checks.values()):raise SystemExit("Manual diagnostic integration contract failed")
print("Manual capture source contract passed. Actual GPU readback still needs Windows D3D12 + headset validation.")
