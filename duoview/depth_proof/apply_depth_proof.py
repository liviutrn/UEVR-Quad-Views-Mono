#!/usr/bin/env python3
"""Stable Build49 + independent opt-in offline depth proof. No P1/S0 patches."""
from pathlib import Path
import argparse

def change(root, path, old, new):
    p=root/path
    s=p.read_text(encoding='utf-8-sig')
    if s.count(old)!=1:
        raise RuntimeError(f'DepthProof source drift: {path}: {s.count(old)} matches: {old[:80]!r}')
    p.write_text(s.replace(old,new,1),encoding='utf-8',newline='\n')

def apply(root):
    change(root,'src/hooks/D3D12Hook.hpp',
        '    virtual ~D3D12DepthStencilObserver() = default;',
        '''    virtual ~D3D12DepthStencilObserver() = default;
    virtual void on_command_list_reset(ID3D12GraphicsCommandList*) {}
    virtual void on_begin_render_pass(ID3D12GraphicsCommandList*, D3D12_RENDER_PASS_FLAGS) {}
    virtual void on_end_render_pass(ID3D12GraphicsCommandList*) {}
    virtual void on_command_lists_submitted(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*) {}''')
    change(root,'src/hooks/D3D12Hook.hpp',
        '    std::vector<std::unique_ptr<PointerHook>> m_resource_barrier_hooks{};',
        '''    std::vector<std::unique_ptr<PointerHook>> m_resource_barrier_hooks{};
    std::vector<std::unique_ptr<PointerHook>> m_depth_proof_reset_hooks{}, m_depth_proof_begin_hooks{}, m_depth_proof_end_hooks{}, m_depth_proof_execute_hooks{};
    std::unordered_map<uintptr_t, PointerHook*> m_depth_proof_reset_lookup{}, m_depth_proof_begin_lookup{}, m_depth_proof_end_lookup{}, m_depth_proof_execute_lookup{};''')
    change(root,'src/hooks/D3D12Hook.hpp',
        '    static void WINAPI resource_barrier(ID3D12GraphicsCommandList* command_list, UINT count, const D3D12_RESOURCE_BARRIER* barriers);',
        '''    static void WINAPI resource_barrier(ID3D12GraphicsCommandList* command_list, UINT count, const D3D12_RESOURCE_BARRIER* barriers);
    static HRESULT WINAPI depth_proof_reset(ID3D12GraphicsCommandList*, ID3D12CommandAllocator*, ID3D12PipelineState*);
    static void WINAPI depth_proof_begin(ID3D12GraphicsCommandList4*, UINT, const D3D12_RENDER_PASS_RENDER_TARGET_DESC*, const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC*, D3D12_RENDER_PASS_FLAGS);
    static void WINAPI depth_proof_end(ID3D12GraphicsCommandList4*);
    static void WINAPI depth_proof_execute(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*);''')
    change(root,'src/hooks/D3D12Hook.cpp',
        '        m_hooked = true;',
        '''        // Proof lifecycle hooks are passive unless an observer opts in.
        // Never assume the Present queue submitted a captured command list.
        std::unordered_set<uintptr_t> proof_reset_slots, proof_begin_slots, proof_end_slots, proof_execute_slots;
        const auto hook_proof_list = [&](IUnknown* p) {
            add_unique_pointer_hook(p,10,reinterpret_cast<void*>(&D3D12Hook::depth_proof_reset),
                m_depth_proof_reset_hooks,m_depth_proof_reset_lookup,proof_reset_slots);
        };
        hook_proof_list(command_list);
        for (auto* p:command_list_interfaces) hook_proof_list(p);
        for (IUnknown* p : std::array<IUnknown*,4>{command_list4.Get(),command_list5.Get(),command_list6.Get(),command_list7.Get()}) {
            add_unique_pointer_hook(p,68,reinterpret_cast<void*>(&D3D12Hook::depth_proof_begin),
                m_depth_proof_begin_hooks,m_depth_proof_begin_lookup,proof_begin_slots);
            add_unique_pointer_hook(p,69,reinterpret_cast<void*>(&D3D12Hook::depth_proof_end),
                m_depth_proof_end_hooks,m_depth_proof_end_lookup,proof_end_slots);
        }
        add_unique_pointer_hook(command_queue,10,reinterpret_cast<void*>(&D3D12Hook::depth_proof_execute),
            m_depth_proof_execute_hooks,m_depth_proof_execute_lookup,proof_execute_slots);
        m_hooked = true;''')
    change(root,'src/hooks/D3D12Hook.cpp',
        '    m_resource_barrier_hooks.clear();',
        '''    m_resource_barrier_hooks.clear();
    m_depth_proof_reset_hooks.clear(); m_depth_proof_begin_hooks.clear(); m_depth_proof_end_hooks.clear(); m_depth_proof_execute_hooks.clear();
    m_depth_proof_reset_lookup.clear(); m_depth_proof_begin_lookup.clear(); m_depth_proof_end_lookup.clear(); m_depth_proof_execute_lookup.clear();''')
    # Each trampoline looks up its own exact vtable slot. No fallback to an
    # unrelated original is permitted for these new lifecycle hooks.
    wrappers=''
    definitions=[
        ('HRESULT','reset','ID3D12GraphicsCommandList* cmd, ID3D12CommandAllocator* alloc, ID3D12PipelineState* pso','cmd','10','cmd,alloc,pso','if (SUCCEEDED(result)) observer->on_command_list_reset(cmd);'),
        ('void','begin','ID3D12GraphicsCommandList4* cmd, UINT n, const D3D12_RENDER_PASS_RENDER_TARGET_DESC* rtv, const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC* dsv, D3D12_RENDER_PASS_FLAGS flags','cmd','68','cmd,n,rtv,dsv,flags','observer->on_begin_render_pass(cmd,flags);'),
        ('void','end','ID3D12GraphicsCommandList4* cmd','cmd','69','cmd','observer->on_end_render_pass(cmd);'),
        ('void','execute','ID3D12CommandQueue* queue, UINT n, ID3D12CommandList* const* lists','queue','10','queue,n,lists','observer->on_command_lists_submitted(queue,n,lists);'),
    ]
    for result,name,args,obj,index,call,observe in definitions:
        original_call=f'auto result=original({call});' if result!='void' else f'original({call});'
        # Begin notification precedes engine Begin; End/Reset/Execute follow
        # original. Copy injection itself is only at an external barrier.
        notify=f'''if (!g_inside_depth_stencil_observer) {{
        if (auto* observer=owner->m_depth_stencil_observer.load(std::memory_order_acquire)) {{ {observe} }}
    }}'''
        body=(notify+'\n    '+original_call) if name=='begin' else (original_call+'\n    '+notify)
        wrappers+=f'''
{result} WINAPI D3D12Hook::depth_proof_{name}({args}) {{
    auto* owner=g_d3d12_hook;
    if (!owner || !{obj}) {'return E_FAIL;' if result!='void' else 'return;'}
    const auto slot=reinterpret_cast<uintptr_t>(&(*(void***){obj})[{index}]);
    const auto it=owner->m_depth_proof_{name}_lookup.find(slot);
    if (it==owner->m_depth_proof_{name}_lookup.end()) {'return E_FAIL;' if result!='void' else 'return;'}
    auto original=it->second->get_original<decltype(D3D12Hook::depth_proof_{name})*>();
    {body}
    {'return result;' if result!='void' else '// original completed'}
}}
'''
    change(root,'src/hooks/D3D12Hook.cpp',
        'thread_local int32_t g_resize_buffers_depth = 0;',
        wrappers+'\nthread_local int32_t g_resize_buffers_depth = 0;')
    change(root,'src/mods/vr/D3D12Component.hpp',
        '#include "d3d12/DIBRPreview.hpp"',
        '#include "d3d12/DIBRPreview.hpp"\n#include "DepthProofObserver.hpp"')
    change(root,'src/mods/vr/D3D12Component.hpp',
        '    d3d12::DIBRPreview m_dibr_depth_capture{};',
        '''    d3d12::DIBRPreview m_dibr_depth_capture{};
    // Intentionally process-lifetime: timed-out/unsubmitted GPU references
    // cannot be released safely merely because the VR runtime is reset.
    uevr::depth_proof::Observer* m_depth_proof{new uevr::depth_proof::Observer{}};
    std::atomic<bool> m_depth_proof_request{false};
    bool m_depth_proof_result_logged{false};
public:
    void request_depth_proof() { m_depth_proof_request.store(true,std::memory_order_release); }
    std::string depth_proof_status() const { return m_depth_proof->session.status(); }
private:''')
    change(root,'src/mods/vr/D3D12Component.cpp',
        'vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {',
        '''vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
    if (m_depth_proof_request.exchange(false,std::memory_order_acq_rel) && vr->is_duoview_renderer_active()) {
        if (const auto& proof_hook=g_framework->get_d3d12_hook(); proof_hook && proof_hook->get_device()) {
            const auto stamp=std::to_string(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
            const auto folder=Framework::get_persistent_dir("depth_proof")/stamp;
            const bool started=m_depth_proof->session.start(proof_hook->get_device(),folder);
            SPDLOG_INFO("[DepthProof] start={} output={} one diagnostic session per game process",started,folder.string());
        }
    }
    if (m_depth_proof->session.started()) {
        if (!vr->is_duoview_renderer_active()) m_depth_proof->session.cancel();
        m_depth_proof->session.service(vr->m_render_frame_count);
        if (!m_depth_proof_result_logged && m_depth_proof->session.export_finished()) {
            SPDLOG_INFO("[DepthProof] {}",m_depth_proof->session.status());
            m_depth_proof_result_logged=true;
        }
    }''')
    change(root,'src/mods/vr/D3D12Component.cpp',
        '        hook->set_depth_stencil_observer(vr->is_dibr_depth_trace_requested() ? &m_dibr_depth_capture : nullptr);',
        '''        hook->set_depth_stencil_observer(m_depth_proof->session.observing()
            ? static_cast<D3D12DepthStencilObserver*>(m_depth_proof)
            : (vr->is_dibr_depth_trace_requested() ? &m_dibr_depth_capture : nullptr));''')
    change(root,'src/mods/VR.cpp',
        '                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");',
        '''                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");
                if (ImGui::TreeNode("Depth proof to disk (experimental)")) {
                    if (ImGui::Button("Capture depth proof (10 seconds, once per game)")) d3d12().request_depth_proof();
                    ImGui::TextWrapped("%s",d3d12().depth_proof_status().c_str());
                    ImGui::TextWrapped("Saves anonymous candidate PGM images, raw float32 Z and a rejection manifest beside the UEVR logs in depth_proof. Output remains Mono. No stereo/view pairing claim.");
                    ImGui::TreePop();
                }''')
    for name in ('DepthProofSession.hpp','DepthProofObserver.hpp'):
        (root/'src/mods/vr'/name).write_bytes((Path(__file__).parent/name).read_bytes())
    print('Independent offline depth proof applied to stable Build49; no compositor/shader modifications')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('backend',type=Path);apply(p.parse_args().backend)
