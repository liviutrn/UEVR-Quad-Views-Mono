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
edit(header,'    std::atomic<uint64_t> m_duo_stereo_reject_frames{0};',
'''    std::atomic<uint64_t> m_duo_stereo_reject_frames{0};
    std::atomic<uint32_t> m_duo_stereo_output{0};''',"requested versus submitted output state")
edit(header,'    int duoview_left_choice() const {return m_duo_left_choice.load();}',
'''    uint32_t duoview_stereo_mode() const {return m_duo_stereo_mode.load();}
    bool duoview_stereo_reverse() const {return m_duo_stereo_reverse.load();}
    uint64_t duoview_stereo_frames() const {return m_duo_stereo_frames.load();}
    uint64_t duoview_stereo_recorded_frames() const {return m_duo_stereo_recorded_frames.load();}
    uint64_t duoview_stereo_rejected_frames() const {return m_duo_stereo_reject_frames.load();}
    const char* duoview_stereo_output_status() const {
        switch(m_duo_stereo_output.load()) {
        case 1:return "EXPERIMENTAL STEREO copy submitted (source identity UNVERIFIED)";
        case 2:return "WAITING / REJECTED stereo: V3 mono copied; depth/config details in log";
        case 3:return "XR copy not submitted; prior displayed output is not measured";
        default:return "V3 mode 0 mono copy";
        }
    }
    void duoview_stereo_config(uint32_t mode,bool reverse) {
        m_duo_stereo_mode.store((std::min)(mode,3u),std::memory_order_release);
        m_duo_stereo_reverse.store(reverse,std::memory_order_release);
    }
    int duoview_left_choice() const {return m_duo_left_choice.load();}''',"UI public getters")
vr="src/mods/VR.cpp"
edit(vr,'                    const int n=m_d3d12.duoview_depth_candidate_count();',
'''                    int stereo_mode=int(m_d3d12.duoview_stereo_mode());
                    bool stereo_reverse=m_d3d12.duoview_stereo_reverse();
                    bool mode_changed=false;
                    mode_changed|=ImGui::SliderInt("TRUE STEREO (0 V3 / 1 stereo / 2 tint / 3 fovea only)",&stereo_mode,0,3);
                    mode_changed|=ImGui::Checkbox("Reverse stereo parallax sign (A/B)",&stereo_reverse);
                    if(mode_changed)m_d3d12.duoview_stereo_config(uint32_t(stereo_mode),stereo_reverse);
                    ImGui::Text("Experimental stereo XR copies submitted: %llu | rejected: %llu",
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_frames()),
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_rejected_frames()));
                    ImGui::Text("Stereo commands recorded: %llu (not headset delivery)",
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_recorded_frames()));
                    ImGui::TextWrapped("Last copy: %s",m_d3d12.duoview_stereo_output_status());
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
                            }
                            const uint32_t effective_stereo_mode=depths.left && depths.right &&
                                packet_frame->split_eye && packet_frame->config.settings.fovea_view==0
                                    ? stereo_mode : 0u;''',"remove invalid spdlog macro and acquire real stereo depth")
edit(dc,'''                                info << " previewMode=" << preview_mode''',
'''                                info << " stereoMode=" << stereo_mode
                                     << " effectiveStereoMode=" << effective_stereo_mode
                                     << " stereoReversed=" << (stereo_sign<0)
                                     << " stereoCopiesSubmitted=" << m_duo_stereo_frames.load()
                                     << " stereoCommandsRecorded=" << m_duo_stereo_recorded_frames.load()
                                     << " sourceRoleVerified=false sourceFrameVerified=false sourceStageVerified=false"
                                     << " trueStereoRejected=" << m_duo_stereo_reject_frames.load();
                                info << " previewMode=" << preview_mode''',"record replay metadata")
edit(dc,'''                                 left_depth=depths.left,right_depth=depths.right,preview_mode](''',
'''                                 left_depth=depths.left,right_depth=depths.right,preview_mode,
                                 stereo_mode,effective_stereo_mode,stereo_sign,&stereo_recorded,
                                 left_viewport=depths.left_viewport,right_viewport=depths.right_viewport](''',"XR callback locks stereo policy")
