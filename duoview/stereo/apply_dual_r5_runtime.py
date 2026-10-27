#!/usr/bin/env python3
"""B3/B4 live wiring. Apply after B2 and stock R5 overlays; guarded anchors.
If dual color/depth validation fails, XR holds its last valid frame rather than
quietly producing a fake stereoscopic copy.
"""
import pathlib,sys,shutil
root=pathlib.Path(sys.argv[1]).resolve()
src=pathlib.Path(__file__).resolve().parent
def edit(path,old,new):
    p=root/path;s=p.read_text(encoding='utf-8-sig')
    count=s.count(old)
    if count!=1:raise RuntimeError(f'B3/B4 refused ambiguous {path}: {count}: {old[:120]!r}')
    p.write_text(s.replace(old,new,1),encoding='utf-8',newline='')
h='src/mods/VR.hpp'
edit(h,'    bool is_duoview_binocular_requested() const {',
'''    const ModToggle::Ptr m_duo_r5_stereo{ModToggle::create(generate_name("DuoViewR5BidirectionalStereo"), false)};
    bool is_duoview_r5_stereo_enabled() const {
        return is_duoview_renderer_active() && m_duo_r5_stereo->value();
    }
    bool is_duoview_binocular_requested() const {''')
edit(h,'return is_duoview_renderer_active() && m_duo_binocular_sources->value();',
       'return is_duoview_renderer_active() && (m_duo_binocular_sources->value() || m_duo_r5_stereo->value());')
edit(h,'*m_duo_native_fix, *m_duo_binocular_sources, *m_duo_quant,',
       '*m_duo_native_fix, *m_duo_binocular_sources, *m_duo_r5_stereo, *m_duo_quant,')
c='src/mods/VR.cpp'
edit(c,'m_duo_binocular_sources->draw("B2: render fovea from LEFT / periphery from RIGHT (EXPERIMENTAL)");',
'''m_duo_binocular_sources->draw("B2: render fovea from LEFT / periphery from RIGHT (EXPERIMENTAL)");
                m_duo_r5_stereo->draw("B3+B4: TWO R5 reprojections + true binocular XR output (EXPERIMENTAL)");
                ImGui::TextWrapped("B3+B4 require valid per-eye R5 depth, fovea UE0 / periphery UE1, and physical HMD IPD. Enable DSV/RDG capture above, select original DuoView ID6 and reload the mode. The default stereo switch is OFF; failures do not silently fake stereo.");''')
edit(c,'m_duo_binocular_sources->value()=false;', 'm_duo_binocular_sources->value()=false; m_duo_r5_stereo->value()=false;')

dh='src/mods/vr/D3D12Component.hpp'
edit(dh,'#include "DuoViewD3D12.hpp"',
       '#include "DuoViewD3D12.hpp"\n#include "DuoViewDualR5Depth.hpp"')
edit(dh,'        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;',
'''        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;
        // Shared type erasure breaks VR.hpp <-> D3D12Component.hpp include cycle.
        // All actual GPU objects remain owned per retired command slot.
        std::unordered_map<d3d12::CommandContext*, std::shared_ptr<void>> duoview_r5_slots;''')
edit(dh,'    std::shared_ptr<stock_dibr::DepthCapture> m_stock_dibr_depth{std::make_shared<stock_dibr::DepthCapture>()};',
'''    std::shared_ptr<stock_dibr::DepthCapture> m_stock_dibr_depth{std::make_shared<stock_dibr::DepthCapture>()};
    std::shared_ptr<uevr::duoview::r5::DualDepth> m_duo_r5_depth{
        std::make_shared<uevr::duoview::r5::DualDepth>()};''')

dc='src/mods/vr/D3D12Component.cpp'
edit(dc,'#include "DuoViewD3D12.hpp"', '#include "DuoViewD3D12.hpp"\n#include "DuoViewR5StereoSlot.hpp"') if '#include "DuoViewD3D12.hpp"' in (root/dc).read_text() else edit(dc,'#include "D3D12Component.hpp"', '#include "D3D12Component.hpp"\n#include "DuoViewR5StereoSlot.hpp"')
edit(dc,'    stock_dibr::DepthRetirementHub::arm(m_stock_dibr_depth);',
'''    stock_dibr::DepthRetirementHub::arm(m_stock_dibr_depth);
    stock_dibr::DepthRetirementHub::arm(m_duo_r5_depth);''') if (root/dc).read_text().count('    stock_dibr::DepthRetirementHub::arm(m_stock_dibr_depth);')==1 else None
# A component's R5 observer must not lose retirement ownership on mode change.
edit(dc,'        hook->set_depth_stencil_observer(m_stock_dibr_scope ?',
'''        if (m_stock_dibr_scope && vr->is_duoview_binocular_requested()) {
            stock_dibr::DepthRetirementHub::arm(m_duo_r5_depth);
        } else stock_dibr::DepthRetirementHub::disarm(m_duo_r5_depth);
        hook->set_depth_stencil_observer(m_stock_dibr_scope && vr->is_duoview_binocular_requested() ?
            static_cast<D3D12DepthStencilObserver*>(m_duo_r5_depth.get()) :
            m_stock_dibr_scope ?''')
edit(dc,'    this->duoview_compositors.clear();',
       '    this->duoview_r5_slots.clear();\n    this->duoview_compositors.clear();')
edit(dc,'    if (!this->duoview_compositors.empty())',
       '    if (!this->duoview_compositors.empty() || !this->duoview_r5_slots.empty())')
edit(dc,'            for (auto& tc : it->second.texture_contexts) {',
'''            for (auto& tc : it->second.texture_contexts) {''') if False else None

