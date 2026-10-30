#define main ci75_fixture_entry_unused
#include "../ci75/recorder_gpu_tests.cpp"
#undef main

int main()try {
    GPU gpu;
    std::vector<uint8_t> color(128*64*4,127);
    auto xr=gpu.texture(128,64,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_STATE_RENDER_TARGET,color,4);
    for(const auto format:{DXGI_FORMAT_R32_TYPELESS,DXGI_FORMAT_R16_FLOAT,DXGI_FORMAT_R16_TYPELESS,
                           DXGI_FORMAT_R24G8_TYPELESS,DXGI_FORMAT_R32G8X24_TYPELESS,DXGI_FORMAT_R16G16_FLOAT,DXGI_FORMAT_R32G32_FLOAT}) {
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=64;d.Height=64;
        d.DepthOrArraySize=d.MipLevels=1;d.SampleDesc.Count=1;d.Format=format;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows{};UINT64 row_bytes{},total{};
        gpu.device->GetCopyableFootprints(&d,0,1,0,&fp,&rows,&row_bytes,&total);
        if(!row_bytes||row_bytes>512)throw std::runtime_error("unsupported probe layout");
        const UINT bpp=UINT(row_bytes/64);std::vector<uint8_t> input(size_t(row_bytes)*64,0);
        for(size_t p=0;p<4096;++p) {
            if(format==DXGI_FORMAT_R16_FLOAT||format==DXGI_FORMAT_R16_TYPELESS) {
                const uint16_t value=(p%2)?0x3800u:0x3000u;std::memcpy(input.data()+p*bpp,&value,2);
            } else if(format==DXGI_FORMAT_R24G8_TYPELESS) {
                const uint32_t value=(p%2)?0x800000u:0x400000u;std::memcpy(input.data()+p*bpp,&value,4);
            } else if(format==DXGI_FORMAT_R16G16_FLOAT) {
                const uint32_t value=0xb8003800u;std::memcpy(input.data()+p*bpp,&value,4);
            } else {
                const float value=(p%2)?.5f:.25f;std::memcpy(input.data()+p*bpp,&value,4);
                if(format==DXGI_FORMAT_R32G32_FLOAT){const float second=-.125f;std::memcpy(input.data()+p*bpp+4,&second,4);}
            }
        }
        auto resource=gpu.texture(64,64,format,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,input,bpp);
        Source source;source.name="depth_left";source.resource=resource;source.state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        source.active={5,7,50,48};source.u=.63f;source.v=.42f;source.extent=16;source.required=true;
        auto recorder=std::make_shared<Recorder>(75002,0,1,2000);
        auto frame=recorder->stage(gpu.device.Get(),{source},1);
        if(!frame||!recorder->record(gpu.list.Get(),frame,xr.Get()))throw std::runtime_error("format rejected");
        gpu.flush();const auto& p=frame->planes[0];
        void* mapped{};D3D12_RANGE range{0,SIZE_T(p.capacity)};hr(p.readback->Map(0,&range,&mapped),"map probe");
        const size_t meaningful=format==DXGI_FORMAT_R32G8X24_TYPELESS?4:bpp;
        for(UINT y=0;y<p.height;++y)for(UINT x=0;x<p.width;++x) {
            const auto* actual=static_cast<const uint8_t*>(mapped)+size_t(y)*p.footprint.Footprint.RowPitch+size_t(x)*bpp;
            const auto* expected=input.data()+((size_t(p.box.top+y)*64)+p.box.left+x)*bpp;
            if(std::memcmp(actual,expected,meaningful))throw std::runtime_error("format numerical bits changed");
        }
        D3D12_RANGE empty{0,0};p.readback->Unmap(0,&empty);
        std::cout<<"PASS DXGI="<<int(format)<<" footprint="<<int(p.footprint.Footprint.Format)
            <<" bytesPerPixel="<<bpp<<" offset active subrect and cropped GPU readback exact\n";
    }
    ComPtr<ID3D12InfoQueue> info;if(SUCCEEDED(gpu.device.As(&info)))
        for(UINT64 i=0;i<info->GetNumStoredMessages();++i){SIZE_T size{};info->GetMessage(i,nullptr,&size);
            std::vector<uint8_t> bytes(size);auto* msg=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());info->GetMessage(i,msg,&size);
            if(msg->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(msg->pDescription);}
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
