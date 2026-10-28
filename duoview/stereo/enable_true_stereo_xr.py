#!/usr/bin/env python3
"""True stereo OpenXR submission; applied after attach_depth_probe.py.
No source view changes: V3 still renders physical LEFT fovea and RIGHT periphery.
Stereo is fused to a double-wide XR texture by one new raster pass.
"""
from pathlib import Path
import sys, shutil
if len(sys.argv)!=2: raise SystemExit("usage: enable_true_stereo_xr.py <patched-backend>")
root=Path(sys.argv[1])
shutil.copyfile(Path(__file__).resolve().parent.parent/"DuoViewStereoCompositeRaster.hlsl",
                root/"src/mods/vr/DuoViewStereoCompositeRaster.hlsl")
def edit(path,old,new,label):
    p=root/path;data=p.read_text(encoding="utf-8-sig")
    if data.count(old)!=1:raise RuntimeError("Stereo XR "+label+" expected one anchor, got "+str(data.count(old)))
    p.write_text(data.replace(old,new,1),encoding="utf-8",newline="")
# V3 split-eye patch adds these camera fields ONLY to backend's ViewFrame.
# The workspace baseline retains the original POD type for older WARP tests.
edit("src/mods/vr/DuoViewState.hpp","#pragma once",
     "#pragma once\n#define UEVR_DUOVIEW_V3_CAMERA_FIELDS 1",
     "marker for real split-eye metadata")
header="src/mods/vr/D3D12Component.hpp"
edit(header,'    std::atomic<uint32_t> m_duo_preview_mode{0};',
'''    std::atomic<uint32_t> m_duo_preview_mode{0};
    // Opt-in only: without the R5 observer, stereo is NOT ready at ID6 startup.
    // Starting at mode 1 can trigger compositor rejection and switch away from
    // DuoView before the user can enable capture/re-enter ID6.
    std::atomic<uint32_t> m_duo_stereo_mode{0};
    std::atomic<bool> m_duo_stereo_reverse{false};
    std::atomic<uint64_t> m_duo_stereo_frames{0};
    std::atomic<uint64_t> m_duo_stereo_recorded_frames{0};
    std::atomic<uint64_t> m_duo_stereo_reject_frames{0};''',"stereo controls")
edit(header,'    int duoview_left_choice() const {return m_duo_left_choice.load();}',
'''    uint32_t duoview_stereo_mode() const {return m_duo_stereo_mode.load();}
    bool duoview_stereo_reverse() const {return m_duo_stereo_reverse.load();}
    uint64_t duoview_stereo_frames() const {return m_duo_stereo_frames.load();}
    uint64_t duoview_stereo_recorded_frames() const {return m_duo_stereo_recorded_frames.load();}
    uint64_t duoview_stereo_rejected_frames() const {return m_duo_stereo_reject_frames.load();}
    void duoview_stereo_config(uint32_t mode,bool reverse) {
        m_duo_stereo_mode.store((std::min)(mode,2u),std::memory_order_release);
        m_duo_stereo_reverse.store(reverse,std::memory_order_release);
    }
    int duoview_left_choice() const {return m_duo_left_choice.load();}''',"UI public getters")
vr="src/mods/VR.cpp"
edit(vr,'                    const int n=m_d3d12.duoview_depth_candidate_count();',
'''                    int stereo_mode=int(m_d3d12.duoview_stereo_mode());
                    bool stereo_reverse=m_d3d12.duoview_stereo_reverse();
                    bool mode_changed=false;
                    mode_changed|=ImGui::SliderInt("TRUE STEREO (0 V3 mono / 1 stereo / 2 tint proof)",&stereo_mode,0,2);
                    mode_changed|=ImGui::Checkbox("Reverse stereo parallax sign (A/B)",&stereo_reverse);
                    if(mode_changed)m_d3d12.duoview_stereo_config(uint32_t(stereo_mode),stereo_reverse);
                    ImGui::Text("Experimental stereo XR copies submitted: %llu | rejected: %llu",
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_frames()),
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_rejected_frames()));
                    ImGui::Text("Stereo commands recorded: %llu (not headset delivery)",
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_recorded_frames()));
                    ImGui::TextWrapped("EXPERIMENTAL: depth eye/frame/stage identity UNVERIFIED. Stereo uses per-eye raster or a doublewide intermediate. Mode 2 tints the ENTIRE RIGHT eye. Submitted means queue copy + XR image release; headset presentation is not measured.");
                    const int n=m_d3d12.duoview_depth_candidate_count();''',"mode UI")
