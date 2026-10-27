#pragma once
// Two independent R5 capture state machines receiving the same D3D12 stream.
// Each may accept only its own expected (viewport-proven) source extent.
// This is not proof of a matching RGB draw unless the caller also validates
// source packet identity, frame scope, and mutually exclusive extents.
#include "d3d12/StockDibrDepth.hpp"
namespace uevr::duoview::r5 {
class DualDepth final : public D3D12DepthStencilObserver {
public:
    stock_dibr::DepthCapture fovea{};
    stock_dibr::DepthCapture periphery{};
    void configure(ID3D12Device* dev, ID3D12CommandQueue* q,
                   uint32_t fw,uint32_t fh,uint32_t pw,uint32_t ph,bool enabled) {
        // R5 uses 'double-wide color width' to establish the single-eye
        // viewport width. Never truncate or infer it from a depth allocation.
        const bool distinct=fw && fh && pw && ph &&
            (fw>pw+16 || pw>fw+16 || fh>ph+16 || ph>fh+16);
        fovea.configure(dev,q,uint64_t(fw)*2,fh,enabled && distinct);
        periphery.configure(dev,q,uint64_t(pw)*2,ph,enabled && distinct);
    }
    bool accepts_cached_dsv_metadata() const override { return true; }
    bool has_pending_retirement() override {
        return fovea.has_pending_retirement() || periphery.has_pending_retirement();
    }
    void on_depth_stencil_view_created(ID3D12Resource* r,
        const D3D12_DEPTH_STENCIL_VIEW_DESC* d,D3D12_CPU_DESCRIPTOR_HANDLE h) override {
        fovea.on_depth_stencil_view_created(r,d,h);
        periphery.on_depth_stencil_view_created(r,d,h);
    }
    void on_resource_barriers(ID3D12GraphicsCommandList* c,UINT n,
        const D3D12_RESOURCE_BARRIER* b) override {
        fovea.on_resource_barriers(c,n,b); periphery.on_resource_barriers(c,n,b);
    }
    void on_post_resource_barriers(ID3D12GraphicsCommandList* c,UINT n,
        const D3D12_RESOURCE_BARRIER* b) override {
        fovea.on_post_resource_barriers(c,n,b); periphery.on_post_resource_barriers(c,n,b);
    }
    void on_render_targets(ID3D12GraphicsCommandList* c,UINT n,
        D3D12_CPU_DESCRIPTOR_HANDLE d) override {
        fovea.on_render_targets(c,n,d); periphery.on_render_targets(c,n,d);
    }
    void on_viewports(ID3D12GraphicsCommandList* c,UINT n,
        const D3D12_VIEWPORT* vp) override {
        fovea.on_viewports(c,n,vp); periphery.on_viewports(c,n,vp);
    }
    void on_render_pass(ID3D12GraphicsCommandList* c,bool begin) override {
        fovea.on_render_pass(c,begin); periphery.on_render_pass(c,begin);
    }
    void on_command_list_reset(ID3D12GraphicsCommandList* c) override {
        fovea.on_command_list_reset(c); periphery.on_command_list_reset(c);
    }
    void on_command_lists_executed(ID3D12CommandQueue* q,UINT n,
        ID3D12CommandList*const* ls) override {
        fovea.on_command_lists_executed(q,n,ls);
        periphery.on_command_lists_executed(q,n,ls);
    }
    void finish_frame() {fovea.finish_frame();periphery.finish_frame();}
    void reset() {fovea.reset();periphery.reset();}
};
}
