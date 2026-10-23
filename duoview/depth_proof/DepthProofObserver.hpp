#pragma once
#include <hooks/D3D12Hook.hpp>
#include "DepthProofSession.hpp"
namespace uevr::depth_proof {
class Observer final : public D3D12DepthStencilObserver {
public:
    Session session;
    void on_depth_stencil_view_created(ID3D12Resource*,const D3D12_DEPTH_STENCIL_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE) override {}
    void on_resource_barriers(ID3D12GraphicsCommandList* c,UINT n,const D3D12_RESOURCE_BARRIER* b) override { session.barriers(c,n,b); }
    void on_command_list_reset(ID3D12GraphicsCommandList* c) override { session.reset(c); }
    void on_begin_render_pass(ID3D12GraphicsCommandList* c,D3D12_RENDER_PASS_FLAGS f) override { session.begin_pass(c,f); }
    void on_end_render_pass(ID3D12GraphicsCommandList* c) override { session.end_pass(c); }
    void on_command_lists_submitting(ID3D12CommandQueue* q,UINT n,ID3D12CommandList* const* c) override { session.submitting(q,n,c); }
    void on_command_lists_submitted(ID3D12CommandQueue* q,UINT n,ID3D12CommandList* const* c) override { session.submitted(q,n,c); }
};
}
