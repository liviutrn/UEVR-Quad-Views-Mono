// Run the actual final production PSNativeStereo on WARP. Intentionally
// displaced, high-contrast eye colors make mixed-owner pixels measurable.
#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d3d11shader.h>
#include <wrl/client.h>
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
static void need(bool ok,const char* s){if(!ok)throw std::runtime_error(s);}
static void hr(HRESULT h,const char* s){need(SUCCEEDED(h),s);}
static ComPtr<ID3DBlob> compile(const std::string& s,const char* file,const char* entry,const char* target){
 ComPtr<ID3DBlob> b,e;auto h=D3DCompile(s.data(),s.size(),file,nullptr,D3D_COMPILE_STANDARD_FILE_INCLUDE,entry,target,D3DCOMPILE_ENABLE_STRICTNESS|D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&b,&e);
 if(FAILED(h)&&e)std::cerr<<static_cast<const char*>(e->GetBufferPointer());hr(h,"shader compile");return b;
}
int main(int argc,char**argv)try{
 need(argc==2||argc==3,"usage: owner_gpu_tests shader [--expect-regression]");
 const bool before=argc==3;const auto file=std::filesystem::absolute(argv[1]);std::ifstream f(file);need(bool(f),"shader missing");
 const std::string s((std::istreambuf_iterator<char>(f)),{});std::filesystem::current_path(file.parent_path());
 auto psb=compile(s,file.string().c_str(),"PSNativeStereo","ps_5_0");
 auto vsb=compile(R"(struct V{float4 p:SV_POSITION;float2 uv:TEXCOORD0;};V VS(uint id:SV_VertexID){V v;v.uv=float2((id<<1)&2,id&2);v.p=float4(v.uv*float2(2,-2)+float2(-1,1),0,1);return v;})","probe","VS","vs_5_0");
 ComPtr<ID3D11Device>d;ComPtr<ID3D11DeviceContext>c;D3D_FEATURE_LEVEL l{};
 hr(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&d,&l,&c),"WARP");
 ComPtr<ID3D11PixelShader>ps;ComPtr<ID3D11VertexShader>vs;
 hr(d->CreatePixelShader(psb->GetBufferPointer(),psb->GetBufferSize(),nullptr,&ps),"PS");hr(d->CreateVertexShader(vsb->GetBufferPointer(),vsb->GetBufferSize(),nullptr,&vs),"VS");
 ComPtr<ID3D11ShaderReflection>r;hr(D3DReflect(psb->GetBufferPointer(),psb->GetBufferSize(),IID_PPV_ARGS(&r)),"reflect");
 auto* cb=r->GetConstantBufferByName("DuoViewCompositeConfig");D3D11_SHADER_BUFFER_DESC cbd{};hr(cb->GetDesc(&cbd),"cb");need(cbd.Size==240,"b0 size changed");
 std::array<unsigned char,240> data{};
 auto put=[&](const char* name,const void* p,size_t n){D3D11_SHADER_VARIABLE_DESC v{};hr(cb->GetVariableByName(name)->GetDesc(&v),name);need(v.StartOffset+n<=data.size(),"bounds");std::memcpy(data.data()+v.StartOffset,p,n);};
 auto sf=[&](const char* name,std::initializer_list<float> v){put(name,v.begin(),v.size()*4);};
 auto su=[&](const char* name,std::initializer_list<unsigned> v){put(name,v.begin(),v.size()*4);};
 su("OutputSize",{32,24});su("AtlasSize",{8,8});su("FoveaRect",{0,0,8,8});su("PeripheralRect",{0,0,8,8});
 su("NativeFoveaDimensions",{8,8});su("NativePeripheryDimensions",{8,8});
 sf("CropUv",{.25f,.25f,.75f,.75f});sf("FeatherFraction",{.3f});sf("StereoDepthZ",{0,10,1,0});
 sf("DepthViewportRanges",{0,1,0,1});sf("RightDepthRect",{0,0,8,8});sf("LeftDepthRect",{0,0,8,8});sf("StereoCheck",{1,.015f,.2f,5});
 D3D11_BUFFER_DESC bd{};bd.ByteWidth=240;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;ComPtr<ID3D11Buffer>b;hr(d->CreateBuffer(&bd,nullptr,&b),"buffer");
 auto texture=[&](unsigned channels,const float* values,ComPtr<ID3D11Texture2D>&t,ComPtr<ID3D11ShaderResourceView>&srv){
  std::vector<float> pixels(8*8*channels);for(unsigned i=0;i<64;++i)for(unsigned k=0;k<channels;++k)pixels[i*channels+k]=values[k];
  D3D11_TEXTURE2D_DESC td{};td.Width=td.Height=8;td.MipLevels=td.ArraySize=1;td.SampleDesc.Count=1;td.Format=channels==1?DXGI_FORMAT_R32_FLOAT:DXGI_FORMAT_R32G32B32A32_FLOAT;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
  D3D11_SUBRESOURCE_DATA init{pixels.data(),8*channels*4,0};hr(d->CreateTexture2D(&td,&init,&t),"input");hr(d->CreateShaderResourceView(t.Get(),nullptr,&srv),"SRV");
 };
 D3D11_TEXTURE2D_DESC td{};td.Width=64;td.Height=24;td.MipLevels=td.ArraySize=1;td.SampleDesc.Count=1;td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;td.BindFlags=D3D11_BIND_RENDER_TARGET;
 ComPtr<ID3D11Texture2D>out,read;hr(d->CreateTexture2D(&td,nullptr,&out),"output");td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;hr(d->CreateTexture2D(&td,nullptr,&read),"read");
 ComPtr<ID3D11RenderTargetView>rtv;hr(d->CreateRenderTargetView(out.Get(),nullptr,&rtv),"RTV");auto*rt=rtv.Get();c->OMSetRenderTargets(1,&rt,nullptr);
 D3D11_VIEWPORT vp{0,0,64,24,0,1};c->RSSetViewports(1,&vp);c->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);c->VSSetShader(vs.Get(),nullptr,0);c->PSSetShader(ps.Get(),nullptr,0);
 auto*buffer=b.Get();c->PSSetConstantBuffers(0,1,&buffer);D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxAnisotropy=1;sd.MaxLOD=D3D11_FLOAT32_MAX;sd.ComparisonFunc=D3D11_COMPARISON_ALWAYS;ComPtr<ID3D11SamplerState>sam;hr(d->CreateSamplerState(&sd,&sam),"sampler");auto*sm=sam.Get();c->PSSetSamplers(0,1,&sm);
 uint64_t mixed=0,checks=0,opaque_green=0,partial_green=0,near_outer_green=0;
 for(float alpha:{0.f,.25f,.5f,.75f,.99f,1.f})for(bool is_near:{false,true}){
  std::array<ComPtr<ID3D11Texture2D>,6> tex;std::array<ComPtr<ID3D11ShaderResourceView>,6> views;float red[]{1,0,0,1},blue[]{0,0,1,1},green[]{0,alpha,0,alpha};float z=is_near?10.f/50.f:10.f/200.f;
  texture(4,red,tex[0],views[0]);texture(4,blue,tex[1],views[1]);texture(1,&z,tex[2],views[2]);texture(1,&z,tex[3],views[3]);texture(4,green,tex[4],views[4]);texture(4,green,tex[5],views[5]);
  std::array<ID3D11ShaderResourceView*,6> raw{};for(unsigned i=0;i<6;++i)raw[i]=views[i].Get();c->PSSetShaderResources(0,6,raw.data());c->UpdateSubresource(b.Get(),0,nullptr,data.data(),0,0);c->Draw(3,0);c->CopyResource(read.Get(),out.Get());D3D11_MAPPED_SUBRESOURCE map{};hr(c->Map(read.Get(),0,D3D11_MAP_READ,0,&map),"map");
  for(unsigned y=0;y<24;++y)for(unsigned x=0;x<64;++x){auto*pix=reinterpret_cast<const float*>(static_cast<const unsigned char*>(map.pData)+y*map.RowPitch)+4*x;unsigned nonzero=0;for(unsigned k=0;k<3;++k)if(pix[k]>.001f)++nonzero;if(nonzero>1)++mixed;++checks;
   if(pix[1]>.999f){if(alpha==1&&!is_near)++opaque_green;if(alpha<.995f)++partial_green;if(is_near&&(x%32<8||x%32>=24||y<6||y>=18))++near_outer_green;}
  }c->Unmap(read.Get(),0);std::array<ID3D11ShaderResourceView*,6> empty{};c->PSSetShaderResources(0,6,empty.data());
 }
 std::cout<<"pixels="<<checks<<" mixed_owners="<<mixed<<" opaque_synthetic="<<opaque_green<<" unsupported_synthetic="<<partial_green<<" near_periphery_warp="<<near_outer_green<<"\n";
 if(before)need(mixed>0,"CI75 ghosting witness not reproduced");else{need(mixed==0,"displaced image mixing");need(opaque_green>0,"all-native cheat");need(partial_green==0,"partial synthetic support selected");need(near_outer_green==0,"is_near periphery warped");}
 return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