dc="src/mods/vr/D3D12Component.cpp"
edit(dc,'''                            const uint32_t preview_mode=m_duo_preview_mode.load(std::memory_order_acquire);
                            stock_dibr::DepthCapture::PreviewPair depths{};
                            if(m_stock_dibr_scope && preview_mode) {
                                depths=m_stock_dibr_depth->select_preview(
                                    m_duo_left_choice.load(),m_duo_right_choice.load(),
                                    packet_frame->config.layout.fovea.width,
                                    packet_frame->config.layout.fovea.height,
                                    packet_frame->config.layout.periphery.width,
                                    packet_frame->config.layout.periphery.height);
                            }
                            if(preview_mode && (!depths.left||!depths.right))
                                SPDLOG_WARN_EVERY_N_SEC(2,"[DuoView][Preview] Candidate pair unavailable; use manual sliders and capture ZIP");''',
'''                            const uint32_t preview_mode=m_duo_preview_mode.load(std::memory_order_acquire);
                            const uint32_t stereo_mode=m_duo_stereo_mode.load(std::memory_order_acquire);
                            const float stereo_sign=m_duo_stereo_reverse.load(std::memory_order_acquire)?-1.0f:1.0f;
                            stock_dibr::DepthCapture::PreviewPair depths{};
                            if(m_stock_dibr_scope && (preview_mode || stereo_mode)) {
                                depths=m_stock_dibr_depth->select_preview(
                                    m_duo_left_choice.load(),m_duo_right_choice.load(),
                                    packet_frame->config.layout.fovea.width,
                                    packet_frame->config.layout.fovea.height,
                                    packet_frame->config.layout.periphery.width,
                                    packet_frame->config.layout.periphery.height);
                            }
                            if((preview_mode||stereo_mode) && (!depths.left||!depths.right)) {
                                static uint64_t last_missing_warn=0;
                                const auto now=GetTickCount64();
                                if(now-last_missing_warn>2000) {
                                    last_missing_warn=now;
                                    SPDLOG_WARN("[DuoView][StereoXR] No submitted depth pair yet. Select another LEFT or RIGHT candidate, or re-enter ID6.");
                                }
                            }''',"remove invalid spdlog macro and acquire real stereo depth")
edit(dc,'''                                info << " previewMode=" << preview_mode''',
'''                                info << " stereoMode=" << stereo_mode
                                     << " stereoReversed=" << (stereo_sign<0)
                                     << " stereoCopiesSubmitted=" << m_duo_stereo_frames.load()
                                     << " stereoCommandsRecorded=" << m_duo_stereo_recorded_frames.load()
                                     << " sourceRoleVerified=false sourceFrameVerified=false sourceStageVerified=false"
                                     << " trueStereoRejected=" << m_duo_stereo_reject_frames.load();
                                info << " previewMode=" << preview_mode''',"record replay metadata")
edit(dc,'''                                 left_depth=depths.left,right_depth=depths.right,preview_mode](''',
'''                                 left_depth=depths.left,right_depth=depths.right,preview_mode,
                                 stereo_mode,stereo_sign,
                                 left_viewport=depths.left_viewport,right_viewport=depths.right_viewport](''',"XR callback locks stereo policy")
edit(dc,'''                                        left_depth.Get(),right_depth.Get(),preview_mode);''',
'''                                        left_depth.Get(),right_depth.Get(),preview_mode,
                                        stereo_mode,stereo_sign,
                                        {left_viewport.TopLeftX,left_viewport.TopLeftY,left_viewport.Width,left_viewport.Height,left_viewport.MinDepth,left_viewport.MaxDepth},
                                        {right_viewport.TopLeftX,right_viewport.TopLeftY,right_viewport.Width,right_viewport.Height,right_viewport.MinDepth,right_viewport.MaxDepth});
                                    if(stereo_mode) {
                                        if(recorded && compositor.last_true_stereo())
                                            m_duo_stereo_recorded_frames.fetch_add(1,std::memory_order_relaxed);
                                    }''',"stereo GPU recording counter, not delivery")
