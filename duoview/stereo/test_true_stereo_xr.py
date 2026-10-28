#!/usr/bin/env python3
"""Fail closed on Mono presentation, missing physical-eye source or unsafe R5 lifetime."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def text(p):return (root/p).read_text(encoding="utf-8-sig")
comp=text("src/mods/vr/DuoViewD3D12.hpp")
shader=text("src/mods/vr/DuoViewStereoCompositeRaster.hlsl")
h=text("src/mods/vr/D3D12Component.hpp")
c=text("src/mods/vr/D3D12Component.cpp")
ui=text("src/mods/VR.cpp")
depth=text("src/mods/vr/d3d12/StockDibrDepth.hpp")
copy=text("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp")
checks={
"Actual left/right XR pixel shader precompiled":'native_stereo_shader_bytecode' in comp and "PSNativeStereo" in shader,
"Distinct eye outputs use physical eye half":'const bool right=i.pos.x>=float(OutputSize.x)' in shader,
"Stereo uses direct or full doublewide stereo copy":'frame.config.settings.direct_xr_output || requested_stereo' in comp and 'transition(cmd,atlas_.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,' in comp,
"Mono frame-copy cannot be stereo":'else if(indirect_eye_output)' in comp and 'else copied=copy_composite_to_stereo' in comp,
"Valid physical left/right source":'frame.split_eye' in comp and 'frame.eye_cameras[0].position' in comp,
"Full frozen left/right projections":'frame.projection_right' in comp and 'frame.projection' in comp,
"Real IPD not arbitrary full-screen disparity":'const float baseline=static_cast<float>(std::sqrt(sum))*stereoSign' in comp,
"D3D12 root constant register alignment":'static_assert(sizeof(ShaderConstants) == 240)' in comp,
"True depth-guided right fovea":'RightFovea(uv,nativeRight,confidence)' in shader and 'DeviceLeftDepth(local)' in shader,
"Right peripheral depth guides left reprojection":'RightSampleForLeft(uv,good)' in shader,
"Periphery errors use actual right color":'if(good)periphery=RightNative(shifted)' in shader,
"Right fovea keeps LEFT shading":'return LeftNative(leftUV);' in shader,
"Manual L/R DSV browsing available":'SliderInt("LEFT fovea candidate' in ui and 'SliderInt("RIGHT periphery candidate' in ui,
"Explicit headset stereo switch and proof mode":'TRUE STEREO (0 V3 mono / 1 stereo / 2 tint proof)' in ui,
"Depth preview must not silently replace real stereo PSO":'const bool depthPreview=!requested_stereo && previewMode>=1u' in comp,
"Experimental opt-in starts with V3 mode 0 until capture observer active":'m_duo_stereo_mode{0}' in h,
"DuoView retires one depth interval at the existing Present tail":'duoview_interval_owner->finish_frame' in c and 'Existing tail guard owns the one DuoView epoch advance' in c,
"Raw screenshot includes stereo XR output":'"xr_submitted_doublewide"' in copy,
"Final XR image attached inside rendering callback":'if(capture->attach_headset_output(device,destination) &&' in c,
"Final XR readback reservation":'reserve_headset_output_' in copy and '128ull*1024*1024' in copy,
"Undeclared XR destination cannot enter pre-copy frame prep":'m_scene_capture_tex.texture.Get(),candidates,\n                                    true))' in c and 'm_scene_capture_tex.texture.Get(),candidates,\n                                    destination))' not in c,
"Every screenshot retains stereo choices":'stereoMode=' in c and 'manualLeft=' in c,
"R5 depth copy state supports pixel reads":'D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE' in depth,
"Stereo active when preview disabled":'if(m_stock_dibr_scope && (preview_mode || stereo_mode))' in c,
"Stereo root constants within DX12 root-size limit":'static_assert(sizeof(ShaderConstants) / 4 + 1 <= 64)' in comp,
"Depth rect metadata captured with immutable selected resources":'left_viewport=depths.left_viewport' in c and 'right_viewport=depths.right_viewport' in c,
"Distinct per-eye depth coefficients reach shader":'constants.stereo_left_depth_z[1]=l[14]' in comp and 'LeftEyeForwardZ(DeviceLeftDepth(local))' in shader,
"Unknown or invalid depth viewport rejects before recording":'depth_viewport_valid(leftViewport' in comp and comp.index('depth_viewport_valid(leftViewport')<comp.index('ensure_depth_srvs(device,leftDepth,rightDepth)'),
"Recorded does not claim delivered":'m_duo_stereo_recorded_frames.fetch_add' in c and 'trueStereoDelivered=' not in c,
"Submitted counter follows copy outcome":c.index('m_duo_stereo_frames.fetch_add')>c.index('// One outcome per copy attempt.'),
"Both stages and frame semantics explicitly unverified":'sourceRoleVerified=false sourceFrameVerified=false sourceStageVerified=false' in c,
"Whole-eye tint on peripheral early return":'if(feather<=0.0f) return StereoProofColor(' in shader,
"Readback saving requires actual enqueue, not merely recording":'commands_were_submitted(capture_submission)' in c and 'capture_submission=result' in c,
"Capture records release separately from physical presentation":'headsetPresentationVerified=false' in copy and 'xrCopyReleased=' in copy,
"Stock early retirement cannot erase DuoView candidates":'if(m_stock_dibr_scope && !duoview_depth_interval)' in c,
"Missing depth never destroys the two-view producer":'effective_stereo_mode=depths.left && depths.right' in c and 'rendering V3 mono without disabling two-view capture' in c,
"Mono fallback cannot inflate stereo submitted counters":'if(submitted && stereo_recorded && callback_attempted)' in c,
"Depth-less capture request stays pending and armed":'if(candidates.empty() || !capture->prepare' in c and 'snapshot_armed=keep_snapshot_armed' in depth,
"Camera metadata preserves precision and explicit matrix uncertainty":'std::setprecision(17)' in c and 'frozenSourceProjection_NOT_depthPassVerified_L=[' in c,
"Incomplete snapshot allocation never reports complete XR readback":'(!require_complete_snapshot_ || depth_ready)' in copy and '(require_complete_snapshot_ && !final_output_attached_)' in copy,
"Prior copy status cleared before current color-pair check":c.index('m_duo_stereo_output.store(3u')<c.index('const bool packet_pair_valid'),
}
for name,valid in checks.items():print(("PASS: " if valid else "FAIL: ")+name)
if not all(checks.values()):raise SystemExit("Physical stereo XR integration contract FAILED")