edit(dc,'''                                        left_depth.Get(),right_depth.Get(),preview_mode);''',
'''                                        left_depth.Get(),right_depth.Get(),stereo_mode ? 0u : preview_mode,
                                        effective_stereo_mode,stereo_sign,
                                        {left_viewport.TopLeftX,left_viewport.TopLeftY,left_viewport.Width,left_viewport.Height,left_viewport.MinDepth,left_viewport.MaxDepth},
                                        {right_viewport.TopLeftX,right_viewport.TopLeftY,right_viewport.Width,right_viewport.Height,right_viewport.MinDepth,right_viewport.MaxDepth});
                                    stereo_recorded=recorded && compositor.last_true_stereo();
                                    if(!recorded && stereo_mode && !compositor.recorded_commands()) {
                                        SPDLOG_WARNING_EVERY_N_SEC(2,"[DuoView][StereoXR] Stereo rejected; rendering V3 mono without disabling two-view capture: {}",compositor.error());
                                        recorded=compositor.record_native(device,commands.cmd_list.Get(),
                                            source.Get(),secondary.Get(),destination,
                                            D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                                            *packet_frame,std::static_pointer_cast<const void>(packet),0);
                                    }
                                    if(stereo_mode) {
                                        if(stereo_recorded)
                                            m_duo_stereo_recorded_frames.fetch_add(1,std::memory_order_relaxed);
                                    }''',"stereo GPU recording counter, not delivery")
edit(dc,'''                            if (submitted && recorded && callback_attempted) {
                                native_stereo_hook->duoview_delivery.result''',
'''                            // One outcome per copy attempt. OpenXR::copy returns true
                            // only after checked queue enqueue and successful image release.
                            // This is NOT proof of xrEndFrame or physical display.
                            if(stereo_mode) {
                                if(submitted && stereo_recorded && callback_attempted)
                                    m_duo_stereo_frames.fetch_add(1,std::memory_order_relaxed);
                                else m_duo_stereo_reject_frames.fetch_add(1,std::memory_order_relaxed);
                            }
                            m_duo_stereo_output.store(!submitted || !recorded ? 3u :
                                stereo_recorded ? 1u : stereo_mode ? 2u : 0u,std::memory_order_release);
                            if (submitted && recorded && callback_attempted) {
                                native_stereo_hook->duoview_delivery.result''',"post-copy submitted accounting")
edit(dc,'''                            bool capture_recorded=false;''',
'''                            bool capture_recorded=false;
                            bool stereo_recorded=false;
                            auto capture_submission=d3d12::dibr_transaction::ExecuteResult::NoWork;''',"capture queue outcome starts unsubmitted")
edit(dc,'''                    if (vr->is_duoview_renderer_active()) {
                        const auto packet = native_stereo_packet;''',
'''                    if (vr->is_duoview_renderer_active()) {
                        // A prior successful copy must not describe a missing current pair.
                        m_duo_stereo_output.store(3u,std::memory_order_release);
                        const auto packet = native_stereo_packet;''',"clear actual output before validating current color packet")
edit(dc,'''                                std::nullopt, m_game_tex.texture.Get());
                            // One outcome per copy attempt.''',
'''                                std::nullopt, m_game_tex.texture.Get(),{},
                                [&capture_submission](d3d12::CommandContext&,
                                    d3d12::dibr_transaction::ExecuteResult result) {
                                    capture_submission=result;
                                });
                            // One outcome per copy attempt.''',"observe checked enqueue before snapshot worker")
edit(dc,'''                            if (capture && capture_recorded) {''',
'''                            if (capture && capture_recorded &&
                                d3d12::dibr_transaction::commands_were_submitted(capture_submission)) {
                                capture->note_submission(submitted,static_cast<unsigned>(capture_submission),stereo_recorded);''',"never save unexecuted readback commands")
edit(dc,'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode)
                                    m_stock_dibr_depth->finish_frame();''',
'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode || stereo_mode)
                                    m_stock_dibr_depth->finish_frame();''',"depth GPU consumer retirement")
