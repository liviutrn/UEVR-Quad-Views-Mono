#!/usr/bin/env python3
"""B18: native-only publication, bounded bootstrap, no automatic GPU readback."""
from pathlib import Path
import shutil
import sys

def one(s,old,new):
    if s.count(old)!=1:raise RuntimeError(f'B18 core anchor count {s.count(old)}: {old[:100]}')
    return s.replace(old,new,1)

def main():
    root=Path(sys.argv[1]);overlay=Path(__file__).parent
    base=root/'src/mods'
    hook=(base/'vr/FFakeStereoRenderingHook.cpp').read_text()
    hook=one(hook,'#include "DuoViewGeometry.hpp"','#include "DuoViewGeometry.hpp"\n#include "TriViewAdmission.hpp"')
    hook=one(hook,'        if (!qv_target_set) { call_original(); return; }', '''        if (!qv_target_set) {
            // B18: keep engine/RHI bootstrap moving without four atlas rasters.
            // This family has no native target provenance and cannot publish.
            uevr::quadview::BootstrapViewCount bootstrap_views{views.count};
            call_original();
            return;
        }''')
    hook=one(hook,'            (!qv_native_ready || native_callback) &&','            qv_native_ready && native_callback &&')
    consumer=(base/'vr/D3D12Component.cpp').read_text()
    consumer=one(consumer,'#include "QuadViewNgxDepth.hpp"','#include "QuadViewNgxDepth.hpp"\n#include "TriViewAdmission.hpp"')
    consumer=one(consumer,'                            const auto frozen=packet->producer;','''                            const auto frozen=packet->producer;
                            if (!uevr::quadview::native_triview_publishable(frozen->layout.shared_context,
                                    frozen->layout.native_local,packet->native_target_set_generation)) {
                                vr->set_quadview_status("Waiting for three authenticated native TriView sources");
                                return;
                            }''')
    start=consumer.index('        {   // Tri-view B11 proof: one automatic snapshot 25 s')
    end=consumer.index('        {   // Tri-view B11 startup proof:',start)
    consumer=consumer[:start]+'''        // B18: GPU readback is manual-only. No automatic allocation/copy spike
        // during normal play or a performance comparison.
        {
            static bool snapshot_dir_set=false;
            if (!snapshot_dir_set) {
                uevr::quadview::dx12::set_snapshot_directory(Framework::get_persistent_dir()/"triview_snapshots");
                snapshot_dir_set=true;
            }
            static uint32_t snapshots_logged=0;
            if (const auto n=uevr::quadview::dx12::snapshots_written().load(); n!=snapshots_logged) {
                snapshots_logged=n;
                spdlog::info("[TriView][Snapshot] {}",uevr::quadview::dx12::last_snapshot_message());
            }
        }
'''+consumer[end:]
    (base/'vr/FFakeStereoRenderingHook.cpp').write_text(hook)
    (base/'vr/D3D12Component.cpp').write_text(consumer)
    shutil.copyfile(overlay/'TriViewAdmission.hpp',base/'vr/TriViewAdmission.hpp')
    canonical=(overlay/'QuadViewNativeDelivery.hpp').read_text(encoding='utf-8')
    if (base/'vr/QuadViewNativeDelivery.hpp').read_text(encoding='utf-8')!=canonical:
        raise RuntimeError('Final production/test NativeDelivery header mismatch')
    print('B18 core: canonical delivery parity; context-only engine bootstrap; native-only presentation; manual GPU snapshots')
if __name__=='__main__':main()
