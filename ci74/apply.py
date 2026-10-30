"""CI74 additive compact stereo sequence recorder. Apply AFTER CI73.
Never alters the stereo shader; keeps existing one-shot capture untouched.
"""
from pathlib import Path
import sys, shutil

def replace(path, old, new):
    p=Path(path)
    s=p.read_text(encoding='utf-8')
    count=s.count(old)
    if count != 1:
        raise RuntimeError(f'CI74 source mismatch in {p}: {old[:90]!r}: count {count}')
    p.write_text(s.replace(old,new,1),encoding='utf-8')

def apply(backend):
    backend=Path(backend).resolve()
    ci=Path(__file__).resolve().parent
    vr=backend/'src/mods/vr'
    target=vr/'d3d12/DuoViewSequenceRecorder.hpp'
    shutil.copyfile(ci/'DuoViewSequenceRecorder.hpp',target)
    h=vr/'D3D12Component.hpp'
    cpp=vr/'D3D12Component.cpp'
    ui=backend/'src/mods/VR.cpp'
    replace(h,'#include "d3d12/DuoViewDiagnosticDump.hpp"',
            '#include "d3d12/DuoViewDiagnosticDump.hpp"\n#include "d3d12/DuoViewSequenceRecorder.hpp"')
    replace(h,'''    uint64_t duoview_diagnostic_capture_pending() const {
        return m_duo_snapshot_pending.load(std::memory_order_acquire);
    }''', '''    uint64_t duoview_diagnostic_capture_pending() const {
        return m_duo_snapshot_pending.load(std::memory_order_acquire);
    }
    uint64_t request_duoview_sequence_capture() {
        if(!m_stock_dibr_scope) return 0;
        std::lock_guard lock(m_duo_sequence_mutex);
        if(m_duo_sequence_capture && m_duo_sequence_capture->active()) return 0;
        const uint64_t id=m_duo_sequence_serial.fetch_add(1,std::memory_order_relaxed)+1;
        m_duo_sequence_capture=std::make_shared<uevr::duoview::sequence::Recorder>(id);
        return id;
    }
    std::string duoview_sequence_capture_status() const {
        std::lock_guard lock(m_duo_sequence_mutex);
        return m_duo_sequence_capture ? m_duo_sequence_capture->status() : "No sequence captured yet";
    }''')
    replace(h,'    std::atomic<uint64_t> m_duo_snapshot_start{0};', '''    std::atomic<uint64_t> m_duo_snapshot_start{0};
    mutable std::mutex m_duo_sequence_mutex;
    std::shared_ptr<uevr::duoview::sequence::Recorder> m_duo_sequence_capture;
    std::atomic<uint64_t> m_duo_sequence_serial{0};''')
    replace(ui,'''                    ImGui::Text("Pending capture request: %llu",static_cast<unsigned long long>(m_d3d12.duoview_diagnostic_capture_pending()));''', '''                    ImGui::Text("Pending capture request: %llu",static_cast<unsigned long long>(m_d3d12.duoview_diagnostic_capture_pending()));
                    ImGui::Separator();
                    if(ImGui::Button("RECORD 2s stereo jitter (compact ZIP)")) {
                        const auto id=m_d3d12.request_duoview_sequence_capture();
                        if(id) SPDLOG_INFO("[DuoView][Sequence] Started stereo recording #{}",id);
                        else SPDLOG_WARN("[DuoView][Sequence] Busy, waiting for capture, or ID6 disabled");
                    }
                    const auto status=m_d3d12.duoview_sequence_capture_status();
                    ImGui::TextWrapped("Sequence: %s",status.c_str());
                    ImGui::TextWrapped("3s countdown then records final XR left/right center 512px crops and real source 256px crops each genuine frame for 2s (64-frame cap). ZIP target under 18 MiB, saved under TEMP\\\\UEVR_DuoViewSequences. Remain still and look at a jittering edge. Capture does not include real DLSS depth; color source/eye pairing remains unauthenticated.");''')
    replace(cpp,'''                            const std::array<float,4> stereo_quality{''', '''                            // Sequence readbacks are created before XR's recording callback.
                            std::shared_ptr<uevr::duoview::sequence::Recorder> sequence;
                            {
                                std::lock_guard lock(m_duo_sequence_mutex);
                                sequence=m_duo_sequence_capture;
                            }
                            auto sequence_frame=sequence ? sequence->stage(device) : nullptr;
                            std::ostringstream sequence_info;
                            if(sequence_frame) {
                                sequence_info<<std::setprecision(17)
                                   <<"frame="<<packet_frame->config.key.frame
                                   <<" generation="<<packet_frame->config.key.generation
                                   <<" sourceFrame="<<*packet_source
                                   <<" stereoRequested="<<stereo_mode
                                   <<" stereoEffective="<<effective_stereo_mode
                                   <<" leftDepthSerial="<<depths.left_serial
                                   <<" rightDepthSerial="<<depths.right_serial
                                   <<" depthIdentityAuthenticated=false"
                                   <<" crop="<<packet_frame->config.layout.u0<<","<<packet_frame->config.layout.v0<<","<<packet_frame->config.layout.u1<<","<<packet_frame->config.layout.v1;
                                for(unsigned eye=0;eye<2;++eye) {
                                    const auto& cam=packet_frame->eye_cameras[eye];
                                    sequence_info<<" eye"<<eye<<"Position=";
                                    for(const auto& v:cam.position)sequence_info<<v<<",";
                                    sequence_info<<" eye"<<eye<<"Rotation=";
                                    for(const auto& v:cam.rotation)sequence_info<<v<<",";
                                }
                                sequence_info<<" leftProjection=";
                                for(const auto& v:packet_frame->projection)sequence_info<<v<<",";
                                sequence_info<<" rightProjection=";
                                for(const auto& v:packet_frame->projection_right)sequence_info<<v<<",";
                            }
                            bool sequence_recorded=false;
                            const std::array<float,4> stereo_quality{''')
    replace(cpp,'''                                 capture,&capture_recorded,
                                 left_depth=depths.left''', '''                                 capture,&capture_recorded,sequence,sequence_frame,&sequence_recorded,
                                 left_depth=depths.left''')
    replace(cpp,'''                                    if (compositor.recorded_commands()) commands.has_commands = true;''', '''                                    if(recorded && sequence && sequence_frame) {
                                        const auto& layout=packet_frame->config.layout;
                                        sequence_recorded=sequence->record(commands.cmd_list.Get(),sequence_frame,
                                            destination,source.Get(),secondary.Get(),
                                            layout.fovea.width,layout.fovea.height,
                                            layout.periphery.width,layout.periphery.height);
                                        if(sequence_recorded) commands.has_commands=true;
                                    }
                                    if (compositor.recorded_commands()) commands.has_commands = true;''')
    replace(cpp,'''                            if (capture && capture_recorded &&
                                d3d12::dibr_transaction::commands_were_submitted(capture_submission)) {''', '''                            if(sequence && sequence_frame) {
                                auto* queue=g_framework->get_d3d12_hook()->get_command_queue();
                                sequence->submit(sequence_frame,queue,
                                    submitted && sequence_recorded &&
                                    d3d12::dibr_transaction::commands_were_submitted(capture_submission),
                                    packet->serial,sequence_info.str());
                            }
                            if(sequence)sequence->finish_if_ready();
                            if (capture && capture_recorded &&
                                d3d12::dibr_transaction::commands_were_submitted(capture_submission)) {''')
    print('CI74 recorder integrated after CI73; renderer/shaders unchanged.')

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: python ci74/apply.py <patched-uevr-backend>')
    apply(sys.argv[1])
