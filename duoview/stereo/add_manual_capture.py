#!/usr/bin/env python3
"""Manual, repeatable diagnostic captures, independent of the stereo compositor.
Apply AFTER enhance_depth_bridge_v1.py, never in any existing V3 branch.
"""
from pathlib import Path
import shutil, sys
if len(sys.argv)!=2: raise SystemExit("usage: add_manual_capture.py <patched backend>")
root=Path(sys.argv[1]).resolve()
here=Path(__file__).resolve().parent
dest=root/"src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp"
shutil.copyfile(here/"DuoViewDiagnosticDump.hpp",dest)
def edit(rel,old,new,tag):
    path=root/rel
    s=path.read_text(encoding="utf-8-sig")
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{tag}: missing/ambiguous source anchor {rel} ({n} matches)")
    path.write_text(s.replace(old,new,1),encoding="utf-8",newline="")
depth="src/mods/vr/d3d12/StockDibrDepth.hpp"
edit(depth,'#include "DepthPolicy.hpp"',
    '#include "DepthPolicy.hpp"\n#include "DuoViewDiagnosticDump.hpp"', "diagnostic types")
edit(depth,'    static constexpr size_t Capacity = 12;',
    '    static constexpr size_t Capacity = 48;\n    static constexpr size_t NormalCapacity = 12;', "snapshot capacity")
edit(depth,'    std::string observed{"none"};',
'''    std::string observed{"none"};
    bool snapshot_armed{};
    std::array<bool,Capacity> snapshot_leases{};
    std::unordered_map<std::uintptr_t,std::string> diagnostic_catalog{};
    uint64_t diagnostic_catalog_overflow{};''', "manual capture/catalog fields")
# In DepthBridge V1.1, observed has extra provenance members after this anchor: harmless.
edit(depth,'    bool accepts_cached_dsv_metadata() const override { return true; }',
'''    void arm_diagnostic_capture() {
        std::scoped_lock lock{mutex};
        snapshot_armed=true;
    }
    std::string diagnostic_inventory() const {
        std::scoped_lock lock{mutex};
        std::ostringstream o;
        o << "all_DSV_resources_seen=" << (diagnostic_catalog.size()+diagnostic_catalog_overflow)
          << " inventory_capped=" << diagnostic_catalog_overflow
          << " producer_copies_this_interval=" << recorded_this_interval
          << " producer_capacity=" << (snapshot_armed ? Capacity : NormalCapacity);
        for (const auto& [ptr,detail] : diagnostic_catalog) o << "\\n" << detail;
        return o.str();
    }
    std::vector<uevr::duoview::diag::Candidate> snapshot_candidates() {
        std::scoped_lock lock{mutex};
        std::vector<uevr::duoview::diag::Candidate> result;
        if(!enabled || !snapshot_armed) return result;
        result.reserve(Capacity);
        for (size_t i=0;i<slots.size();++i) {
            auto& s=slots[i];
            if(!s.texture || s.pending || s.leased || s.quarantined || s.epoch!=epoch ||
               (!s.fence && !s.foreign_fence)) continue;
            if(s.foreign_fence && (!queue || FAILED(queue->Wait(s.foreign_fence.Get(),1)))) {
                last="diagnostic candidate foreign-queue GPU wait rejected";
                continue;
            }
            uevr::duoview::diag::Candidate c;
            c.source=s.texture;c.state=Read;c.serial=s.serial;
            const auto d=s.texture->GetDesc();
            std::ostringstream label;
            label << "originalDSV=0x" << std::hex << reinterpret_cast<std::uintptr_t>(s.source.Get())
                  << std::dec << " epoch=" << s.epoch << " serial=" << s.serial
                  << " format=" << unsigned(d.Format)
                  << " viewport=(" << s.viewport.TopLeftX << "," << s.viewport.TopLeftY
                  << "," << s.viewport.Width << "," << s.viewport.Height << ")"
                  << " layout=" << (s.layout==Layout::Eye ? "eye" : "packed")
                  << " eyeAttribution=UNPROVEN";
            c.details=label.str();
            result.push_back(std::move(c));
            s.leased=true;
            snapshot_leases[i]=true;
        }
        return result;
    }
    bool accepts_cached_dsv_metadata() const override { return true; }''', "public manual snapshot API")
