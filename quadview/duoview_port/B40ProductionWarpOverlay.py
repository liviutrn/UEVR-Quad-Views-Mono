#!/usr/bin/env python3
"""Generate a temporary B40-enabled variant of V208SharedEyeWarp.cpp.

The checked-in production contract stays unchanged; this overlay reuses its WARP
device, source textures, command submission, readback, pixel checks and debug-layer
validation, then exercises the production Native record/dispatch/draw path.
"""
from pathlib import Path
import argparse


MARKER = "    a.reset(); b.reset(); c.reset();\n"
BLOCK = r'''    // B40 regression: the exact production Native compositor, on WARP.
    // The solid fovea/periphery colors create a known positive red correction
    // just outside the crop. Controlled time steps must make that pixel change.
    auto b40_history=uevr::duoview::dx12::B40MonoHistory::create(g.device.Get(),g.queue.Get());
    if (!b40_history || !b40_history->buffer) throw std::runtime_error("B40 history allocation failed");
    a->set_b40_history(b40_history);
    frame.config.settings.seam_match_enabled=true;
    frame.config.settings.seam_strength=1.0f;
    frame.config.settings.seam_limit=0.5f;
    frame.config.settings.seam_reach_px=240.0f;
    frame.config.settings.seam_time_ms=250;
    b40_overlay_mode=true;
    a->set_b40_test_timestamp_ms(1000u);
    run(*a,true,Route::copy,"B40 frame 1: initialize history and draw");
    const uint8_t red0=b40_probe;
    a->set_b40_test_timestamp_ms(1016u);
    run(*a,true,Route::copy,"B40 frame 2: stable history and draw");
    const uint8_t red1=b40_probe;
    a->set_b40_test_timestamp_ms(1400u);
    run(*a,true,Route::copy,"B40 frame 3: elapsed-time clamp path and draw");
    const uint8_t red2=b40_probe;
    if (!(red0<red1 && red1<red2))
        throw std::runtime_error("B40 outside-crop red correction did not increase across controlled timestamps: "+
            std::to_string(red0)+", "+std::to_string(red1)+", "+std::to_string(red2));
    std::cout << "PASS: B40 outside-crop red response " << unsigned(red0) << " -> "
              << unsigned(red1) << " -> " << unsigned(red2) << "\n";
    b40_overlay_mode=false;
    a->set_b40_history({});
    b40_history.reset();

    frame.config.settings.seam_match_enabled=false;
    frame.config.settings.synthetic_stereo=true;
    frame.config.settings.stereo_near_m=0.f;
    m1_geometry.world_to_meters=1.f;
    m1_geometry.depth_coefficients={0.f,1.f,1.f};
    m1_geometry.k={.25f,-.25f};
    for (auto& h : m1_geometry.context_h) h={1,0,0,0, 0,1,0,0, 0,0,1,0};
    run(*a,false,Route::direct,"M1 zero disparity fallback");
    const auto unwarped=m1_probe;
    if (unwarped[0]!=unwarped[1])
        throw std::runtime_error("M1 infinity views differed despite identical test frusta");

    const auto depth_desc=texture(32,32,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_NONE);
    auto depth=resource(g.device.Get(),depth_desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT depth_foot{}; UINT64 depth_bytes{};
    g.device->GetCopyableFootprints(&depth_desc,0,1,0,&depth_foot,nullptr,nullptr,&depth_bytes);
    depth_foot.Footprint.Format=DXGI_FORMAT_R32_FLOAT;
    auto depth_upload=resource(g.device.Get(),buffer(depth_bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* depth_map{};
    const D3D12_RANGE no_reads{0,0};
    check(depth_upload->Map(0,&no_reads,&depth_map));
    for (UINT y=0;y<32;++y) {
        auto* row=reinterpret_cast<float*>(static_cast<uint8_t*>(depth_map)+y*depth_foot.Footprint.RowPitch);
        for (UINT x=0;x<32;++x) row[x]=.5f; // flat 2 m plane
    }
    depth_upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION depth_from{depth_upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    depth_from.PlacedFootprint=depth_foot;
    D3D12_TEXTURE_COPY_LOCATION depth_to{depth.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    g.cmd->CopyTextureRegion(&depth_to,0,0,0,&depth_from,nullptr);
    transition(g.cmd.Get(),depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE);
    g.submit_and_wait();
    m1_depth={depth.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},std::make_shared<const int>(1)};
    run(*a,false,Route::direct,"M1 conditioned depth and opposite shifts");
    if (!(m1_probe[0]>200 && m1_probe[1]<40))
        throw std::runtime_error("M1 eye warps did not sample opposite sides of the fovea boundary");
    frame.config.settings.synthetic_stereo=false;
    run(*a,true,Route::copy,"Mono after M1 toggle OFF");

'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True, help="Pinned V208SharedEyeWarp.cpp")
    ap.add_argument("--output", type=Path, required=True, help="Temporary generated C++ file")
    args = ap.parse_args()
    source = args.source.read_text(encoding="utf-8")
    prelude = "    std::vector<uint8_t> reference;\n"
    if source.count(MARKER) != 1 or source.count(prelude) != 1:
        raise SystemExit("Expected unique WARP insertion points")
    gpu = """    void submit_and_wait() {
        check(cmd->Close());"""
    if source.count(gpu) != 1:
        raise SystemExit("Expected a unique GPU submit function")
    source = source.replace(gpu, """    void verify(HRESULT result, const char* stage) {
        if (SUCCEEDED(result)) return;
        std::cerr << stage << " HRESULT=" << std::hex << uint32_t(result)
                  << " device reason=" << uint32_t(device->GetDeviceRemovedReason()) << std::dec << "\\n";
        ComPtr<ID3D12InfoQueue> debug;
        if (SUCCEEDED(device.As(&debug))) {
            for (UINT64 i=0;i<debug->GetNumStoredMessages();++i) {
                SIZE_T length{};
                debug->GetMessage(i,nullptr,&length);
                if (!length) continue;
                std::vector<uint8_t> bytes(length);
                auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());
                if (SUCCEEDED(debug->GetMessage(i,message,&length)) &&
                    message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)
                    std::cerr << message->pDescription << "\\n";
            }
        }
        check(result);
    }
    void submit_and_wait() {
        verify(cmd->Close(),"Close");""", 1)
    source = source.replace("check(queue->Signal(fence.Get(),++value));",
                            'verify(queue->Signal(fence.Get(),++value),"Signal");', 1)
    source = source.replace("check(fence->SetEventOnCompletion(value,event));",
                            'verify(fence->SetEventOnCompletion(value,event),"SetEventOnCompletion");', 1)
    source = source.replace("check(allocator->Reset()); check(cmd->Reset(allocator.Get(),nullptr));",
                            'verify(device->GetDeviceRemovedReason(),"Post-fence device status");\n'
                            '        verify(allocator->Reset(),"Reset allocator");\n'
                            '        verify(cmd->Reset(allocator.Get(),nullptr),"Reset list");', 1)
    source = source.replace("        const float green[4]", '        std::cout << "RUN: " << name << std::endl;\n'
                            "        const float green[4]", 1)
    source = source.replace(prelude, prelude + """    bool b40_overlay_mode=false;
    uint8_t b40_probe{};
    uevr::duoview::stereo::Geometry m1_geometry{};
    uevr::duoview::dx12::M1DepthInput m1_depth{};
    std::array<uint8_t,2> m1_probe{};
""", 1)
    native = """                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,std::make_shared<const int>(1),0);
        if (!ok)"""
    if source.count(native) != 1:
        raise SystemExit("Expected a unique Native record call in the pinned fixture")
    source = source.replace(native, """                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,std::make_shared<const int>(1),0,
                frame.config.settings.synthetic_stereo ? &m1_geometry : nullptr,
                m1_depth.texture ? &m1_depth : nullptr);
        if (frame.config.settings.synthetic_stereo &&
            (!c.last_stereo_output() || c.last_stereo_depth()!=bool(m1_depth.texture)))
            throw std::runtime_error("Wrong M1 recording path");
        if (!ok)""", 1)
    source = source.replace("if (!shared && !right_copy)", "if (!shared && !right_copy && !frame.config.settings.synthetic_stereo)", 1)
    source = source.replace(
        "        readback->Unmap(0,nullptr);\n        // Routes use different (proven) shaders; allow 2 levels of rounding.\n",
        "        if (b40_overlay_mode) b40_probe=px(6,16)[2]; // BGRA byte 2 is red, outside the crop.\n"
        "        if (frame.config.settings.synthetic_stereo) m1_probe={px(8,16)[2],px(40,16)[2]};\n"
        "        readback->Unmap(0,nullptr);\n"
        "        // Routes use different (proven) shaders; allow 2 levels of rounding.\n", 1)
    source = source.replace(
        "        if (reference.empty()) reference=left;\n        else for (size_t i=0;i<left.size();++i)\n",
        "        if (reference.empty()) reference=left;\n"
        "        else if (!b40_overlay_mode && !frame.config.settings.synthetic_stereo) for (size_t i=0;i<left.size();++i)\n", 1)
    gather = '    run(*a,true,Route::gather,"v208 shared gather fallback route");\n'
    if source.count(gather) != 1:
        raise SystemExit("Expected one gather route in pinned fixture")
    source = source.replace(gather, "", 1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source.replace(MARKER, BLOCK + gather + MARKER), encoding="utf-8")
    print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
