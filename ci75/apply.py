"""CI75 diagnostic recorder, applied after the verified CI74 jitter repair.
Adds only bounded capture/instrumentation. Does not modify reconstruction shaders.
"""
from pathlib import Path
import os
import re
import shutil
import sys

def replace(path, old, new):
    text=path.read_text(encoding="utf-8")
    if text.count(old)!=1:
        raise RuntimeError(f"CI75 exact anchor drift {path.name}: {old[:90]!r}: count={text.count(old)}")
    path.write_text(text.replace(old,new),encoding="utf-8")

def apply(backend):
    root=Path(backend).resolve();vr=root/"src/mods/vr";ci=Path(__file__).resolve().parent
    shutil.copyfile(ci/"DuoViewCaptureArchive.hpp",vr/"d3d12/DuoViewCaptureArchive.hpp")
    header=(ci/"DuoViewDiagnosticRecorder.hpp").read_text()
    commit=os.environ.get("GITHUB_SHA","UNVERSIONED_LOCAL_BUILD")
    if commit!="UNVERSIONED_LOCAL_BUILD" and not re.fullmatch(r"[0-9a-fA-F]{40}",commit):
        raise RuntimeError("Invalid source build identity")
    (vr/"d3d12/DuoViewDiagnosticRecorder.hpp").write_text(header.replace("@BUILD_COMMIT@",commit))
    h=vr/"D3D12Component.hpp";cpp=vr/"D3D12Component.cpp";ui=root/"src/mods/VR.cpp"
    replace(h,'#include "d3d12/DuoViewDiagnosticDump.hpp"',
        '#include "d3d12/DuoViewDiagnosticDump.hpp"\n#include "d3d12/DuoViewDiagnosticRecorder.hpp"')
    replace(h,"    std::atomic<uint64_t> m_duo_snapshot_start{0};",r'''    std::atomic<uint64_t> m_duo_snapshot_start{0};
    mutable std::mutex m_duo_sequence_mutex;
    std::shared_ptr<uevr::duoview::capture75::Recorder> m_duo_sequence;
    std::atomic<uint64_t> m_duo_sequence_serial{0};''')
    replace(h,r'''    uint64_t duoview_diagnostic_capture_pending() const {
        return m_duo_snapshot_pending.load(std::memory_order_acquire);
    }''',r'''    uint64_t duoview_diagnostic_capture_pending() const {
        return m_duo_snapshot_pending.load(std::memory_order_acquire);
    }
    uint64_t request_duoview_sequence_capture() {
        if(!m_stock_dibr_scope||!m_stock_dibr_depth)return 0;
        std::lock_guard lock(m_duo_sequence_mutex);
        if(m_duo_sequence&&m_duo_sequence->active())return 0;
        const auto id=m_duo_sequence_serial.fetch_add(1)+1;
        m_duo_sequence=std::make_shared<uevr::duoview::capture75::Recorder>(id);
        m_stock_dibr_depth->set_sequence_motion_capture(true);
        return id;
    }
    std::string duoview_sequence_status() const {
        std::lock_guard lock(m_duo_sequence_mutex);
        return m_duo_sequence?m_duo_sequence->status():"No diagnostic sequence";
    }''')
    replace(ui,r'''                    ImGui::Text("Pending capture request: %llu",static_cast<unsigned long long>(m_d3d12.duoview_diagnostic_capture_pending()));''',r'''                    ImGui::Text("Pending capture request: %llu",static_cast<unsigned long long>(m_d3d12.duoview_diagnostic_capture_pending()));
                    ImGui::Separator();
                    if(ImGui::Button("RECORD lossless stereo + depth (2s / 96 frames)")) {
                        const auto id=m_d3d12.request_duoview_sequence_capture();
                        if(id)SPDLOG_INFO("[DuoView][CI75] Armed diagnostic sequence {}",id);
                        else SPDLOG_WARN("[DuoView][CI75] Capture busy or ID6 unavailable");
                    }
                    const auto sequence_status=m_d3d12.duoview_sequence_status();
                    ImGui::TextWrapped("%s",sequence_status.c_str());
                    if(ImGui::SmallButton("Copy diagnostic folder")) {
                        try {const auto folder=(std::filesystem::temp_directory_path()/"UEVR_DuoViewDiagnostics").string();ImGui::SetClipboardText(folder.c_str());}
                        catch(...){SPDLOG_WARN("[DuoView][CI75] Could not resolve diagnostics folder");}
                    }
                    ImGui::TextWrapped("3s countdown: close menu and fix gaze on an unstable edge. Records up to 2s or 96 consecutive genuine frames: native eye/source crops, exact selected depths, synthetic coverage and available NGX motion. Lossless PNG data; all frames retained across numbered ZIPs <=20 MiB each. Upload ALL parts + index from TEMP\\UEVR_DuoViewDiagnostics. Capturing adds overhead; input eye/frame identity remains explicitly unverified.");''')
    # Keep diagnostic NGX color/MV copies alive only for the short session.
    replace(cpp,r'''        if(duoview_interval_owner)
            duoview_interval_owner->finish_frame(m_duo_snapshot_pending.load(std::memory_order_acquire)!=0);''',r'''        std::shared_ptr<uevr::duoview::capture75::Recorder> recorder_retirement;
        {std::lock_guard lock(m_duo_sequence_mutex);recorder_retirement=m_duo_sequence;}
        if(recorder_retirement)recorder_retirement->finish_if_ready();
        if(duoview_interval_owner) {
            duoview_interval_owner->set_sequence_motion_capture(recorder_retirement&&recorder_retirement->wants_guides());
            duoview_interval_owner->finish_frame(m_duo_snapshot_pending.load(std::memory_order_acquire)!=0);
        }''')
    # Expose only motion copied with the SAME selected depth slot/evaluation.
    depth=vr/"d3d12/StockDibrDepth.hpp"
    replace(depth,"    bool snapshot_armed{};","    bool snapshot_armed{};\n    bool sequence_motion_armed{};")
    replace(depth,"    bool diagnostic_capture_armed() const {",r'''    void set_sequence_motion_capture(bool active) {
        std::scoped_lock guard(mutex);sequence_motion_armed=active;
    }
    bool diagnostic_capture_armed() const {''')
    replace(depth,"const bool capture_color=color_ok && same_device(color);",
        "const bool capture_color=snapshot_armed && color_ok && same_device(color);")
    replace(depth,"const bool capture_motion=motion_ok && same_device(mv);",
        "const bool capture_motion=motion_ok && same_device(mv) && (snapshot_armed || (sequence_motion_armed && role_compatible && uint64_t(mw)*mh*8<=16ull*1024*1024));")
    text=depth.read_text()
    begin=text.index("    void capture_ngx_dlss(")
    end=text.index("    void set_legacy_dsv_capture_enabled",begin)
    fn=text[begin:end]
    if fn.count("if(snapshot_armed) {")!=2:raise RuntimeError("CI75 capture payload gate drift")
    fn=fn.replace("if(snapshot_armed) {","if(snapshot_armed || (sequence_motion_armed && role_compatible)) {")
    depth.write_text(text[:begin]+fn+text[end:])
    replace(depth,"        Ptr<ID3D12Resource> left, right;",
        "        Ptr<ID3D12Resource> left, right;\n        std::array<Ptr<ID3D12Resource>,2> selected_motion{};")
    replace(depth,"                    r.left=left.texture;r.right=right.texture;r.ngx_guides={left.ngx_guide,right.ngx_guide};",
        r'''                    r.left=left.texture;r.right=right.texture;r.ngx_guides={left.ngx_guide,right.ngx_guide};
                    if(left.ngx_snapshot_complete)r.selected_motion[0]=left.ngx_motion;
                    if(right.ngx_snapshot_complete)r.selected_motion[1]=right.ngx_motion;''')
    replace(cpp,"                            const std::array<float,4> stereo_quality{",r'''                            std::shared_ptr<uevr::duoview::capture75::Recorder> sequence;
                            {std::lock_guard lock(m_duo_sequence_mutex);sequence=m_duo_sequence;}
                            std::shared_ptr<uevr::duoview::capture75::Frame> sequence_frame;
                            if(sequence) {
                                namespace cap=uevr::duoview::capture75;
                                const auto& l=packet_frame->config.layout;
                                const float gaze_u=(l.u0+l.u1)*.5f,gaze_v=(l.v0+l.v1)*.5f;
                                std::vector<cap::Source> inputs;
                                const auto add=[&](const char* name,ID3D12Resource* resource,
                                        D3D12_RESOURCE_STATES state,cap::Rect active,float u,float v,
                                        unsigned extent,bool required,bool full=false,unsigned height_extent=0) {
                                    cap::Source s;s.name=name;s.resource=resource;s.state=state;s.active=active;
                                    s.u=u;s.v=v;s.extent=extent;s.height_extent=height_extent;s.required=required;s.full=full;inputs.push_back(std::move(s));
                                };
                                add("xr_left",nullptr,D3D12_RESOURCE_STATE_RENDER_TARGET,{},gaze_u,gaze_v,512,true,false,192);
                                add("xr_right",nullptr,D3D12_RESOURCE_STATE_RENDER_TARGET,{},gaze_u,gaze_v,512,true,false,192);
                                add("source_left",m_game_tex.texture.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,{0,0,l.fovea.width,l.fovea.height},.5f,.5f,512,true,false,192);
                                add("source_right",m_scene_capture_tex.texture.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,{0,0,l.periphery.width,l.periphery.height},gaze_u,gaze_v,256,true,false,128);
                                const auto rect=[](const D3D12_VIEWPORT& v){return cap::Rect{UINT(v.TopLeftX),UINT(v.TopLeftY),UINT(v.Width),UINT(v.Height)};};
                                add("depth_left",depths.left.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,rect(depths.left_viewport),.5f,.5f,320,true,false,192);
                                add("depth_right",depths.right.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,rect(depths.right_viewport),gaze_u,gaze_v,192,true,false,128);
                                add("synthetic_right",nullptr,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,{},.5f,.5f,192,false);
                                add("synthetic_left",nullptr,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,{},gaze_u,gaze_v,128,false);
                                for(unsigned eye=0;eye<2;++eye) {
                                    const auto& g=depths.ngx_guides[eye];
                                    const cap::Rect active{0,0,g.motion_low_resolution?g.input_width:g.output_width,
                                        g.motion_low_resolution?g.input_height:g.output_height};
                                    add(eye?"motion_right":"motion_left",g.motion_extent_known?depths.selected_motion[eye].Get():nullptr,
                                        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,active,eye?gaze_u:.5f,eye?gaze_v:.5f,96,false);
                                }
                                add("full_source_left",m_game_tex.texture.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,{0,0,l.fovea.width,l.fovea.height},.5f,.5f,192,false,true);
                                add("full_source_right",m_scene_capture_tex.texture.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,{0,0,l.periphery.width,l.periphery.height},gaze_u,gaze_v,128,false,true);
                                add("full_depth_left",depths.left.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,rect(depths.left_viewport),.5f,.5f,192,false,true);
                                add("full_depth_right",depths.right.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,rect(depths.right_viewport),gaze_u,gaze_v,128,false,true);
                                sequence_frame=sequence->stage(device,std::move(inputs),packet->serial);
                            }
                            bool sequence_recorded=false;
                            const std::array<float,4> stereo_quality{''')
    replace(cpp,r'''                                 capture,&capture_recorded,
                                 left_depth=depths.left''',r'''                                 capture,&capture_recorded,sequence,sequence_frame,&sequence_recorded,
                                 left_depth=depths.left''')
    replace(cpp,"                                    if (compositor.recorded_commands()) commands.has_commands = true;",r'''                                    if(recorded && sequence && sequence_frame) {
                                        sequence_recorded=sequence->record(commands.cmd_list.Get(),sequence_frame,destination,
                                            stereo_recorded&&effective_stereo_mode>=4u?compositor.surface_color(0):nullptr,
                                            stereo_recorded&&effective_stereo_mode>=5u?compositor.surface_color(1):nullptr);
                                        if(sequence_recorded)commands.has_commands=true;
                                    }
                                    if (compositor.recorded_commands()) commands.has_commands = true;''')
    replace(cpp,r'''                            if (capture && capture_recorded &&
                                d3d12::dibr_transaction::commands_were_submitted(capture_submission)) {''',r'''                            if(sequence && sequence_frame) {
                                namespace cap=uevr::duoview::capture75;
                                std::ostringstream meta;meta<<std::setprecision(17);
                                const auto arr=[&](const auto& a){meta<<"[";bool first=true;for(const auto& v:a){if(!first)meta<<",";first=false;if(std::isfinite(double(v)))meta<<v;else meta<<"null";}meta<<"]";};
                                const auto& l=packet_frame->config.layout;
                                meta<<"{\"ue_frame\":"<<packet_frame->config.key.frame<<",\"source_frame\":"<<*packet_source
                                    <<",\"generation\":"<<packet_frame->config.key.generation
                                    <<",\"mode\":"<<effective_stereo_mode<<",\"requested_mode\":"<<stereo_mode
                                    <<",\"strategy\":"<<cap::quote(stereo_quality[3]>=7.5f?"CI73_CONSERVATIVE_CI74_JITTER_FIX":stereo_quality[3]>3.5f?"CI72_RIGHT_GATHER":stereo_quality[3]>1.5f?"CI71_LEFT_MESH":"LEGACY")
                                    <<",\"world_to_meters\":"<<cap::number(vr->get_world_to_meters())<<",\"world_scale\":"<<cap::number(vr->get_world_scale())
                                    <<",\"jitter_units\":\"NGX_input_pixels_raw_sign\",\"depth_space\":\"device_Z\""
                                    <<",\"stereo_sign\":"<<stereo_sign<<",\"fovea_view\":"<<packet_frame->config.settings.fovea_view
                                    <<",\"stereo_recorded\":"<<(stereo_recorded?"true":"false")
                                    <<",\"xr_copy_submitted\":"<<(submitted?"true":"false")
                                    <<",\"depth_identity_authenticated\":false,\"crop\":["<<l.u0<<","<<l.v0<<","<<l.u1<<","<<l.v1<<"]"
                                    <<",\"depth_serials\":["<<depths.left_serial<<","<<depths.right_serial<<"]"
                                    <<",\"depth_epochs\":["<<depths.left_epoch<<","<<depths.right_epoch<<"]"
                                    <<",\"depth_selection\":"<<cap::quote(depths.decision)<<",\"quality\":";arr(stereo_quality);
                                meta<<",\"positions\":[";arr(packet_frame->eye_cameras[0].position);meta<<",";arr(packet_frame->eye_cameras[1].position);meta<<"]";
                                meta<<",\"rotations\":[";arr(packet_frame->eye_cameras[0].rotation);meta<<",";arr(packet_frame->eye_cameras[1].rotation);meta<<"]";
                                meta<<",\"projection_left\":";arr(packet_frame->projection);
                                meta<<",\"projection_right\":";arr(packet_frame->projection_right);
                                meta<<",\"matrix_layout\":\"column_major_unjittered_frozen_color_not_authenticated_depth_pass\""
                                    <<",\"depth_viewports\":[";
                                const auto viewport=[&](const D3D12_VIEWPORT& v){meta<<"["<<v.TopLeftX<<","<<v.TopLeftY<<","<<v.Width<<","<<v.Height<<","<<v.MinDepth<<","<<v.MaxDepth<<"]";};
                                viewport(depths.left_viewport);meta<<",";viewport(depths.right_viewport);meta<<"],\"guides\":[";
                                for(unsigned eye=0;eye<2;++eye) {
                                    if(eye)meta<<",";const auto& g=depths.ngx_guides[eye];
                                    meta<<"{\"feature\":"<<g.feature<<",\"feature_generation\":"<<g.feature_generation<<",\"evaluation\":"<<g.evaluation
                                        <<",\"role\":"<<g.role<<",\"manual\":"<<(g.manual_source?"true":"false")
                                        <<",\"input\":["<<g.input_width<<","<<g.input_height<<"],\"output\":["<<g.output_width<<","<<g.output_height<<"]"
                                        <<",\"depth_base\":["<<g.depth_x<<","<<g.depth_y<<"],\"motion_base\":["<<g.motion_x<<","<<g.motion_y<<"]"
                                        <<",\"jitter\":["<<cap::number(g.jitter_x)<<","<<cap::number(g.jitter_y)<<"],\"motion_scale\":["<<cap::number(g.motion_scale_x)<<","<<cap::number(g.motion_scale_y)<<"]"
                                        <<",\"flags\":"<<g.flags<<",\"flags_known\":"<<(g.flags_known?"true":"false")
                                        <<",\"reset\":"<<g.reset<<",\"motion_low_resolution\":"<<(g.motion_low_resolution?"true":"false")
                                        <<",\"motion_extent_known\":"<<(g.motion_extent_known?"true":"false")<<"}";
                                }
                                meta<<"]}";
                                sequence->submit(sequence_frame,g_framework->get_d3d12_hook()->get_command_queue(),
                                    d3d12::dibr_transaction::commands_were_submitted(capture_submission),
                                    submitted&&sequence_recorded,packet->serial,meta.str());
                            }
                            if (capture && capture_recorded &&
                                d3d12::dibr_transaction::commands_were_submitted(capture_submission)) {''')
    print("CI75 recorder integrated after CI74: lossless depth/color sequence and metadata; reconstruction unchanged")

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: ci75/apply.py BACKEND")
    apply(sys.argv[1])