edit(depth,'''        ++dsv_events;
        const auto key = descriptor.ptr;''',
'''        ++dsv_events;
        if (resource) {
            const auto key_id=reinterpret_cast<std::uintptr_t>(resource);
            if (!diagnostic_catalog.contains(key_id)) {
                if (diagnostic_catalog.size()<256) {
                    // Cache replay supplies a non-owning pointer identity.
                    // Its resource may already be destroyed: NEVER call COM here.
                    std::ostringstream label;
                    label << "DSV=0x" << std::hex << key_id << std::dec
                          << " viewFormat=" << unsigned(dsv ? dsv->Format : DXGI_FORMAT_UNKNOWN)
                          << " allocation=UNKNOWN_UNTIL_LIVE_BARRIER"
                          << " classification=METADATA_ONLY_NONOWNING";
                    diagnostic_catalog.emplace(key_id,label.str());
                } else ++diagnostic_catalog_overflow;
            }
        }
        const auto key = descriptor.ptr;''', "inventory all DSV creations")
edit(depth,'''            observed = std::to_string(desc.Width) + "x" + std::to_string(desc.Height) + " fmt=" + std::to_string(desc.Format);''',
'''            // Only the live ResourceBarrier callback supplies a resource
            // whose lifetime is guaranteed by the executing engine call.
            const auto live_key=reinterpret_cast<std::uintptr_t>(source);
            if(diagnostic_catalog.contains(live_key) || diagnostic_catalog.size()<256) {
                std::ostringstream label;
                label << "DSV=0x" << std::hex << live_key << std::dec
                      << " allocation=" << desc.Width << "x" << desc.Height
                      << " format=" << unsigned(desc.Format)
                      << " array=" << desc.DepthOrArraySize
                      << " MSAA=" << desc.SampleDesc.Count
                      << " classification=LIVE_BARRIER_OBSERVED_ONLY";
                diagnostic_catalog[live_key]=label.str();
            }
            observed = std::to_string(desc.Width) + "x" + std::to_string(desc.Height) + " fmt=" + std::to_string(desc.Format);''',
"read allocation metadata only from the live barrier resource")
edit(depth,'recorded_this_interval >= Capacity || render_passes.contains',
    'recorded_this_interval >= (snapshot_armed ? Capacity : NormalCapacity) || render_passes.contains',
    "bounded high-capacity manual sampling")
edit(depth,'            if (recorded_this_interval >= Capacity) return;',
    '            if (recorded_this_interval >= (snapshot_armed ? Capacity : NormalCapacity)) return;',
    "bounded sampling loop")
edit(depth,'''        ++epoch; recorded_this_interval = 0;
        executed_proofs.clear();''',
'''        // Captures were copied into the same present queue before this call.
        // Fence ALL manually leased candidates past the snapshot consumer,
        // not only the one best candidate used by stock DIBR.
        bool any_snapshot_lease=false;
        for (bool x:snapshot_leases) any_snapshot_lease|=x;
        if (any_snapshot_lease) {
            const bool signalled = queue && fence &&
                SUCCEEDED(queue->Signal(fence.Get(), ++signal));
            for(size_t i=0;i<snapshot_leases.size();++i) if(snapshot_leases[i]) {
                auto& s=slots[i];
                if(signalled){s.fence=signal;s.leased=false;}
                else {enabled=false;s.quarantined=true;s.epoch=0;s.leased=false;}
                snapshot_leases[i]=false;
            }
            if(!signalled)last="diagnostic producer retirement signal failure; slots quarantined";
        }
        snapshot_armed=false;
        ++epoch; recorded_this_interval = 0;
        executed_proofs.clear();''', "release snapshot-owned source slots only after capture consumer")