# The stock cleanup used to erase ALL candidates before DuoView selected
# them. Extend the EXISTING tail guard (no extra per-frame guard allocation).
edit(dc,'    if (m_stock_dibr_scope) m_stock_dibr_depth->finish_frame();',
'''    const bool duoview_depth_interval=vr->is_duoview_renderer_active();
    if(m_stock_dibr_scope && !duoview_depth_interval) {
        m_stock_dibr_depth->finish_frame();
    }
    const auto duoview_interval_owner=duoview_depth_interval && m_stock_dibr_scope
        ? m_stock_dibr_depth : nullptr;''',"skip stock early retirement for DuoView only")
edit(dc,'    const auto dibr_preview_succeeded = vr->is_dibr_preview_active() &&',
'''    if(m_stock_dibr_scope && !vr->is_duoview_renderer_active())
        m_stock_dibr_depth->configure_duoview_sources(0,0,0,0);
    const auto dibr_preview_succeeded = vr->is_dibr_preview_active() &&''',"stock DIBR restores its original discovery policy before acquiring")
edit(dc,'''    utility::ScopeGuard dibr_consumer_retirement{[&]() {
        if (!dibr_preview_succeeded''',
'''    utility::ScopeGuard dibr_consumer_retirement{[&]() {
        if(duoview_interval_owner)
            duoview_interval_owner->finish_frame(m_duo_snapshot_pending.load(std::memory_order_acquire)!=0);
        if (!dibr_preview_succeeded''',"single tail retirement follows all DuoView consumers")
