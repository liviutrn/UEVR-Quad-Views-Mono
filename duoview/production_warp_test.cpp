#include <windows.h>
#include "DuoViewD3D12.hpp"
#include <dxgi1_6.h>
#include <array>
#include <iostream>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
static void check(HRESULT h) { if (FAILED(h)) throw std::runtime_error("D3D12 failure " + std::to_string(static_cast<uint32_t>(h))); }
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES h{}; h.Type=type; h.CreationNodeMask=h.VisibleNodeMask=1; return h;
}
static D3D12_RESOURCE_DESC texture(UINT w, UINT h, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=w; d.Height=h; d.DepthOrArraySize=d.MipLevels=1; d.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    d.SampleDesc.Count=1; d.Flags=flags; return d;
}
static D3D12_RESOURCE_DESC buffer(UINT64 size) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width=size; d.Height=d.DepthOrArraySize=d.MipLevels=1;
    d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR; return d;
}
static ComPtr<ID3D12Resource> resource(ID3D12Device* device, D3D12_RESOURCE_DESC desc,
    D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    auto hp=heap(type); ComPtr<ID3D12Resource> r;
    check(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&r))); return r;
}
static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a,D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b};cmd->ResourceBarrier(1,&barrier);
}
int main() try {
    ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
    D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator;check(device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> cmd;check(device->CreateCommandList(0,q.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));
    auto atlas=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto stereo=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
    auto bad=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_NONE),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COMMON);
    const auto desc=atlas->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{};UINT64 bytes{};
    device->GetCopyableFootprints(&desc,0,1,0,&foot,nullptr,nullptr,&bytes);
    auto upload=resource(device.Get(),buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback=resource(device.Get(),buffer(bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    auto layout=uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.5f,.5f);
    if (!layout) throw std::runtime_error("Invalid test layout");
    void* mapped{};D3D12_RANGE zero{0,0};check(upload->Map(0,&zero,&mapped));std::memset(mapped,0,bytes);
    auto fill=[&](uevr::duoview::Rect r,std::array<uint8_t,4> bgra) {
        for(UINT y=r.y;y<r.y+r.height;++y) for(UINT x=r.x;x<r.x+r.width;++x)
            std::memcpy(static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4,bgra.data(),4);
    };
    fill(layout->fovea,{0,0,255,255}); fill(layout->periphery,{255,0,0,255});upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};from.PlacedFootprint=foot;
    D3D12_TEXTURE_COPY_LOCATION to{atlas.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    uevr::duoview::FrameConfig frame{{1,1},*layout,{.5f,.5f},{},1};frame.settings.feather_fraction=.12f;
    uevr::duoview::dx12::Compositor compositor;
    UINT64 frequency{};check(queue->GetTimestampFrequency(&frequency));
    if (!compositor.prewarm(device.Get(),32,32,false,frequency)) throw std::runtime_error("Timing prewarm failed");
    if (compositor.record(device.Get(),cmd.Get(),atlas.Get(),bad.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,frame)) throw std::runtime_error("Invalid destination accepted");
    if (compositor.recorded_commands()) throw std::runtime_error("Rejected input recorded GPU commands");
    if (!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,frame,frequency)) throw std::runtime_error(compositor.error());
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    from={stereo.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};to={readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};to.PlacedFootprint=foot;
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);check(cmd->Close());
    ID3D12CommandList* lists[]{cmd.Get()};queue->ExecuteCommandLists(1,lists);
    ComPtr<ID3D12Fence> fence;check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));check(queue->Signal(fence.Get(),1));
    auto event=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(fence->SetEventOnCompletion(1,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)throw std::runtime_error("GPU timeout");CloseHandle(event);
    D3D12_RANGE read{0,static_cast<size_t>(bytes)};check(readback->Map(0,&read,&mapped));
    auto sample=[&](UINT x,UINT y) { return static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4; };
    if(sample(16,16)[2]<240 || sample(1,1)[0]<240 || sample(8,16)[2]<5 || sample(8,16)[2]>250) throw std::runtime_error("Production compositor pixels wrong");
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4)) throw std::runtime_error("Mono stereo-copy mismatch");
    readback->Unmap(0,nullptr);
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    frame.key.frame=2;frame.gaze={.75f,.5f};frame.layout=*uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.75f,.5f);
    if (!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,frame,frequency)) throw std::runtime_error(compositor.error());
    if (compositor.gpu_milliseconds()<0.f) throw std::runtime_error("Completed GPU timestamps missing");
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);check(cmd->Close());queue->ExecuteCommandLists(1,lists);check(queue->Signal(fence.Get(),2));
    event=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(fence->SetEventOnCompletion(2,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)throw std::runtime_error("Second GPU timeout");CloseHandle(event);
    check(readback->Map(0,&read,&mapped));
    if(sample(24,16)[2]<240 || sample(8,16)[0]<240) throw std::runtime_error("Moved gaze crop pixels wrong");
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4)) throw std::runtime_error("Reused mono copy mismatch");
    readback->Unmap(0,nullptr);
    // Fused Glamarye strength > 0 must execute the NATIVE two-source pixel
    // shader on a real D3D12 WARP device, then copy exactly one sharpened
    // Mono output to both OpenXR eye halves.
    check(allocator->Reset());
    check(cmd->Reset(allocator.Get(),nullptr));
    auto native_fovea=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto native_periphery=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION sourceAtlas{atlas.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION toFocus{native_fovea.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION toContext{native_periphery.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    cmd->CopyTextureRegion(&toFocus,0,0,0,&sourceAtlas,nullptr);
    const D3D12_BOX contextBox{layout->periphery.x,layout->periphery.y,0,
        layout->periphery.x+layout->periphery.width,
        layout->periphery.y+layout->periphery.height,1};
    cmd->CopyTextureRegion(&toContext,0,0,0,&sourceAtlas,&contextBox);
    transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    transition(cmd.Get(),native_fovea.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    transition(cmd.Get(),native_periphery.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    uevr::duoview::ViewFrame nativeFrame{};
    nativeFrame.config=uevr::duoview::FrameConfig{
        {1,3},*layout,{.5f,.5f},{},2};
    nativeFrame.config.settings.sharpen_strength=.4f;
    nativeFrame.config.settings.fovea_view=0;
    nativeFrame.config.settings.direct_xr_output=true; // fused path must override to single Mono
    if (!compositor.record_native(device.Get(),cmd.Get(),
        native_fovea.Get(),native_periphery.Get(),stereo.Get(),
        D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
        nativeFrame,{},frequency))
        throw std::runtime_error("Native fused Glamarye WARP failed: "+compositor.error());
    if (compositor.last_native_direct_xr())
        throw std::runtime_error("Native fused sharpening erroneously rasterized twice");
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    check(cmd->Close()); queue->ExecuteCommandLists(1,lists);
    check(queue->Signal(fence.Get(),3));
    event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    check(fence->SetEventOnCompletion(3,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
        throw std::runtime_error("Fused native sharpening WARP GPU timeout");
    CloseHandle(event);
    check(readback->Map(0,&read,&mapped));
    if(sample(16,16)[2]<240 || sample(1,1)[0]<240)
        throw std::runtime_error("Fused native fovea/context output corrupted");
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4))
            throw std::runtime_error("Fused native Mono eye duplication mismatch");
    readback->Unmap(0,nullptr);
    // v211: Exercise the EXACT SAME optional NGX depth producer copy, queue
    // submission proof, retained SRV and foveal GPU shader. This WARP test
    // uses a synthetic DLSS input, not an NVIDIA runtime. It cannot prove the
    // game's NGX hook or depth convention, which require headset validation.
    check(allocator->Reset());
    check(cmd->Reset(allocator.Get(),nullptr));
    auto depth_desc=texture(32,32,D3D12_RESOURCE_FLAG_NONE);
    depth_desc.Format=DXGI_FORMAT_R32_FLOAT;
    auto raw_depth=resource(device.Get(),depth_desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT depth_foot{};
    UINT64 depth_bytes{};
    device->GetCopyableFootprints(&depth_desc,0,1,0,&depth_foot,nullptr,nullptr,&depth_bytes);
    auto depth_upload=resource(device.Get(),buffer(depth_bytes),D3D12_HEAP_TYPE_UPLOAD,
                               D3D12_RESOURCE_STATE_GENERIC_READ);
    void* dp{};
    check(depth_upload->Map(0,&zero,&dp));
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x) {
        const float raw=0.5f;
        std::memcpy(static_cast<uint8_t*>(dp)+y*depth_foot.Footprint.RowPitch+x*sizeof(raw),
                    &raw,sizeof(raw));
    }
    depth_upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION depth_from{depth_upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    depth_from.PlacedFootprint=depth_foot;
    D3D12_TEXTURE_COPY_LOCATION depth_to{raw_depth.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    cmd->CopyTextureRegion(&depth_to,0,0,0,&depth_from,nullptr);
    transition(cmd.Get(),raw_depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    auto& samples=uevr::duoview::ngx::candidates();
    samples.clear();
    samples.set_expected(layout->fovea.width,layout->fovea.height,
                         layout->periphery.width,layout->periphery.height);
    uevr::duoview::ngx::DepthCandidate candidate{};
    candidate.feature=static_cast<uintptr_t>(0x12345);
    candidate.output_width=layout->fovea.width;
    candidate.output_height=layout->fovea.height;
    candidate.render_width=layout->fovea.width;
    candidate.render_height=layout->fovea.height;
    candidate.depth_width=32;candidate.depth_height=32;
    candidate.depth_present=true;candidate.color_present=true;
    samples.observe(candidate);
    auto pick=samples.choose();
    if(!pick.exact || pick.source[0]!=candidate.feature)
        throw std::runtime_error("Synthetic NGX output was not recognized as the frozen fovea");
    auto& pool=uevr::duoview::ngx::depth_snapshots();
    if(!pool.bind_queue(queue.Get()))throw std::runtime_error("WARP depth queue was rejected");
    pool.set_enabled(true);
    const uevr::duoview::FrameKey depth_key{1,4};
    pool.capture(cmd.Get(),raw_depth.Get(),candidate,depth_key);
    if(pool.captures()==0)throw std::runtime_error("Depth copy not recorded");
    check(cmd->Close());
    queue->ExecuteCommandLists(1,lists);
    pool.submitted(queue.Get(),1,lists);
    if(pool.submits()==0)throw std::runtime_error("Depth producer submission was not verified");
    if(pool.find(device.Get(),queue.Get(),{1,5},candidate.feature,candidate.output_width,candidate.output_height) ||
       pool.find(device.Get(),nullptr,depth_key,candidate.feature,candidate.output_width,candidate.output_height))
        throw std::runtime_error("Unproven producer frame or missing queue improperly accepted");
    check(queue->Signal(fence.Get(),4));
    event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    check(fence->SetEventOnCompletion(4,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
        throw std::runtime_error("Synthetic NGX depth producer timed out");
    CloseHandle(event);

    nativeFrame.config.key=depth_key;
    nativeFrame.projection[14]=10.f; // 10 cm near plane -> 0.10 metres
    nativeFrame.config.settings.distance_sharpen_enabled=true;
    nativeFrame.config.settings.sharpen_strength=0.f; // depth curve must still use the single Mono raster
    nativeFrame.config.settings.sharpen_near_strength=5.f;
    nativeFrame.config.settings.sharpen_far_strength=1.f;
    nativeFrame.config.settings.sharpen_near_m=.10f;
    nativeFrame.config.settings.sharpen_far_m=.50f;
    nativeFrame.config.settings.sharpen_distance_smooth=false;
    nativeFrame.config.settings.depth_reversed_z=true;
    auto depth_draw=[&](uint32_t preview,UINT64 signal) {
        check(allocator->Reset());
        check(cmd->Reset(allocator.Get(),nullptr));
        nativeFrame.config.settings.depth_preview_mode=preview;
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
        if(!compositor.record_native(device.Get(),cmd.Get(),
                native_fovea.Get(),native_periphery.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                nativeFrame,{},frequency,queue.Get()))
            throw std::runtime_error("v211 WARP depth compositor rejected: "+compositor.error());
        if(compositor.last_native_direct_xr())
            throw std::runtime_error("Distance sharpening mistakenly rasterized twice to XR");
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
        cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        check(cmd->Close());queue->ExecuteCommandLists(1,lists);
        check(queue->Signal(fence.Get(),signal));
        auto done=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        check(fence->SetEventOnCompletion(signal,done));
        if(WaitForSingleObject(done,30000)!=WAIT_OBJECT_0)
            throw std::runtime_error("WARP live depth compositor timeout");
        CloseHandle(done);
        check(readback->Map(0,&read,&mapped));
        const auto pixel=sample(16,16);
        const int red=pixel[2],green=pixel[1],blue=pixel[0];
        for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
            if(std::memcmp(sample(x,y),sample(x+32,y),4))
                throw std::runtime_error("Depth shader broke Mono eye duplication");
        readback->Unmap(0,nullptr);
        if(std::abs(red-green)>2 || std::abs(red-blue)>2)
            throw std::runtime_error("Depth preview failed to write grayscale in fovea");
        return red;
    };
    const int raw_grey=depth_draw(1,5);
    if(raw_grey<120 || raw_grey>136)
        throw std::runtime_error("Raw depth should be .5 (128 grey), got "+std::to_string(raw_grey));
    const int distance_grey=depth_draw(2,6);
    // reversed Z 0.5 with 10 cm near => 0.20 m. Ramp [.10,.50] -> 0.25.
    if(distance_grey<56 || distance_grey>72)
        throw std::runtime_error("Metric depth blend should be 0.25 (64 grey), got "+std::to_string(distance_grey));
    // If Unreal projection metadata is missing, NGX raw depth must still be
    // visible. Metric preview then fails explicitly, not as a normal image.
    nativeFrame.projection[14]=0.f;
    const int raw_no_near=depth_draw(1,7);
    if(raw_no_near<120 || raw_no_near>136)
        throw std::runtime_error("Raw NGX preview incorrectly required a metric near plane");
    nativeFrame.projection[14]=10.f;
    // Real game NGX can run outside UE's RHI-command ticket. This full GPU
    // regression exercises repair only with matching physical NGX Output.
    check(allocator->Reset());
    check(cmd->Reset(allocator.Get(),nullptr));
    const auto prior_unkeyed=pool.unkeyed_captures();
    pool.capture(cmd.Get(),raw_depth.Get(),candidate,{},native_fovea.Get());
    if(pool.unkeyed_captures()!=prior_unkeyed+1)
        throw std::runtime_error("Unscoped NGX Output depth not captured");
    check(cmd->Close());queue->ExecuteCommandLists(1,lists);
    pool.submitted(queue.Get(),1,lists);
    if(pool.find_by_output(device.Get(),queue.Get(),native_periphery.Get(),
           candidate.feature,candidate.output_width,candidate.output_height))
        throw std::runtime_error("Non-foveal NGX Output accepted");
    if(pool.find_by_output(device.Get(),nullptr,native_fovea.Get(),
           candidate.feature,candidate.output_width,candidate.output_height))
        throw std::runtime_error("NGX Output without original queue accepted");
    nativeFrame.config.key={1,5}; // intentionally NOT the RHI depth key
    const int output_proven_raw=depth_draw(1,9);
    if(output_proven_raw<120 || output_proven_raw>136 || pool.output_matches()==0)
        throw std::runtime_error("Physical NGX Output failed foveal depth preview");
    if(pool.find_by_output(device.Get(),queue.Get(),native_fovea.Get(),
           candidate.feature,candidate.output_width,candidate.output_height))
        throw std::runtime_error("Old NGX Output snapshot was replayed");
    // Simulate a missing Eval ticket but an EXACT per-command-list RHI
    // packet found on actual ExecuteCommandLists. Physical output differs.
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    const auto prior_late=pool.late_tickets();
    pool.capture(cmd.Get(),raw_depth.Get(),candidate,{},native_periphery.Get());
    check(cmd->Close());queue->ExecuteCommandLists(1,lists);
    const uevr::duoview::FrameKey late_key{1,6};
    pool.submitted(queue.Get(),1,lists,late_key);
    if(pool.late_tickets()!=prior_late+1)
        throw std::runtime_error("Actual NGX command-list late ticket was not attached");
    if(pool.find(device.Get(),queue.Get(),{1,7},
       candidate.feature,candidate.output_width,candidate.output_height))
        throw std::runtime_error("Late ticket accepted wrong render frame");
    nativeFrame.config.key=late_key;
    const int late_grey=depth_draw(1,11);
    if(late_grey<120 || late_grey>136)
        throw std::runtime_error("NGX submit-time producer ticket did not reach the shader");
    // Regression: Unreal final BGRA fovea need not equal NGX HDR Output.
    // Demonstrate useful raw depth from an actual submitted producer copy
    // under a unique exact source, without falsely assigning a frame ticket.
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    const auto prior_ordered=pool.ordered_matches();
    pool.capture(cmd.Get(),raw_depth.Get(),candidate,{},native_periphery.Get());
    check(cmd->Close());queue->ExecuteCommandLists(1,lists);
    pool.submitted(queue.Get(),1,lists);
    if(pool.find_recent_ordered(device.Get(),nullptr,candidate.feature,
           candidate.output_width,candidate.output_height))
        throw std::runtime_error("Ordered depth accepted a missing GPU queue");
    if(pool.find_recent_ordered(device.Get(),queue.Get(),candidate.feature,
           candidate.output_width+1,candidate.output_height))
        throw std::runtime_error("Ordered depth accepted wrong fovea dimensions");
    nativeFrame.config.key={1,8};
    const int ordered_grey=depth_draw(1,12);
    if(ordered_grey<120 || ordered_grey>136 || pool.ordered_matches()!=prior_ordered+1)
        throw std::runtime_error("Valid ordered NGX depth not visible through fovea");
    if(pool.find_recent_ordered(device.Get(),queue.Get(),candidate.feature,
           candidate.output_width,candidate.output_height))
        throw std::runtime_error("Already-used ordered NGX depth improperly replayed");
    // The legacy atlas/gather compositor is a possible source-format
    // fallback. It must show magenta for requested depth preview rather than
    // silently displaying normal image when NGX is unavailable.
    check(allocator->Reset());
    check(cmd->Reset(allocator.Get(),nullptr));
    frame.settings.depth_preview_mode=1;
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    if(!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),
            D3D12_RESOURCE_STATE_RENDER_TARGET,frame,frequency))
        throw std::runtime_error("Legacy depth-unavailable preview raster failed: "+compositor.error());
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    check(cmd->Close());queue->ExecuteCommandLists(1,lists);
    check(queue->Signal(fence.Get(),14));
    event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    check(fence->SetEventOnCompletion(14,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
        throw std::runtime_error("Legacy missing-depth preview GPU timeout");
    CloseHandle(event);
    check(readback->Map(0,&read,&mapped));
    const auto missing=sample(24,16); // inside the moved fovea
    if(missing[0]<245 || missing[1]>8 || missing[2]<245)
        throw std::runtime_error("Legacy preview silently hid missing NGX depth instead of magenta");
    for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4))
            throw std::runtime_error("Legacy missing-depth preview broke Mono duplication");
    readback->Unmap(0,nullptr);
    frame.settings.depth_preview_mode=0;
    if(pool.used()<2)throw std::runtime_error("Depth was copied but never used by the compositor");
    std::cout<<"v212 NGX GPU copy, negative-provenance checks, compositor usage, raw/metric preview: PASS\\n";
    std::cout << "Native fused Glamarye WARP path, focus-only, no duplicate full XR pass: PASS\\n";
    std::cout << "Production shader, BGRA8 raster, moved gaze, retired-slot reuse, GPU timestamps: 2048 exact pixel pairs PASS\n";
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
