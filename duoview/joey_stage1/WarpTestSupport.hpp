#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include "DuoViewD3D12.hpp"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <array>
#include <cstring>
#include <memory>
#include <vector>
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
struct NativeSource {
    ComPtr<ID3D12Resource> texture;
    ComPtr<ID3D12Resource> upload;
};
static NativeSource native_source(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                                  UINT width, UINT height, std::array<uint8_t,4> bgra,
                                  bool gradient = false, UINT gradient_offset = 0,
                                  DXGI_FORMAT resource_format = DXGI_FORMAT_B8G8R8A8_TYPELESS) {
    auto desc=texture(width,height,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    desc.Format=resource_format;
    NativeSource result;
    result.texture=resource(device,desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 bytes{};
    device->GetCopyableFootprints(&desc,0,1,0,&footprint,nullptr,nullptr,&bytes);
    footprint.Footprint.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    result.upload=resource(device,buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped{};D3D12_RANGE zero{0,0};check(result.upload->Map(0,&zero,&mapped));
    std::memset(mapped,0,bytes);
    for(UINT y=0;y<height;++y) for(UINT x=0;x<width;++x) {
        auto pixel=bgra;
        if (gradient) {
            pixel={static_cast<uint8_t>((x*17+gradient_offset*11)&255),
                   static_cast<uint8_t>((y*23+gradient_offset*7)&255),
                   static_cast<uint8_t>((x*3+y*5+gradient_offset*13)&255),255};
        }
        std::memcpy(static_cast<uint8_t*>(mapped)+y*footprint.Footprint.RowPitch+x*4,pixel.data(),4);
    }
    result.upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{result.upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    from.PlacedFootprint=footprint;
    D3D12_TEXTURE_COPY_LOCATION to{result.texture.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    transition(cmd,result.texture.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    return result;
}
// R5 captures are copied to R32_FLOAT texture with pixel and non-pixel SRV state.
// WARP uses synthetic reversed-Z so the per-eye compositor can be evaluated
// without modifying a game-owned DSV or relying on a live Unreal scene.
static NativeSource native_depth(ID3D12Device* device,ID3D12GraphicsCommandList* cmd,
                                 UINT width,UINT height,float deviceZ,
                                 std::optional<uevr::duoview::DepthViewport> active=std::nullopt) {
    auto desc=texture(width,height,D3D12_RESOURCE_FLAG_NONE);
    desc.Format=DXGI_FORMAT_R32_FLOAT;
    NativeSource result;
    result.texture=resource(device,desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{}; UINT64 bytes{};
    device->GetCopyableFootprints(&desc,0,1,0,&foot,nullptr,nullptr,&bytes);
    result.upload=resource(device,buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped{};D3D12_RANGE zero{0,0};check(result.upload->Map(0,&zero,&mapped));
    std::memset(mapped,0,static_cast<size_t>(bytes));
    for(UINT y=0;y<height;++y)for(UINT x=0;x<width;++x) {
        const float value=active && (x<active->x || y<active->y ||
            x>=active->x+active->width || y>=active->y+active->height) ? .9f : deviceZ;
        std::memcpy(static_cast<uint8_t*>(mapped)+size_t(y)*foot.Footprint.RowPitch+x*4,&value,4);
    }
    result.upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{result.upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    from.PlacedFootprint=foot;
    D3D12_TEXTURE_COPY_LOCATION to{result.texture.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    transition(cmd,result.texture.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    return result;
}