edit(dc,'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode || stereo_mode)
                                    m_stock_dibr_depth->finish_frame();''',
'''                                // Existing tail guard owns the one DuoView epoch advance.''',"remove duplicate DuoView retirement")
depth_header="src/mods/vr/d3d12/StockDibrDepth.hpp"
edit(depth_header,'    void finish_frame() {','    void finish_frame(bool keep_snapshot_armed=false) {',"preserve requested snapshot through depth warmup")
edit(depth_header,'        snapshot_armed=false;','        snapshot_armed=keep_snapshot_armed;',"capture remains armed until valid snapshot enqueues")
edit(dc,'#include "D3D12Component.hpp"','#include "D3D12Component.hpp"\n#include <iomanip>',"precise camera capture metadata")
edit(dc,'                                info << "packet=" << packet->serial',
'''                                info << std::setprecision(17);
                                info << "packet=" << packet->serial''',"preserve double precision in camera metadata")
edit(dc,'''                                info << " crop=(" << packet_frame->config.layout.u0''',
'''                                info << " LEFTrotation=("<<left.rotation[0]<<","<<left.rotation[1]<<","<<left.rotation[2]
                                     <<") RIGHTrotation=("<<right.rotation[0]<<","<<right.rotation[1]<<","<<right.rotation[2]<<")";
                                info << " frozenSourceProjection_NOT_depthPassVerified_L=[";
                                for(size_t k=0;k<16;++k)info<<(k?",":"")<<packet_frame->projection[k];
                                info << "] frozenSourceProjection_NOT_depthPassVerified_R=[";
                                for(size_t k=0;k<16;++k)info<<(k?",":"")<<packet_frame->projection_right[k];
                                const auto& active=packet_frame->config.layout;
                                info << "] colorActiveRects=L:(0,0,"<<active.fovea.width<<","<<active.fovea.height
                                     <<") R:(0,0,"<<active.periphery.width<<","<<active.periphery.height<<")";
                                info << " crop=(" << packet_frame->config.layout.u0''',"record frozen geometry without inventing depth-pass calibration")
# The OpenXR destination pointer exists ONLY inside the frame-copy callback.
# Reserve 128 MiB of one-shot readback budget for the FINAL stereo output,
# then attach the actual destination after compositor.record_native completed.
# No readback occurs on ordinary frames; a one-shot readback allocation in the
# XR callback is preferable to capturing the wrong/null resource.
dump="src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp"
edit(dump,'''    UINT64 total_bytes_{};''',
'''    UINT64 total_bytes_{};
    bool reserve_headset_output_{};
    bool require_complete_snapshot_{};
    bool final_output_attached_{};''',"one-shot final XR reservation")
edit(dump,'''           total_bytes_+bytes>MaxBytes) {''',
'''           total_bytes_+bytes>MaxBytes-(reserve_headset_output_ ? 128ull*1024*1024 : 0ull)) {''',
"reserve readback space for doublewide OpenXR image")
edit(dump,'''           const std::vector<Candidate>& depths) {
        add_image(dev,left,''',
'''           const std::vector<Candidate>& depths,
           bool reserveHeadsetOutput=false) {
        reserve_headset_output_=reserveHeadsetOutput;
        require_complete_snapshot_=reserveHeadsetOutput;
        add_image(dev,left,''',"reserve output before raw depth captures")
edit(dump,'''        return images_.size()>=2; // do not alter the original XR output if some depth allocations fail''',
'''        const bool left_ready=std::any_of(images_.begin(),images_.end(),
            [](const Image& i){return i.label=="left_fovea";});
        const bool right_ready=std::any_of(images_.begin(),images_.end(),
            [](const Image& i){return i.label=="right_periphery";});
        const bool depth_ready=std::any_of(images_.begin(),images_.end(),
            [](const Image& i){return i.depth;});
        return left_ready && right_ready && (!require_complete_snapshot_ || depth_ready);''',
"complete diagnostic needs actual allocated colors and depth, not candidate count")
edit(dump,'''    bool record(ID3D12GraphicsCommandList* cmd) {''',
'''    void note_submission(bool xrCopyReleased,unsigned outcome,bool stereoRecorded) {
        metadata_+=" readbackCommandsEnqueued=true xrCopyReleased=";
        metadata_+=xrCopyReleased ? "true" : "false";
        metadata_+=" executeOutcome="+std::to_string(outcome);
        metadata_+=" actualStereoRecorded=";metadata_+=stereoRecorded ? "true" : "false";
        metadata_+=" headsetPresentationVerified=false";
    }
    bool attach_headset_output(ID3D12Device* dev,ID3D12Resource* destination) {
        if(final_output_attached_)return true;
        reserve_headset_output_=false;
        // GPU copy occurs only after actual stereo pixel shader has drawn.
        // The R5 sources and final headset target share the same OpenXR
        // command-list and fence, so the manifest describes ONE frame.
        if(!add_image(dev,destination,D3D12_RESOURCE_STATE_RENDER_TARGET,
                         "xr_submitted_doublewide",false,
                         "FINAL headset image. LEFT x=0..W-1, RIGHT x=W..2W-1; same copy command as source color and depth."))return false;
        final_output_attached_=true;
        return true;
    }
    bool record(ID3D12GraphicsCommandList* cmd) {''',
"one-shot XR destination allocation inside callback")
edit(dump,'''        if(!cmd||recorded_||images_.empty())return false;''',
'''        if(!cmd||recorded_||images_.empty() ||
           (require_complete_snapshot_ && !final_output_attached_))return false;''',
"never record a complete XR snapshot whose final image allocation failed")
edit(dc,'''                                    m_scene_capture_tex.texture.Get(),candidates)) capture.reset();''',
'''                                    m_scene_capture_tex.texture.Get(),candidates,
                                    true)) capture.reset();''',"reserve final XR capture without undeclared destination")
edit(dc,'''                                if(!capture->prepare(device,m_game_tex.texture.Get(),''',
'''                                if(candidates.empty() || !capture->prepare(device,m_game_tex.texture.Get(),''',"no misleading color-only snapshot when depth is still missing")
edit(dc,'''                                    true)) capture.reset();''',
'''                                    true)) {
                                    SPDLOG_WARNING_EVERY_N_SEC(2,"[DuoView][Capture] Request #{} remains pending: eligibleDepths={}; required color/depth readback preparation incomplete (format/allocation/session budget)",capture_id,candidates.size());
                                    capture.reset();
                                }''',"pending capture has an explicit diagnostic reason")
edit(dc,'''                                    if (recorded && capture) {
                                        // Sources have been restored to their native RT states''',
'''                                    if (recorded && capture) {
                                        // XR destination exists only in the copy callback.
                                        // Capture the FINAL separately composed two-eye image.
                                        // Sources have been restored to their native RT states''',
"bind real final XR destination after successful stereo recording")
edit(dc,'''                                        if(capture->record(commands.cmd_list.Get())) {''',
'''                                        if(capture->attach_headset_output(device,destination) &&
                                           capture->record(commands.cmd_list.Get())) {''',
"final readback allocation must succeed before recording the session")
print("TRUE XR STEREO: actual two-eye rendering, same-command final headset screenshot, reserved readback budget.")