# Ensure no accidental capture of slots with preexisting leases; direct DIBR path untouched.
hdr="src/mods/vr/D3D12Component.hpp"
edit(hdr,'#include "d3d12/StockDibrDepth.hpp"',
    '#include "d3d12/StockDibrDepth.hpp"\n#include "d3d12/DuoViewDiagnosticDump.hpp"',
    "include offline screenshot utility")
edit(hdr,'    std::shared_ptr<stock_dibr::DepthCapture> m_stock_dibr_depth{std::make_shared<stock_dibr::DepthCapture>()};',
'''    std::shared_ptr<stock_dibr::DepthCapture> m_stock_dibr_depth{std::make_shared<stock_dibr::DepthCapture>()};
    std::atomic<uint64_t> m_duo_snapshot_serial{0};
    std::atomic<uint64_t> m_duo_snapshot_pending{0};''', "snapshot state")
edit(hdr,'    std::string get_dibr_preview_depth_trace_summary() const { return m_stock_dibr_scope ? m_stock_dibr_depth->summary() : m_dibr_depth_capture.depth_trace_summary(); }',
'''    std::string get_dibr_preview_depth_trace_summary() const { return m_stock_dibr_scope ? m_stock_dibr_depth->summary() : m_dibr_depth_capture.depth_trace_summary(); }
    uint64_t request_duoview_diagnostic_capture() {
        if(!m_stock_dibr_scope)return 0;
        uint64_t expected=0;
        const auto id=m_duo_snapshot_serial.fetch_add(1,std::memory_order_relaxed)+1;
        if(!m_duo_snapshot_pending.compare_exchange_strong(expected,id,std::memory_order_acq_rel))
            return 0; // never silently replace a still-pending request
        m_stock_dibr_depth->arm_diagnostic_capture();
        return id;
    }
    uint64_t duoview_diagnostic_capture_pending() const {
        return m_duo_snapshot_pending.load(std::memory_order_acquire);
    }''', "public request API")
vr="src/mods/VR.cpp"
edit(vr,'                    ImGui::TextWrapped("Proof means submitted GPU DSV/viewport; it does NOT guarantee association with UE0 LEFT or UE1 RIGHT.");',
'''                    ImGui::TextWrapped("Proof means submitted GPU DSV/viewport; it does NOT guarantee association with UE0 LEFT or UE1 RIGHT.");
                    if (ImGui::Button("CAPTURE NOW: both source colors + ALL eligible depth candidates")) {
                        const auto id=m_d3d12.request_duoview_diagnostic_capture();
                        if(id) SPDLOG_INFO("[DuoView][Capture] Requested manual capture #{}",id);
                        else SPDLOG_WARN("[DuoView][Capture] Busy or R5 observer not yet active; re-enter ID6");
                    }
                    ImGui::TextWrapped("Each press saves a NEW folder: Windows TEMP\\\\UEVR_DuoViewCaptures\\\\capture_N");
                    ImGui::TextWrapped("Color BMP + raw BGRA; depth preview BMP + raw depth + manifest.json. No continuous GPU readback.");
                    ImGui::Text("Pending capture request: %llu",static_cast<unsigned long long>(m_d3d12.duoview_diagnostic_capture_pending()));''', "manual button")
