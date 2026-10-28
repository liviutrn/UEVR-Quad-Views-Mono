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
    // Experimental headset build defaults to actual stereo; disable for V3 A/B.
    std::atomic<uint32_t> m_duo_stereo_mode{1};
    std::atomic<bool> m_duo_stereo_reverse{false};
    std::atomic<uint64_t> m_duo_stereo_frames{0};
    std::atomic<uint64_t> m_duo_stereo_reject_frames{0};''',"stereo controls")
edit(header,'    int duoview_left_choice() const {return m_duo_left_choice.load();}',
'''    uint32_t duoview_stereo_mode() const {return m_duo_stereo_mode.load();}
    bool duoview_stereo_reverse() const {return m_duo_stereo_reverse.load();}
    uint64_t duoview_stereo_frames() const {return m_duo_stereo_frames.load();}
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
                    ImGui::Text("TRUE STEREO COMPOSITES DELIVERED: %llu | rejected: %llu",
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_frames()),
                        static_cast<unsigned long long>(m_d3d12.duoview_stereo_rejected_frames()));
                    ImGui::TextWrapped("Stereo ON forces direct per-eye XR raster. Candidate errors are visible; test alternate LEFT/RIGHT depth selectors. Tint proof must appear ONLY in RIGHT headset eye.");
                    const int n=m_d3d12.duoview_depth_candidate_count();''',"mode UI")
dc="src/mods/vr/D3D12Component.cpp"
edit(dc,'''                            const uint32_t preview_mode=m_duo_preview_mode.load(std::memory_order_acquire);
                            stock_dibr::DepthCapture::PreviewPair depths{};
                            if(m_stock_dibr_scope && preview_mode) {
                                depths=m_stock_dibr_depth->select_preview(m_duo_left_choice.load(),m_duo_right_choice.load());
                            }
                            if(preview_mode && (!depths.left||!depths.right))
                                SPDLOG_WARN_EVERY_N_SEC(2,"[DuoView][Preview] Candidate pair unavailable; use manual sliders and capture ZIP");''',
'''                            const uint32_t preview_mode=m_duo_preview_mode.load(std::memory_order_acquire);
                            const uint32_t stereo_mode=m_duo_stereo_mode.load(std::memory_order_acquire);
                            const float stereo_sign=m_duo_stereo_reverse.load(std::memory_order_acquire)?-1.0f:1.0f;
                            stock_dibr::DepthCapture::PreviewPair depths{};
                            if(m_stock_dibr_scope && (preview_mode || stereo_mode)) {
                                depths=m_stock_dibr_depth->select_preview(m_duo_left_choice.load(),m_duo_right_choice.load());
                            }
                            if((preview_mode||stereo_mode) && (!depths.left||!depths.right)) {
                                static uint64_t last_missing_warn=0;
                                const auto now=GetTickCount64();
                                if(now-last_missing_warn>2000) {
                                    last_missing_warn=now;
                                    SPDLOG_WARN("[DuoView][StereoXR] No submitted depth pair yet. Select another LEFT or RIGHT candidate, or re-enter ID6.");
                                }
                                if(stereo_mode)m_duo_stereo_reject_frames.fetch_add(1,std::memory_order_relaxed);
                            }''',"remove invalid spdlog macro and acquire real stereo depth")
edit(dc,'''                                info << " previewMode=" << preview_mode''',
'''                                info << " stereoMode=" << stereo_mode
                                     << " stereoReversed=" << (stereo_sign<0)
                                     << " trueStereoDelivered=" << m_duo_stereo_frames.load()
                                     << " trueStereoRejected=" << m_duo_stereo_reject_frames.load();
                                info << " previewMode=" << preview_mode''',"record replay metadata")
edit(dc,'''                                 left_depth=depths.left,right_depth=depths.right,preview_mode](''',
'''                                 left_depth=depths.left,right_depth=depths.right,preview_mode,
                                 stereo_mode,stereo_sign](''',"XR callback locks stereo policy")
edit(dc,'''                                        left_depth.Get(),right_depth.Get(),preview_mode);''',
'''                                        left_depth.Get(),right_depth.Get(),preview_mode,
                                        stereo_mode,stereo_sign);
                                    if(stereo_mode) {
                                        if(recorded && compositor.last_true_stereo())
                                            m_duo_stereo_frames.fetch_add(1,std::memory_order_relaxed);
                                        else
                                            m_duo_stereo_reject_frames.fetch_add(1,std::memory_order_relaxed);
                                    }''',"stereo GPU submission counter")
edit(dc,'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode)
                                    m_stock_dibr_depth->finish_frame();''',
'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode || stereo_mode)
                                    m_stock_dibr_depth->finish_frame();''',"depth GPU consumer retirement")
# Add final stereo XR output image to one-shot captures, BEFORE depth candidates
# consume the 512MB readback budget. Never alter XR destination image content.
dump="src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp"
edit(dump,'''           const std::vector<Candidate>& depths) {''',
'''           const std::vector<Candidate>& depths,
           ID3D12Resource* headsetOutput=nullptr) {''',"XR capture argument")
edit(dump,'''        add_image(dev,right,D3D12_RESOURCE_STATE_RENDER_TARGET,"right_periphery",false,"UE1 split-right color; allocation (may include inactive pixels)");
        size_t n=0;''',
'''        add_image(dev,right,D3D12_RESOURCE_STATE_RENDER_TARGET,"right_periphery",false,"UE1 split-right color; allocation (may include inactive pixels)");
        if(headsetOutput)
            add_image(dev,headsetOutput,D3D12_RESOURCE_STATE_RENDER_TARGET,
                      "xr_submitted_doublewide",false,
                      "FINAL headset image. LEFT half x=0..W-1; RIGHT half x=W..2W-1. Compare both eyes on one raw image.");
        size_t n=0;''',"XR final stereo screenshot")
edit(dc,'''                                    m_scene_capture_tex.texture.Get(),candidates)) capture.reset();''',
'''                                    m_scene_capture_tex.texture.Get(),candidates,
                                    destination)) capture.reset();''',"capture final destination")
print("TRUE XR STEREO: pinned actual UE split-eye sources; candidate controls; direct eye output and stereo readback capture patched.")
