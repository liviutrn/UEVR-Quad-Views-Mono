#!/usr/bin/env python3
"""Connect the source-depth surface renderer to experimental modes 4/5/6.

Applied after all legacy overlays and capture retention. V3 and modes 1..3
remain available. Selection is still a documented GPU/shape heuristic; no
producer authentication is manufactured from a Present epoch.
"""
from pathlib import Path
import shutil
import sys

root=Path(sys.argv[1]).resolve()
source=Path(__file__).resolve().parent.parent
pending={}
def edit(path,before,after):
    p=root/path
    code=pending.get(p,p.read_text(encoding='utf-8-sig'))
    if code.count(before)!=1:
        raise RuntimeError(f'Surface renderer anchor mismatch: {path}: {before[:100]}')
    pending[p]=code.replace(before,after,1)

header='src/mods/vr/D3D12Component.hpp'
edit(header,'m_duo_stereo_mode.store((std::min)(mode,3u)',
    'm_duo_stereo_mode.store((std::min)(mode,6u)')
ui='src/mods/VR.cpp'
edit(ui,'ImGui::SliderInt("TRUE STEREO (0 V3 / 1 stereo / 2 tint / 3 fovea only)",&stereo_mode,0,3)',
    'ImGui::SliderInt("TRUE STEREO (0 V3 / 1-3 legacy / 4 surface fovea / 5 full / 6 coverage)",&stereo_mode,0,6)')
edit(ui,'                    const int n=m_d3d12.duoview_depth_candidate_count();',
'''                    ImGui::TextWrapped("4: source-depth RIGHT fovea; 5: source-depth stereo in fovea and periphery; 6: geometry coverage (green fovea / red fallback). These modes use fresh retained copies immediately, without CI30 pointer probation. Native RIGHT color repairs unavailable surfaces. Eye/frame/stage attribution is still unverified. First activation/layout change prepares GPU resources once per retired XR slot.");
                    const int n=m_d3d12.duoview_depth_candidate_count();''')
depth='src/mods/vr/d3d12/StockDibrDepth.hpp'
edit(depth,'                               UINT right_width,UINT right_height) {',
    '                               UINT right_width,UINT right_height,bool require_probation=true) {')
edit(depth,'        if(left_selector==0 && right_selector==0) {',
    '        if(require_probation && left_selector==0 && right_selector==0) {')
edit(depth,'               s.leased || s.quarantined || (!s.fence && !s.foreign_fence)) continue;',
    '               (s.leased && !snapshot_leases[i]) || s.quarantined || (!s.fence && !s.foreign_fence)) continue;')
edit(depth,r'        for (const auto& [ptr,detail] : diagnostic_catalog) o << "\n" << detail;',
r'''        o << "\nCURRENT COPY SLOTS (producer completion is not consumer retirement):";
        for(size_t i=0;i<slots.size();++i) {
            const auto& s=slots[i];if(!s.texture)continue;
            o << "\nslot="<<i<<" serial="<<s.serial<<" epoch="<<s.epoch
              <<" currentEpoch="<<epoch<<" pending="<<s.pending<<" leased="<<s.leased
              <<" captureLease="<<snapshot_leases[i]<<" quarantined="<<s.quarantined
              <<" fence="<<s.fence<<" foreign="<<bool(s.foreign_fence)
              <<" viewport="<<s.viewport.Width<<"x"<<s.viewport.Height;
        }
        for (const auto& [ptr,detail] : diagnostic_catalog) o << "\n" << detail;''')
component='src/mods/vr/D3D12Component.cpp'
edit(component,'                                    packet_frame->config.layout.periphery.height);',
    '                                    packet_frame->config.layout.periphery.height,stereo_mode<4u);')
edit(component,'''                                        if(capture->attach_headset_output(device,destination) &&
                                           capture->record(commands.cmd_list.Get())) {''',
'''                                        const bool final_capture=capture->attach_headset_output(device,destination);
                                        if(final_capture && effective_stereo_mode>=4u)
                                            capture->attach_surface_outputs(device,compositor.surface_color(0),
                                                effective_stereo_mode>=5u?compositor.surface_color(1):nullptr);
                                        if(final_capture && capture->record(commands.cmd_list.Get())) {''')
for name in ['DuoViewSurfaceReproject.hlsl','SurfaceGeometry.hpp','DuoViewSurfaceD3D12.hpp']:
    shutil.copyfile(source/name,root/'src/mods/vr'/name)
for path,code in pending.items():
    path.write_text(code,encoding='utf-8',newline='')
print('Source-depth surfaces connected to live XR modes 4/5/6; original V3/legacy A/B retained.')