edit(dc,'''                            if (submitted && recorded && callback_attempted) {
                                native_stereo_hook->duoview_delivery.result''',
'''                            // One outcome per copy attempt. OpenXR::copy returns true
                            // only after checked queue enqueue and successful image release.
                            // This is NOT proof of xrEndFrame or physical display.
                            if(stereo_mode) {
                                if(submitted && recorded && callback_attempted)
                                    m_duo_stereo_frames.fetch_add(1,std::memory_order_relaxed);
                                else m_duo_stereo_reject_frames.fetch_add(1,std::memory_order_relaxed);
                            }
                            if (submitted && recorded && callback_attempted) {
                                native_stereo_hook->duoview_delivery.result''',"post-copy submitted accounting")
edit(dc,'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode)
                                    m_stock_dibr_depth->finish_frame();''',
'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode || stereo_mode)
                                    m_stock_dibr_depth->finish_frame();''',"depth GPU consumer retirement")
# The OpenXR destination pointer exists ONLY inside the frame-copy callback.
# Reserve 128 MiB of one-shot readback budget for the FINAL stereo output,
# then attach the actual destination after compositor.record_native completed.
# No readback occurs on ordinary frames; a one-shot readback allocation in the
# XR callback is preferable to capturing the wrong/null resource.
dump="src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp"
edit(dump,'''    UINT64 total_bytes_{};''',
'''    UINT64 total_bytes_{};
    bool reserve_headset_output_{};
    bool final_output_attached_{};''',"one-shot final XR reservation")
edit(dump,'''           total_bytes_+bytes>MaxBytes) {''',
'''           total_bytes_+bytes>MaxBytes-(reserve_headset_output_ ? 128ull*1024*1024 : 0ull)) {''',
"reserve readback space for doublewide OpenXR image")
edit(dump,'''           const std::vector<Candidate>& depths) {
        add_image(dev,left,''',
'''           const std::vector<Candidate>& depths,
           bool reserveHeadsetOutput=false) {
        reserve_headset_output_=reserveHeadsetOutput;
        add_image(dev,left,''',"reserve output before raw depth captures")
edit(dump,'''    bool record(ID3D12GraphicsCommandList* cmd) {''',
'''    bool attach_headset_output(ID3D12Device* dev,ID3D12Resource* destination) {
        if(final_output_attached_)return true;
        reserve_headset_output_=false;
        final_output_attached_=true;
        // GPU copy occurs only after actual stereo pixel shader has drawn.
        // The R5 sources and final headset target share the same OpenXR
        // command-list and fence, so the manifest describes ONE frame.
        return add_image(dev,destination,D3D12_RESOURCE_STATE_RENDER_TARGET,
                         "xr_submitted_doublewide",false,
                         "FINAL headset image. LEFT x=0..W-1, RIGHT x=W..2W-1; same copy command as source color and depth.");
    }
    bool record(ID3D12GraphicsCommandList* cmd) {''',
"one-shot XR destination allocation inside callback")
edit(dc,'''                                    m_scene_capture_tex.texture.Get(),candidates)) capture.reset();''',
'''                                    m_scene_capture_tex.texture.Get(),candidates,
                                    true)) capture.reset();''',"reserve final XR capture without undeclared destination")
edit(dc,'''                                    if (recorded && capture) {
                                        // Sources have been restored to their native RT states''',
'''                                    if (recorded && capture) {
                                        // XR destination exists only in the copy callback.
                                        // Capture the FINAL separately composed two-eye image.
                                        capture->attach_headset_output(device,destination);
                                        // Sources have been restored to their native RT states''',
"bind real final XR destination after successful stereo recording")
print("TRUE XR STEREO: actual two-eye rendering, same-command final headset screenshot, reserved readback budget.")
