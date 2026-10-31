// Exercise the production PSNativeStereo foreground guard on D3D11 WARP.
// The test uses flat, unmistakable owners so every output pixel is attributable.
#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d3d11shader.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace {
void need(bool ok,const char* what){if(!ok)throw std::runtime_error(what);}
void hr(HRESULT h,const char* what){need(SUCCEEDED(h),what);}
ComPtr<ID3DBlob> compile(const std::string& source,const char* file,const char* entry,const char* target){
    ComPtr<ID3DBlob> code,errors;
    const auto result=D3DCompile(source.data(),source.size(),file,nullptr,
        D3D_COMPILE_STANDARD_FILE_INCLUDE,entry,target,
        D3DCOMPILE_ENABLE_STRICTNESS|D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&code,&errors);
    if(FAILED(result)&&errors)std::cerr<<static_cast<const char*>(errors->GetBufferPointer())<<'\n';
    hr(result,"compile production shader");return code;
}
struct Input {
    ComPtr<ID3D11Texture2D> texture;
    ComPtr<ID3D11ShaderResourceView> view;
};
constexpr unsigned W=40,H=24;
}

int main(int argc,char**argv) try {
    need(argc==2,"usage: foreground_gpu_tests DuoViewStereoCompositeRaster.hlsl");
    const auto shader=std::filesystem::absolute(argv[1]);
    std::ifstream in(shader);need(bool(in),"production shader missing");
    const std::string source((std::istreambuf_iterator<char>(in)),{});
    // Prefer the shader's own directory; in the staged ci80 fixture, fall back
    // to the unchanged shared raster base retained by ci76.
    auto include_dir=shader.parent_path();
    if(!std::filesystem::exists(include_dir/"DuoViewCompositeRaster.hlsl")) {
        const auto fallback=std::filesystem::current_path()/"ci76_finalsource/src/mods/vr";
        if(std::filesystem::exists(fallback/"DuoViewCompositeRaster.hlsl"))include_dir=fallback;
    }
    std::filesystem::current_path(include_dir);
    auto ps_code=compile(source,shader.string().c_str(),"PSNativeStereo","ps_5_0");
    auto vs_code=compile(R"(struct V{float4 p:SV_POSITION;};V VS(uint id:SV_VertexID){V v;float2 uv=float2((id<<1)&2,id&2);v.p=float4(uv*float2(2,-2)+float2(-1,1),0,1);return v;})","probe","VS","vs_5_0");
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> ctx;D3D_FEATURE_LEVEL level{};
    hr(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,
        &device,&level,&ctx),"create WARP device");
    ComPtr<ID3D11PixelShader> ps;ComPtr<ID3D11VertexShader> vs;
    hr(device->CreatePixelShader(ps_code->GetBufferPointer(),ps_code->GetBufferSize(),nullptr,&ps),"create PS");
    hr(device->CreateVertexShader(vs_code->GetBufferPointer(),vs_code->GetBufferSize(),nullptr,&vs),"create VS");
    ComPtr<ID3D11ShaderReflection> reflection;
    hr(D3DReflect(ps_code->GetBufferPointer(),ps_code->GetBufferSize(),IID_PPV_ARGS(&reflection)),"reflect PS");
    auto* config=reflection->GetConstantBufferByName("DuoViewCompositeConfig");
    D3D11_SHADER_BUFFER_DESC cb_desc{};hr(config->GetDesc(&cb_desc),"reflect b0");need(cb_desc.Size==240,"b0 layout changed");
    std::array<uint8_t,240> cb{};
    auto put=[&](const char* name,const void* p,size_t bytes){
        D3D11_SHADER_VARIABLE_DESC d{};hr(config->GetVariableByName(name)->GetDesc(&d),name);
        need(d.StartOffset+bytes<=cb.size(),"constant write out of bounds");std::memcpy(cb.data()+d.StartOffset,p,bytes);
    };
    auto floats=[&](const char* name,std::initializer_list<float> v){put(name,v.begin(),v.size()*sizeof(float));};
    auto uints=[&](const char* name,std::initializer_list<uint32_t> v){put(name,v.begin(),v.size()*sizeof(uint32_t));};
    auto color=[&](unsigned width,unsigned height,std::array<float,4> value,
                   const std::vector<std::array<float,4>>& pixels={}){
        Input out;std::vector<std::array<float,4>> data(size_t(width)*height,value);
        if(!pixels.empty()){need(pixels.size()==data.size(),"color pattern size");data=pixels;}
        D3D11_TEXTURE2D_DESC d{};d.Width=width;d.Height=height;d.MipLevels=d.ArraySize=1;
        d.SampleDesc.Count=1;d.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;d.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA init{data.data(),UINT(width*4*sizeof(float)),0};
        hr(device->CreateTexture2D(&d,&init,&out.texture),"create color input");
        hr(device->CreateShaderResourceView(out.texture.Get(),nullptr,&out.view),"create color SRV");return out;
    };
    auto depth=[&](const std::array<float,64>& values){
        Input out;D3D11_TEXTURE2D_DESC d{};d.Width=d.Height=8;d.MipLevels=d.ArraySize=1;
        d.SampleDesc.Count=1;d.Format=DXGI_FORMAT_R32_FLOAT;d.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA init{values.data(),8*sizeof(float),0};
        hr(device->CreateTexture2D(&d,&init,&out.texture),"create depth input");
        hr(device->CreateShaderResourceView(out.texture.Get(),nullptr,&out.view),"create depth SRV");return out;
    };
    D3D11_BUFFER_DESC bd{};bd.ByteWidth=240;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    ComPtr<ID3D11Buffer> constants;hr(device->CreateBuffer(&bd,nullptr,&constants),"create b0");
    D3D11_TEXTURE2D_DESC od{};od.Width=2*W;od.Height=H;od.MipLevels=od.ArraySize=1;
    od.SampleDesc.Count=1;od.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;od.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> output,readback;hr(device->CreateTexture2D(&od,nullptr,&output),"create output");
    od.BindFlags=0;od.Usage=D3D11_USAGE_STAGING;od.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    hr(device->CreateTexture2D(&od,nullptr,&readback),"create readback");
    ComPtr<ID3D11RenderTargetView> rtv;hr(device->CreateRenderTargetView(output.Get(),nullptr,&rtv),"create RTV");
    auto* target=rtv.Get();ctx->OMSetRenderTargets(1,&target,nullptr);D3D11_VIEWPORT vp{0,0,2.f*W,float(H),0,1};
    ctx->RSSetViewports(1,&vp);ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx->VSSetShader(vs.Get(),nullptr,0);ctx->PSSetShader(ps.Get(),nullptr,0);auto* cbp=constants.Get();ctx->PSSetConstantBuffers(0,1,&cbp);
    D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxAnisotropy=1;
    sd.MaxLOD=D3D11_FLOAT32_MAX;sd.ComparisonFunc=D3D11_COMPARISON_ALWAYS;
    ComPtr<ID3D11SamplerState> sampler;hr(device->CreateSamplerState(&sd,&sampler),"create sampler");
    auto* sp=sampler.Get();ctx->PSSetSamplers(0,1,&sp);

    uint64_t checked=0;
    auto draw=[&](const std::array<float,64>& left_depth,const std::array<float,64>& right_depth,
                  float guard,float crop_start=.25f,float crop_end=.75f,unsigned active_periphery=W){
        uints("OutputSize",{W,H});uints("AtlasSize",{8,8});uints("FoveaRect",{0,0,8,8});
        uints("PeripheralRect",{0,0,active_periphery,H});
        uints("NativeFoveaDimensions",{8,8});uints("NativePeripheryDimensions",{40,H});
        floats("CropUv",{crop_start,.25f,crop_end,.75f});floats("FeatherFraction",{.3f});
        floats("_reserved",{guard});floats("StereoDepthZ",{0,10,1,0});
        floats("StereoLeftDepthZ",{0,10,1,0});floats("DepthViewportRanges",{0,1,0,1});
        floats("LeftDepthRect",{0,0,8,8});floats("RightDepthRect",{0,0,8,8});
        floats("StereoEyeX",{1,0,0,1});floats("StereoCheck",{1,.015f,.2f,4});
        auto left=color(8,8,{1,0,0,1});
        auto right=color(40,H,{0,0,0,1});
        // Fill only the active right-periphery viewport. Remaining allocation
        // stays black to catch sampling normalized against the full resource.
        std::vector<std::array<float,4>> right_pixels(size_t(40)*H,{0,0,0,1});
        for(unsigned y=0;y<H;++y)for(unsigned x=0;x<active_periphery;++x)right_pixels[size_t(y)*40+x]={0,0,1,1};
        right=color(40,H,{0,0,0,1},right_pixels);
        auto dl=depth(left_depth),dr=depth(right_depth);
        auto synth_right=color(8,8,{0,1,0,1});auto synth_left=color(40,H,{0,1,0,1});
        ID3D11ShaderResourceView* views[]{left.view.Get(),right.view.Get(),dl.view.Get(),dr.view.Get(),synth_right.view.Get(),synth_left.view.Get()};
        ctx->PSSetShaderResources(0,6,views);ctx->UpdateSubresource(constants.Get(),0,nullptr,cb.data(),0,0);
        ctx->Draw(3,0);ctx->CopyResource(readback.Get(),output.Get());D3D11_MAPPED_SUBRESOURCE mapped{};
        hr(ctx->Map(readback.Get(),0,D3D11_MAP_READ,0,&mapped),"map output");
        std::vector<std::array<float,4>> pixels(size_t(2*W)*H);
        for(unsigned y=0;y<H;++y)for(unsigned x=0;x<2*W;++x){
            const auto* p=reinterpret_cast<const float*>(static_cast<const uint8_t*>(mapped.pData)+size_t(y)*mapped.RowPitch)+4*x;
            pixels[size_t(y)*2*W+x]={p[0],p[1],p[2],p[3]};
        }
        ctx->Unmap(readback.Get(),0);ID3D11ShaderResourceView* empty[6]{};ctx->PSSetShaderResources(0,6,empty);return pixels;
    };
    const auto at=[](const auto& p,unsigned x,unsigned y,unsigned eye=0)->const std::array<float,4>&{
        return p[size_t(y)*2*W+eye*W+x];
    };
    const auto is_blue=[](const auto& c){return c[2]>.98f&&c[0]<.02f&&c[1]<.02f;};
    const auto is_red=[](const auto& c){return c[0]>.98f&&c[1]<.02f&&c[2]<.02f;};
    const auto is_green=[](const auto& c){return c[1]>.98f&&c[0]<.02f&&c[2]<.02f;};
    const std::array<float,64> far_depth=[](){std::array<float,64>a{};a.fill(.05f);return a;}(); // 200 cm
    std::array<float,64> left_near=far_depth,right_near=far_depth;
    for(unsigned y=3;y<=5;++y)for(unsigned x=3;x<=5;++x)left_near[y*8+x]=.2f; // 50 cm
    for(unsigned y=3;y<=5;++y)for(unsigned x=1;x<=2;++x)right_near[y*8+x]=.2f;
    auto p=draw(left_near,far_depth,2.f);
    need(is_red(at(p,20,12,0))&&is_green(at(p,20,12,1)),"guard-off left-depth owner changed");++checked;
    p=draw(left_near,far_depth,3.f);
    for(unsigned y=10;y<=14;++y)for(unsigned x=18;x<=22;++x)for(unsigned eye=0;eye<2;++eye){
        need(is_blue(at(p,x,y,eye)),"left-crop near foreground did not select real RIGHT in both eyes");++checked;
    }
    p=draw(far_depth,right_near,2.f);
    need(is_red(at(p,10,12,0)),"guard-off right-depth owner changed");++checked;
    p=draw(far_depth,right_near,3.f);
    for(unsigned y=10;y<=14;++y)for(unsigned x=9;x<=11;++x)for(unsigned eye=0;eye<2;++eye){
        need(is_blue(at(p,x,y,eye)),"right-depth near foreground did not select real RIGHT in both eyes");++checked;
    }
    auto empty_far=draw(far_depth,far_depth,2.f),guarded_far=draw(far_depth,far_depth,3.f);
    need(is_red(at(empty_far,20,12,0))&&is_green(at(empty_far,20,12,1)),"far baseline fixture did not produce distinct owners");
    need(is_red(at(guarded_far,20,12,0))&&is_green(at(guarded_far,20,12,1)),"foreground guard altered far surfaces");checked+=2;

    // Crop changes from 8/40 to 19/40 while the native resource remains 40
    // texels wide. Only active texels contain blue; black padding must stay out.
    const std::array<float,64> no_near=far_depth;
    p=draw(no_near,no_near,0.f,.2f,.499f,19);
    for(unsigned y=0;y<H;++y)for(unsigned x=0;x<W;++x){
        const float u=(x+.5f)/W;
        if(u<.2f||u>=.499f){need(is_blue(at(p,x,y,1)),"padded native periphery sampled black beyond active viewport");++checked;}
    }

    // The paired surface pass must discard target-space near geometry too.
    // Keep this tied to the production bit value and shader branch so the GPU
    // owner fixture also guards the outside-source-mask safety clause.
    const auto mesh_file=shader.parent_path()/"DuoViewSurfaceReproject.hlsl";
    std::ifstream mesh_in(mesh_file);need(bool(mesh_in),"production surface shader missing");
    const std::string mesh((std::istreambuf_iterator<char>(mesh_in)),{});
    need(mesh.find("(MeshConfig.w&128u)!=0u")!=std::string::npos&&
         mesh.find("targetZ<80.f")!=std::string::npos,
         "pass1 near-depth discard bit 128 missing");
    const auto wrapper_file=shader.parent_path()/"DuoViewD3D12.hpp";
    std::ifstream wrapper_in(wrapper_file);need(bool(wrapper_in),"production compositor wrapper missing");
    const std::string wrapper((std::istreambuf_iterator<char>(wrapper_in)),{});
    need(wrapper.find("|=128u")!=std::string::npos,"pass1 does not enable near-depth discard bit 128");
    std::cout<<"foreground_guard_pixels="<<checked<<" padded_active_viewport=19/40 pass1_near_guard=bit128\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
