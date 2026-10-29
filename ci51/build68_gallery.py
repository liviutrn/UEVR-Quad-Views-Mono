from pathlib import Path
import sys
def patch(file,old,new):
    p=Path(file);s=p.read_text(encoding="utf-8")
    if new in s:return
    if s.count(old)!=1:raise RuntimeError("CI68 source mismatch: "+str(p)+" "+old[:60])
    p.write_text(s.replace(old,new,1),encoding="utf-8")
def apply(root):
    v=Path(root)/"src/mods/vr"
    d=v/"d3d12/StockDibrDepth.hpp"
    patch(d,"snapshot_candidates(uint64_t selected_left_serial=0,uint64_t selected_right_serial=0) {",
            "snapshot_candidates(uint64_t selected_left_serial=0,uint64_t selected_right_serial=0,bool manual_gallery=false) {")
    patch(d,"if(ngx_depth_requested() && duoview_source_sizes[0] &&\n           (!selected_left_serial || !selected_right_serial)) return result;",
            "if(!manual_gallery && ngx_depth_requested() && duoview_source_sizes[0] &&\n           (!selected_left_serial || !selected_right_serial)) return result;")
    patch(d,"if(ngx_depth_requested() && selected_left_serial && selected_right_serial &&\n               s.serial!=selected_left_serial && s.serial!=selected_right_serial)continue;",
            "if(!manual_gallery && ngx_depth_requested() && selected_left_serial && selected_right_serial &&\n               s.serial!=selected_left_serial && s.serial!=selected_right_serial)continue;")
    patch(d,"uint64_t color_packet=0,uint64_t color_generation=0) {",
            "uint64_t color_packet=0,uint64_t color_generation=0,bool manual_visual_preview=false) {")
    patch(d,"if(ngx_depth_requested()) {\n            size_t l=Capacity,rr=Capacity;",
            "if(ngx_depth_requested() && !manual_visual_preview) {\n            size_t l=Capacity,rr=Capacity;")
    h=v/"D3D12Component.hpp"
    patch(h,"std::atomic<uint64_t> m_duo_snapshot_pending{0};",
            "std::atomic<uint64_t> m_duo_snapshot_pending{0};\n    std::atomic<uint64_t> m_duo_gallery_request{0};")
    patch(h,"    uint64_t duoview_diagnostic_capture_pending() const {",'''    uint64_t request_duoview_gallery_capture() {
        if(!m_stock_dibr_scope)return 0;
        uint64_t expected=0;
        const auto id=m_duo_snapshot_serial.fetch_add(1,std::memory_order_relaxed)+1;
        m_duo_gallery_request.store(id,std::memory_order_release);
        if(!m_duo_snapshot_pending.compare_exchange_strong(expected,id,std::memory_order_acq_rel)) {
            m_duo_gallery_request.store(0,std::memory_order_release);return 0;
        }
        m_stock_dibr_depth->arm_diagnostic_capture();
        return id;
    }
    uint64_t duoview_diagnostic_capture_pending() const {''')
    c=v/"D3D12Component.cpp"
    patch(c,"const uint64_t capture_id=m_duo_snapshot_pending.load(std::memory_order_acquire);",
            "const uint64_t capture_id=m_duo_snapshot_pending.load(std::memory_order_acquire);\n                            const bool gallery_capture=capture_id!=0 && m_duo_gallery_request.load(std::memory_order_acquire)==capture_id;")
    patch(c,"stereo_mode<4u,packet->serial,packet_frame->config.key.generation);",
            "stereo_mode<4u,packet->serial,packet_frame->config.key.generation,\n                                    preview_mode!=0 && stereo_mode==0);")
    patch(c,"snapshot_candidates(depths.left_serial,depths.right_serial);",
            "snapshot_candidates(depths.left_serial,depths.right_serial,gallery_capture);")
    patch(c,"true,stock_dibr::ngx::Observer::requested())) {",
            "true,!gallery_capture && stock_dibr::ngx::Observer::requested())) {")
    patch(c,"m_duo_snapshot_pending.compare_exchange_strong(\n                                        expected,0,std::memory_order_acq_rel);\n                                    SPDLOG_INFO",
            "m_duo_snapshot_pending.compare_exchange_strong(\n                                        expected,0,std::memory_order_acq_rel);\n                                    if(gallery_capture)m_duo_gallery_request.store(0,std::memory_order_release);\n                                    SPDLOG_INFO")
    ui=Path(root)/"src/mods/VR.cpp"
    anchor='                    if (ImGui::Button("Capture now: DLSS guides and stereo output")) {'
    patch(ui,anchor,'''                    ImGui::Separator();
                    ImGui::TextUnformatted("MANUAL DEPTH VIEWER — independent of NGX");
                    ImGui::TextWrapped("Enable the DSV/RDG observer. Capture all eligible DSV depth candidates as BMP previews and inspect with the matching LEFT/RIGHT color. Pin using the observed DSV source and pass fingerprint; serials/numbered entries can change.");
                    if(ImGui::Button("Capture DSV candidate gallery (no NGX pair required)")) {
                        const auto id=m_d3d12.request_duoview_gallery_capture();
                        if(id)SPDLOG_INFO("[DuoView][Gallery] requested #{}",id);
                        else SPDLOG_WARN("[DuoView][Gallery] Busy or depth observer inactive");
                    }
                    ImGui::TextWrapped("Capture output: Windows TEMP\\\\UEVR_DuoViewCaptures\\\\capture_N; open the depth_preview.bmp files. Depth preview works when stereo is OFF. A visual pin does not authenticate an eye or enable unverified stereo.");
'''+anchor)
    patch(ui,'''if(ImGui::Combo("Display depth preview",&preview_mode,preview_labels,4))
                        m_d3d12.duoview_select_candidates(0,0,uint32_t(preview_mode));''',
'''if(ImGui::Combo("Display depth preview",&preview_mode,preview_labels,4)) {
                        m_d3d12.duoview_select_candidates(0,0,uint32_t(preview_mode));
                        if(preview_mode!=0)m_d3d12.duoview_stereo_config(0,false);
                    }
                    ImGui::TextWrapped("Visualize pinned DSV candidates with stereo OFF; true stereo remains NGX-guarded.");''')
    print("CI68 manual DSV gallery and depth-preview isolation applied")
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: build68_gallery.py BACKEND_ROOT")
    apply(sys.argv[1])
