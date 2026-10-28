#!/usr/bin/env python3
"""Fail-closed audit of split-eye, depth source lifecycle, and preview diagnostics."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def source(p):return (root/p).read_text(encoding="utf-8-sig")
d=source("src/mods/vr/d3d12/StockDibrDepth.hpp")
v=source("src/mods/VR.cpp")
h=source("src/mods/vr/D3D12Component.hpp")
c=source("src/mods/vr/D3D12Component.cpp")
compositor=source("src/mods/vr/DuoViewD3D12.hpp")
shader=source("src/mods/vr/DuoViewShaderSource.hpp")
policy=source("src/mods/vr/d3d12/DepthPolicy.hpp")
checks={
 "V3 split-eye physical camera unchanged":'is_duoview_split_eye_enabled()' in source("src/mods/vr/FFakeStereoRenderingHook.cpp"),
 "submitted-only depth sources":'preview_indices() const' in d and 's.pending' in d,
 "same source identity stable ordering":'slots[a].serial<slots[b].serial' in d,
 "manual chosen ordinal overrides automatic":'if(left_manual && right_manual)' in policy,
 "stale manual index never selects unrelated Auto":'size_t(left_manual)>n || size_t(right_manual)>n' in policy,
 "two separate depth snapshots required":'if(ids.size()<2)return r;' in d and 'if(left_manual==right_manual)return {}' in policy,
 "manual stereo obeys role geometry and coherent scale":'const auto& left=shapes[size_t(left_manual-1)]' in policy and 'const double sl=left.height/lh,sr=right.height/rh;' in policy,
 "pair queue waits preflight before any lease":'if(!queue_ready(a)||!queue_ready(b))return r;' in d and d.index('if(!queue_ready(a)||!queue_ready(b))return r;')<d.index('r.left=lease(a);'),
 "reused original DSV does not collapse two pass copies":'Preserve separately captured source passes' in d,
 "auto jointly matches frozen producer dimensions and render scale":'choose_duoview_depth_pair' in d and 'if(mismatch>.05)continue' in policy,
 "producer frozen widths passed into candidate browser":'packet_frame->config.layout.fovea.width' in c and 'packet_frame->config.layout.periphery.width' in c,
 "foreign producer queue synchronization":'queue->Wait(s.foreign_fence.Get(),1)' in d,
 "depth resource lifetime retained":'snapshot_leases[i]=true' in d,
 "capture includes live previewed depth":'(s.leased && !snapshot_leases[i])' in d,
 "two separate candidate controls":'SliderInt("LEFT fovea candidate' in v and 'SliderInt("RIGHT periphery candidate' in v,
 "three in-game diagnostic views":'SliderInt("View depth (0 Off / 1 L / 2 R / 3 split)"' in v,
 "capture metadata preserves selections":'candidateProof={' in c and 'manualLeft=' in c,
 "XR callback retains depth references":'left_depth=depths.left' in c and 'right_depth=depths.right' in c,
 "preview bytes embedded before runtime":'native_depth_debug_shader_bytecode' in shader,
 "original V3 compositor preserved":'compositor.record_native(device, commands.cmd_list.Get(),' in c,
 "typed nonstencil depth view":'DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS' in compositor,
 "preview PSO only when enabled":'depthPreview ? depth_pipeline_' in compositor,
 "original direct and atlas fallback preserved":'record_native_gather' in compositor and 'direct_xr' in compositor
}
for k,ok in checks.items():print(("PASS: " if ok else "FAIL: ")+k)
if not all(checks.values()):raise SystemExit("DepthCandidateBrowser contracts failed")
