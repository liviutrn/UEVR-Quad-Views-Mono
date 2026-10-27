#!/usr/bin/env python3
"""Diagnostic live depth candidate browser for DuoView ID6, applied after add_manual_capture.py."""
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit("usage: attach_depth_probe.py <patched backend>")
root=Path(sys.argv[1])
def edit(path, old, new, name):
    target=root/path
    code=target.read_text(encoding="utf-8-sig")
    if code.count(old)!=1: raise RuntimeError(f"DepthProbe {name}: expected one anchor, got {code.count(old)}")
    target.write_text(code.replace(old,new,1),encoding="utf-8",newline="")

depth="src/mods/vr/d3d12/StockDibrDepth.hpp"
probe=r'''    struct PreviewPair {
        Ptr<ID3D12Resource> left, right;
        std::string label;
        size_t count{};
    };
    std::vector<size_t> preview_indices() const {
        std::unordered_map<std::uintptr_t,size_t> unique;
        for(size_t i=0;i<slots.size();++i) {
            const auto& s=slots[i];
            if(!s.texture || !s.source || s.epoch!=epoch || s.pending ||
               s.leased || s.quarantined || (!s.fence && !s.foreign_fence)) continue;
            const auto key=reinterpret_cast<std::uintptr_t>(s.source.Get());
            auto it=unique.find(key);
            if(it==unique.end() || slots[it->second].serial<s.serial) unique[key]=i;
        }
        std::vector<std::pair<std::uintptr_t,size_t>> order(unique.begin(),unique.end());
        std::sort(order.begin(),order.end(),[](const auto& a,const auto& b){return a.first<b.first;});
        std::vector<size_t> out;
        for(const auto& x:order)out.push_back(x.second);
        return out;
    }
    size_t preview_count() const {
        std::scoped_lock lock{mutex};
        return preview_indices().size();
    }
    std::string preview_inventory() const {
        std::scoped_lock lock{mutex};
        std::ostringstream out;
        const auto indices=preview_indices();
        out<<"GPU-submitted eligible candidates: "<<indices.size()
           <<"; ordinals sorted by DSV resource identity (may change on reload)";
        for(size_t k=0;k<indices.size()&&k<16;++k) {
            const auto& s=slots[indices[k]];
            const auto d=s.texture->GetDesc();
            out<<"\n"<<k+1<<": DSV=0x"<<std::hex
               <<reinterpret_cast<std::uintptr_t>(s.source.Get())<<std::dec
               <<" serial="<<s.serial<<" epoch="<<s.epoch
               <<" size="<<d.Width<<"x"<<d.Height
               <<" viewport="<<s.viewport.Width<<"x"<<s.viewport.Height
               <<" fmt="<<static_cast<unsigned>(d.Format)<<" eye=UNVERIFIED";
        }
        return out.str();
    }
    PreviewPair select_preview(int left_selector,int right_selector) {
        std::scoped_lock lock{mutex};
        PreviewPair r{};
        if(!enabled)return r;
        const auto ids=preview_indices();
        r.count=ids.size();
        if(ids.empty())return r;
        const size_t invalid=slots.size();
        const auto choose=[&](int manual,size_t other)->size_t {
            if(manual>0&&static_cast<size_t>(manual)<=ids.size())return ids[manual-1];
            size_t best=ids[0];double score=-1;
            for(const auto i:ids) {
                if(i==other && ids.size()>1)continue;
                const auto& v=slots[i].viewport;
                const double area=double(v.Width)*double(v.Height);
                if(area>score){best=i;score=area;}
            }
            return best;
        };
        const size_t a=choose(left_selector,invalid);
        const size_t b=choose(right_selector,a);
        auto lease=[&](size_t i)->Ptr<ID3D12Resource> {
            auto& s=slots[i];
            if(s.foreign_fence&&(!queue||FAILED(queue->Wait(s.foreign_fence.Get(),1))))return {};
            s.leased=true;snapshot_leases[i]=true;return s.texture;
        };
        r.left=lease(a);
        r.right=(b==a)?r.left:lease(b);
        std::ostringstream label;
        label<<"left_choice="<<left_selector<<" left_DSV=0x"<<std::hex
             <<reinterpret_cast<std::uintptr_t>(slots[a].source.Get())
             <<" right_choice="<<std::dec<<right_selector<<" right_DSV=0x"<<std::hex
             <<reinterpret_cast<std::uintptr_t>(slots[b].source.Get())<<std::dec
             <<" serials="<<slots[a].serial<<","<<slots[b].serial
             <<" matchedEyes=UNVERIFIED";
        r.label=label.str();
        return r;
    }
'''
edit(depth,'    bool accepts_cached_dsv_metadata() const override { return true; }',
     probe+'    bool accepts_cached_dsv_metadata() const override { return true; }',"candidate API")

hdr="src/mods/vr/D3D12Component.hpp"
edit(hdr,'    std::atomic<uint64_t> m_duo_snapshot_pending{0};',
'''    std::atomic<uint64_t> m_duo_snapshot_pending{0};
    std::atomic<int> m_duo_left_choice{0}, m_duo_right_choice{0};
    std::atomic<uint32_t> m_duo_preview_mode{0};''',"atomic controls")