# Callbacks: assemble one snapshot from the exact current Native source pair + bounded submitted candidate samples.
dc="src/mods/vr/D3D12Component.cpp"
edit(dc,'''                            bool recorded = false;
                            bool callback_attempted = false;
                            bool compositor_fault = false;''',
'''                            // Manual capture: allocate readback resources on the Present
                            // preparation path, NEVER inside the OpenXR command callback.
                            const uint64_t capture_id=m_duo_snapshot_pending.load(std::memory_order_acquire);
                            std::shared_ptr<uevr::duoview::diag::Session> capture;
                            if (capture_id && m_stock_dibr_scope) {
                                std::ostringstream info;
                                info << "packet=" << packet->serial
                                     << " monoSourceFrame=" << *packet_source
                                     << " generation=" << packet_frame->config.key.generation
                                     << " draw=" << packet_frame->config.key.frame
                                     << " UE0=LEFT fovea UE1=RIGHT periphery; eye depth identity NOT proven";
                                const auto& left=packet_frame->eye_cameras[0];
                                const auto& right=packet_frame->eye_cameras[1];
                                info << " LEFTcam=(" << left.position[0] << "," << left.position[1]
                                     << "," << left.position[2] << ") RIGHTcam=("
                                     << right.position[0] << "," << right.position[1]
                                     << "," << right.position[2] << ")";
                                info << " crop=(" << packet_frame->config.layout.u0 << ","
                                     << packet_frame->config.layout.v0 << ","
                                     << packet_frame->config.layout.u1 << ","
                                     << packet_frame->config.layout.v1 << ")";
                                capture=std::make_shared<uevr::duoview::diag::Session>(
                                    capture_id,info.str(),m_stock_dibr_depth->diagnostic_inventory());
                                const auto candidates=m_stock_dibr_depth->snapshot_candidates();
                                if(!capture->prepare(device,m_game_tex.texture.Get(),
                                    m_scene_capture_tex.texture.Get(),candidates)) capture.reset();
                            }
                            bool capture_recorded=false;
                            bool recorded = false;
                            bool callback_attempted = false;
                            bool compositor_fault = false;''', "create one-shot capture on frozen same-frame packet")
edit(dc,'''&output_direct, &source_extents, &recorded_secondary, &recorded_target](''',
'''&output_direct, &source_extents, &recorded_secondary, &recorded_target,
                                 capture,&capture_recorded](''', "callback owns capture references")
edit(dc,'''                                    if (compositor.recorded_commands()) commands.has_commands = true;''',
'''                                    if (recorded && capture) {
                                        // Sources have been restored to their native RT states
                                        // by record_native; append independent readback copies.
                                        if(capture->record(commands.cmd_list.Get())) {
                                            capture_recorded=true;
                                            commands.has_commands=true;
                                        }
                                    }
                                    if (compositor.recorded_commands()) commands.has_commands = true;''', "record without altering V3 rendered output")
edit(dc,'''                            if (submitted && recorded && callback_attempted) {
                                if (native_frame_ticket) {''',
'''                            if (capture && capture_recorded) {
                                // OpenXR::copy already enqueued commands.execute() before
                                // it returned. A separate queue marker lets the worker
                                // save disk images with NO wait on the XR thread.
                                auto* queue=g_framework->get_d3d12_hook()->get_command_queue();
                                if(capture->launch(device,queue)) {
                                    auto expected=capture_id;
                                    m_duo_snapshot_pending.compare_exchange_strong(
                                        expected,0,std::memory_order_acq_rel);
                                    SPDLOG_INFO("[DuoView][Capture] GPU readbacks enqueued for capture #{}; output under Windows TEMP\\\\UEVR_DuoViewCaptures",
                                        capture_id);
                                } else {
                                    SPDLOG_ERROR("[DuoView][Capture] Could not fence snapshot {}; retaining request for retry",capture_id);
                                }
                            }
                            if (submitted && recorded && callback_attempted) {
                                if (native_frame_ticket) {''', "readback after checked queue enqueue")
# Needed to retire snapshot leases even when XR submission failed; never leave captured R5 resources leased.
edit(dc,'''                                if (submitted && recorded && callback_attempted)
                                    m_stock_dibr_depth->finish_frame();''',
'''                                if ((submitted && recorded && callback_attempted) || capture_id)
                                    m_stock_dibr_depth->finish_frame();''', "retire manual snapshot leases")
print("Manual capture integrated: numbered repeatable GPU-fenced readback sessions, both color sources and every R5-eligible depth sample. The compositor itself remains unchanged.")