# Each new XR command slot receives independent R5 preview state. Allocate
# only after the existing DuoView compositor has proven usable.
edit(dc,'                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();',
'''                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();
                if (!m_openxr.duoview_r5_slots.contains(&tc->commands))
                    m_openxr.duoview_r5_slots[&tc->commands] =
                        std::make_shared<uevr::duoview::r5::StereoSlot>();''')
edit(dc,'                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();',
'''                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();
                if (!this->duoview_r5_slots.contains(&tc->commands))
                    this->duoview_r5_slots[&tc->commands] =
                        std::make_shared<uevr::duoview::r5::StereoSlot>();''')

# Warm up both R5 viewport filters as soon as the captured Native packet
# contains unambiguous fovea and peripheral dimensions.
edit(dc,'''                            if (m_stock_dibr_scope) {
                                const auto duo_depth_extent = m_game_tex.texture->GetDesc();''',
'''                            if (m_stock_dibr_scope && vr->is_duoview_binocular_requested()) {
                                const auto& lay=packet_frame->config.layout;
                                m_duo_r5_depth->configure(device,
                                    g_framework->get_d3d12_hook()->get_command_queue(),
                                    lay.fovea.width,lay.fovea.height,
                                    lay.periphery.width,lay.periphery.height,true);
                            }
                            if (m_stock_dibr_scope && !vr->is_duoview_binocular_requested()) {
                                const auto duo_depth_extent = m_game_tex.texture->GetDesc();''')
# In XR compositor lambda, only synthesize after exact source packet + two
# different depth observer leases; reverse right-eye origin on periphery.
old='''                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),
                                        source.Get(), secondary.Get(), destination,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET, *packet_frame,
                                        std::static_pointer_cast<const void>(packet),
                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);'''
new='''                                    if (vr->is_duoview_r5_stereo_enabled()) {
                                        const auto slot_it=m_openxr.duoview_r5_slots.find(&commands);
                                        const auto typed_slot=slot_it==m_openxr.duoview_r5_slots.end()
                                            ? std::shared_ptr<uevr::duoview::r5::StereoSlot>{}
                                            : std::static_pointer_cast<uevr::duoview::r5::StereoSlot>(slot_it->second);
                                        if (typed_slot) {
                                            // m_openxr.copy() must have retired this exact slot.
                                            typed_slot->retired();
                                            auto fz=m_duo_r5_depth->fovea.acquire();
                                            auto pz=m_duo_r5_depth->periphery.acquire();
                                            const auto fuv=m_duo_r5_depth->fovea.sample_uv();
                                            const auto puv=m_duo_r5_depth->periphery.sample_uv();
                                            const bool ready=fz && pz && fz.Get()!=pz.Get() &&
                                                packet_frame->binocular_enabled &&
                                                packet_frame->config.settings.fovea_view==0;
                                            if(ready && typed_slot->synthesize(
                                                device,commands.cmd_list.Get(),source.Get(),
                                                secondary.Get(),fz.Get(),pz.Get(),fuv,puv,
                                                *packet_frame,vr)) {
                                                recorded=compositor.record_r5_stereo(
                                                    device,commands.cmd_list.Get(),
                                                    typed_slot->fovea.output().texture.Get(),
                                                    typed_slot->periphery.output().texture.Get(),
                                                    destination,*packet_frame,
                                                    std::static_pointer_cast<const void>(packet));
                                                // R5 output/packing allocations and old scene resources
                                                // remain owned by the XR slot until its fence retires.
                                                if(recorded) typed_slot->committed();
                                            }
                                            if(!recorded) {
                                                SPDLOG_WARNING_EVERY_N_SEC(2,
                                                    "[DuoView][B3B4] No validated dual RGB/depth pair: {} fZ={} pZ={}",
                                                    typed_slot->last_error,
                                                    fz!=nullptr,pz!=nullptr);
                                                typed_slot->fovea.abort_recording();
                                                typed_slot->periphery.abort_recording();
                                            }
                                            m_duo_r5_depth->finish_frame();
                                            if (typed_slot->output_recorded ||
                                                typed_slot->native_fovea) commands.has_commands=true;
                                        }
                                    } else {
                                        recorded = compositor.record_native(device, commands.cmd_list.Get(),
                                            source.Get(), secondary.Get(), destination,
                                            D3D12_RESOURCE_STATE_RENDER_TARGET,
                                            D3D12_RESOURCE_STATE_RENDER_TARGET, *packet_frame,
                                            std::static_pointer_cast<const void>(packet),
                                            packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);
                                    }'''
edit(dc,old,new)
# Depth observer report in the B3 path, without restarting the old single
# capture epoch and invalidating two leased R5 textures.
edit(dc,'''                            if (m_stock_dibr_scope) {
                                if (submitted && recorded && callback_attempted)
                                    m_stock_dibr_depth->finish_frame();''',
'''                            if (m_stock_dibr_scope && !vr->is_duoview_binocular_requested()) {
                                if (submitted && recorded && callback_attempted)
                                    m_stock_dibr_depth->finish_frame();''')
# Unavailable DIBR output should not *quarantine DuoView itself*:
# missing depth is routine during first frames and save reload.
edit(dc,'''                                        if (recorded) typed_slot->committed();''',
'''                                        if (recorded) typed_slot->committed();''') if False else None
# Copy source modules into checked-out backend; V1 kept pristine until here.
for name in ('DuoViewDualR5Depth.hpp','DuoViewR5StereoSlot.hpp'):
    dest=root/'src/mods/vr'/name
    if dest.exists():raise RuntimeError('B3 would overwrite existing '+name)
    shutil.copyfile(src/name,dest)
print('B3/B4 integration: dual R5 capture + per-XR-slot bidirectional preview + independent stereo compositor wired.')