edit(hdr,'    uint64_t request_duoview_diagnostic_capture() {',
'''    int duoview_depth_candidate_count() const {
        return m_stock_dibr_scope ? int(m_stock_dibr_depth->preview_count()) : 0;
    }
    std::string duoview_depth_candidate_inventory() const {
        return m_stock_dibr_scope ? m_stock_dibr_depth->preview_inventory() :
            "R5 capture inactive: enable R5 observer and re-enter DuoView ID6";
    }
    int duoview_left_choice() const {return m_duo_left_choice.load();}
    int duoview_right_choice() const {return m_duo_right_choice.load();}
    uint32_t duoview_preview_mode() const {return m_duo_preview_mode.load();}
    void duoview_select_candidates(int l,int r,uint32_t mode) {
        m_duo_left_choice.store((std::max)(0,l));
        m_duo_right_choice.store((std::max)(0,r));
        m_duo_preview_mode.store(mode<=3?mode:0);
    }
    uint64_t request_duoview_diagnostic_capture() {''',"UI accessors")
vr="src/mods/VR.cpp"
edit(vr,'                    if (ImGui::Button("CAPTURE NOW: both source colors + ALL eligible depth candidates")) {',
'''                    ImGui::Separator();
                    ImGui::TextUnformatted("LIVE DEPTH CANDIDATE VIEWER");
                    ImGui::TextWrapped("0=auto (largest DSV viewport, eye attribution not proven). Choose candidates and compare visible geometry to Fovea/Periphery color.");
                    const int n=m_d3d12.duoview_depth_candidate_count();
                    int left=m_d3d12.duoview_left_choice();
                    int right=m_d3d12.duoview_right_choice();
                    int mode=int(m_d3d12.duoview_preview_mode());
                    bool changed=false;
                    changed|=ImGui::SliderInt("LEFT fovea candidate (0 Auto)",&left,0,(std::max)(1,n));
                    changed|=ImGui::SliderInt("RIGHT periphery candidate (0 Auto)",&right,0,(std::max)(1,n));
                    changed|=ImGui::SliderInt("View depth (0 Off / 1 L / 2 R / 3 split)",&mode,0,3);
                    if(changed) m_d3d12.duoview_select_candidates(left,right,uint32_t(mode));
                    const auto listing=m_d3d12.duoview_depth_candidate_inventory();
                    ImGui::TextWrapped("%s",listing.c_str());
                    if (ImGui::Button("CAPTURE NOW: both source colors + ALL eligible depth candidates")) {''',
"selector UI")
dc="src/mods/vr/D3D12Component.cpp"
edit(dc,'''                            const uint64_t capture_id=m_duo_snapshot_pending.load(std::memory_order_acquire);
                            std::shared_ptr<uevr::duoview::diag::Session> capture;''',
'''                            const uint64_t capture_id=m_duo_snapshot_pending.load(std::memory_order_acquire);
                            const uint32_t preview_mode=m_duo_preview_mode.load(std::memory_order_acquire);
                            stock_dibr::DepthCapture::PreviewPair depths{};
                            if(m_stock_dibr_scope && preview_mode) {
                                depths=m_stock_dibr_depth->select_preview(m_duo_left_choice.load(),m_duo_right_choice.load());
                            }
                            if(preview_mode && (!depths.left||!depths.right))
                                SPDLOG_WARN_EVERY_N_SEC(2,"[DuoView][Preview] Candidate pair unavailable; use manual sliders and capture ZIP");
                            std::shared_ptr<uevr::duoview::diag::Session> capture;''',
"preview selected during existing frame preparation")
edit(dc,'                                info << " crop=(" << packet_frame->config.layout.u0 << ","',
'''                                info << " previewMode=" << preview_mode
                                     << " manualLeft=" << m_duo_left_choice.load()
                                     << " manualRight=" << m_duo_right_choice.load()
                                     << " candidateProof={" << depths.label << "}";
                                info << " crop=(" << packet_frame->config.layout.u0 << ","''',
"selected candidates saved to manifest")
edit(dc,'''                                 capture,&capture_recorded](''',
'''                                 capture,&capture_recorded,
                                 left_depth=depths.left,right_depth=depths.right,preview_mode](''',
"resource lifetime in command callback")
edit(dc,'''                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);''',
'''                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0,
                                        left_depth.Get(),right_depth.Get(),preview_mode);''',
"send live candidates to compositor preview PSO")
edit(dc,'''                                if ((submitted && recorded && callback_attempted) || capture_id)
                                    m_stock_dibr_depth->finish_frame();''',
'''                                if ((submitted && recorded && callback_attempted) || capture_id || preview_mode)
                                    m_stock_dibr_depth->finish_frame();''',
"GPU retire preview consumers")
print("Depth preview browser applied. Manual/Auto candidate selection and capture metadata now part of ID6.")
