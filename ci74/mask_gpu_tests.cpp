// Execute the actual production CI73 mask functions on a WARP GPU.
// A diagnostic entry point isolates mask coordinates from reconstruction;
// no mask implementation is copied into the test shader.
#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d3d11shader.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>
using Microsoft::WRL::ComPtr;
static void need(bool b,const char* s) { if(!b)throw std::runtime_error(s); }
static void hr(HRESULT h,const char* s) { need(SUCCEEDED(h),s); }
constexpr unsigned W=128,H=96,DW=24,DH=24,RX=3,RY=5,RW=16,RH=12;
static ComPtr<ID3DBlob> compile(const std::string& text,const char* name,const char* entry,const char* target) {
    ComPtr<ID3DBlob> code,errors;
    const auto result=D3DCompile(text.data(),text.size(),name,nullptr,
        D3D_COMPILE_STANDARD_FILE_INCLUDE,entry,target,
        D3DCOMPILE_ENABLE_STRICTNESS|D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&code,&errors);
    if(FAILED(result)&&errors)std::cerr<<static_cast<const char*>(errors->GetBufferPointer());
    hr(result,"production shader compilation");return code;
}
int main(int argc,char** argv)try {
    need(argc==2||argc==3,"usage: mask_gpu_tests PRODUCTION_SHADER [--expect-regression]");
    const bool expect_regression=argc==3&&std::string(argv[2])=="--expect-regression";
    const auto shader=std::filesystem::absolute(argv[1]);
    std::ifstream in(shader);need(bool(in),"production shader missing");
    std::string source((std::istreambuf_iterator<char>(in)),{});
    source+=R"(
float4 CI74MaskProbe(float4 pos:SV_POSITION):SV_TARGET {
    const float2 uv=pos.xy/float2(128,96);
    return float4(CI73ProtectedNear(uv)?1.f:0.f,
                  CI73RightDepthEdge(uv)?1.f:0.f,0,1);
}
)";
    std::filesystem::current_path(shader.parent_path());
    const auto psCode=compile(source,shader.string().c_str(),"CI74MaskProbe","ps_5_0");
    const auto vsCode=compile(R"(
float4 VS(uint id:SV_VertexID):SV_POSITION {
    float2 p=float2((id<<1)&2,id&2);
    return float4(p*float2(2,-2)+float2(-1,1),0,1);
})","probe_vs","VS","vs_5_0");
    ComPtr<ID3D11Device> dev;ComPtr<ID3D11DeviceContext> ctx;
    D3D_FEATURE_LEVEL level{};
    hr(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,
        D3D11_SDK_VERSION,&dev,&level,&ctx),"D3D11 WARP device");
    ComPtr<ID3D11PixelShader> ps;ComPtr<ID3D11VertexShader> vs;
    hr(dev->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&ps),"PS");
    hr(dev->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs),"VS");
    ComPtr<ID3D11ShaderReflection> refl;
    hr(D3DReflect(psCode->GetBufferPointer(),psCode->GetBufferSize(),IID_PPV_ARGS(&refl)),"reflection");
    auto* cb=refl->GetConstantBufferByName("DuoViewCompositeConfig");
    D3D11_SHADER_BUFFER_DESC cbd{};hr(cb->GetDesc(&cbd),"b0 reflection");
    need(cbd.Size==240,"production b0 ABI changed");
    std::array<unsigned char,240> constants{};
    auto set=[&](const char* name,std::initializer_list<float> values,bool optional=false) {
        D3D11_SHADER_VARIABLE_DESC d{};
        const auto result=cb->GetVariableByName(name)->GetDesc(&d);
        if(FAILED(result)&&optional)return;
        hr(result,name);need(d.StartOffset+values.size()*4<=constants.size(),"constant overflow");
        std::memcpy(constants.data()+d.StartOffset,values.begin(),values.size()*4);
    };
    D3D11_BUFFER_DESC bd{};bd.ByteWidth=240;bd.Usage=D3D11_USAGE_DEFAULT;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    ComPtr<ID3D11Buffer> buffer;hr(dev->CreateBuffer(&bd,nullptr,&buffer),"constant buffer");
    D3D11_TEXTURE2D_DESC td{};td.Width=W;td.Height=H;td.MipLevels=td.ArraySize=1;
    td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;td.SampleDesc.Count=1;
    td.Usage=D3D11_USAGE_DEFAULT;td.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> output,readback;
    hr(dev->CreateTexture2D(&td,nullptr,&output),"output");
    td.Usage=D3D11_USAGE_STAGING;td.BindFlags=0;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    hr(dev->CreateTexture2D(&td,nullptr,&readback),"readback");
    ComPtr<ID3D11RenderTargetView> rtv;hr(dev->CreateRenderTargetView(output.Get(),nullptr,&rtv),"RTV");
    D3D11_VIEWPORT vp{0,0,float(W),float(H),0,1};ctx->RSSetViewports(1,&vp);
    ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx->VSSetShader(vs.Get(),nullptr,0);ctx->PSSetShader(ps.Get(),nullptr,0);
    auto* target=rtv.Get();ctx->OMSetRenderTargets(1,&target,nullptr);
    auto* b=buffer.Get();ctx->PSSetConstantBuffers(0,1,&b);
    const std::array<std::array<float,2>,9> phases{{{0,0},{.49f,.37f},{-.49f,-.37f},
        {.37f,-.49f},{-.37f,.49f},{.125f,.25f},{-.25f,.125f},{.499f,-.499f},{-.499f,.499f}}};
    uint64_t errors=0,checks=0,nonzero_phase_errors=0,zero_phase_errors=0;
    for(bool reversed:{false,true})for(unsigned scene=0;scene<3;++scene)for(auto jitter:phases) {
        std::vector<float> depth(DW*DH,-1.f);
        // Independent raster input: subpixel-jittered sample rays hit a
        // vertical or diagonal foreground silhouette. The padded allocation
        // deliberately differs from active input and output dimensions.
        for(unsigned y=0;y<RH;++y)for(unsigned x=0;x<RW;++x) {
            const float u=(float(x)+.5f-jitter[0])/RW;
            const float v=(float(y)+.5f-jitter[1])/RH;
            const bool foreground=scene==0?u<.47f:scene==1?v<.54f:u+.6f*v<.82f;
            const float z=foreground?50.f:200.f;
            depth[(RY+y)*DW+RX+x]=reversed?10.f/z:1.f-10.f/z;
        }
        set("RightDepthRect",{float(RX),float(RY),float(RW),float(RH)});
        set("DepthViewportRanges",{0,1,0,1});
        set("StereoDepthZ",{reversed?0.f:1.f,reversed?10.f:-10.f,1,0});
        set("StereoCheck",{1.f,.015f,.2f,5.f});
        set("RightDepthJitterUV",{jitter[0]/RW,jitter[1]/RH},true);
        ctx->UpdateSubresource(buffer.Get(),0,nullptr,constants.data(),0,0);
        D3D11_TEXTURE2D_DESC dd{};dd.Width=DW;dd.Height=DH;dd.MipLevels=dd.ArraySize=1;
        dd.Format=DXGI_FORMAT_R32_FLOAT;dd.SampleDesc.Count=1;dd.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA initial{depth.data(),DW*4,0};
        ComPtr<ID3D11Texture2D> dt;hr(dev->CreateTexture2D(&dd,&initial,&dt),"depth texture");
        ComPtr<ID3D11ShaderResourceView> srv;hr(dev->CreateShaderResourceView(dt.Get(),nullptr,&srv),"depth SRV");
        auto* s=srv.Get();ctx->PSSetShaderResources(3,1,&s);ctx->Draw(3,0);
        ctx->CopyResource(readback.Get(),output.Get());
        D3D11_MAPPED_SUBRESOURCE mapped{};hr(ctx->Map(readback.Get(),0,D3D11_MAP_READ,0,&mapped),"map output");
        auto zAt=[&](int x,int y) {
            x=std::clamp(x,int(RX),int(RX+RW-1));y=std::clamp(y,int(RY),int(RY+RH-1));
            const float d=depth[size_t(y)*DW+size_t(x)];return reversed?10.f/d:10.f/(1.f-d);
        };
        for(unsigned y=0;y<H;++y)for(unsigned x=0;x<W;++x) {
            const float u=(float(x)+.5f)/W,v=(float(y)+.5f)/H;
            const float dx=RX+u*RW+jitter[0],dy=RY+v*RH+jitter[1];
            const int cx=std::clamp(int(std::floor(dx)),int(RX),int(RX+RW-1));
            const int cy=std::clamp(int(std::floor(dy)),int(RY),int(RY+RH-1));
            bool foreground=false;
            for(int j=-1;j<=1;++j)for(int i=-1;i<=1;++i)foreground=foreground||zAt(cx+i,cy+j)<80.f;
            const int ox=int(std::floor(dx-.5f)),oy=int(std::floor(dy-.5f));
            const std::array<float,4> zs{zAt(ox,oy),zAt(ox+1,oy),zAt(ox,oy+1),zAt(ox+1,oy+1)};
            const auto [mn,mx]=std::minmax_element(zs.begin(),zs.end());
            const bool edge=*mx-*mn>2.f*(1.f+.015f*(*mn));
            auto* pixel=reinterpret_cast<const float*>(static_cast<const unsigned char*>(mapped.pData)+size_t(y)*mapped.RowPitch)+x*4;
            const bool bad=(pixel[0]>.5f)!=foreground||(pixel[1]>.5f)!=edge;
            ++checks;if(bad){++errors;if(jitter[0]||jitter[1])++nonzero_phase_errors;else ++zero_phase_errors;}
        }
        ctx->Unmap(readback.Get(),0);
    }
    std::cout<<"production mask checks="<<checks<<" errors="<<errors
        <<" zero-jitter="<<zero_phase_errors<<" nonzero-jitter="<<nonzero_phase_errors<<"\n";
    if(expect_regression)need(nonzero_phase_errors>0,"old shader failed to reproduce jitter regression");
    else need(errors==0,"production mask does not match compensated depth footprint");
    std::cout<<"PASS: "<<(expect_regression?"CI73 regression reproduced":"CI74 actual shader masks aligned")<<"\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
