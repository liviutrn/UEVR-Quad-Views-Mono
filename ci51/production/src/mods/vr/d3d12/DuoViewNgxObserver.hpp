#pragma once
// NGX DLSS-SR observation, independently implemented from the public NGX ABI.
// Original calls always run. Successful Evaluate restores inputs to NPS per
// NVIDIA DLSS Programming Guide 3.4, including on a compute command list.
#include <Windows.h>
#include <d3d11.h>
#include <d3d12.h>
#include <safetyhook.hpp>
#include <array>
#include <atomic>
#include <memory>
#include <mutex>
#include "../DuoViewNgxGuide.hpp"
#include "StockDibrDepth.hpp"

namespace stock_dibr::ngx {
struct Parameters {
    virtual void Set(const char*, unsigned long long)=0;
    virtual void Set(const char*, float)=0;
    virtual void Set(const char*, double)=0;
    virtual void Set(const char*, unsigned int)=0;
    virtual void Set(const char*, int)=0;
    virtual void Set(const char*, ID3D11Resource*)=0;
    virtual void Set(const char*, ID3D12Resource*)=0;
    virtual void Set(const char*, void*)=0;
    virtual uint32_t Get(const char*, unsigned long long*) const=0;
    virtual uint32_t Get(const char*, float*) const=0;
    virtual uint32_t Get(const char*, double*) const=0;
    virtual uint32_t Get(const char*, unsigned int*) const=0;
    virtual uint32_t Get(const char*, int*) const=0;
    virtual uint32_t Get(const char*, ID3D11Resource**) const=0;
    virtual uint32_t Get(const char*, ID3D12Resource**) const=0;
    virtual uint32_t Get(const char*, void**) const=0;
    virtual void Reset()=0;
};
inline bool succeeded(uint32_t r) noexcept {return (r & 0xFFF00000U)!=0xBAD00000U;}
inline uint32_t read_uint(const Parameters* p,const char* key) noexcept {
    if(!p)return 0;
    unsigned int v{};if(succeeded(p->Get(key,&v)))return v;
    int s{};return succeeded(p->Get(key,&s)) && s>0 ? uint32_t(s) : 0u;
}
inline bool read_bits(const Parameters* p,const char* key,uint32_t& value) noexcept {
    if(!p)return false;
    int s{};if(succeeded(p->Get(key,&s))){value=uint32_t(s);return true;}
    unsigned int u{};if(succeeded(p->Get(key,&u))){value=u;return true;}
    return false;
}
inline float read_float(const Parameters* p,const char* key,float fallback=0.f) noexcept {
    float v{};return p && succeeded(p->Get(key,&v)) ? v : fallback;
}
inline ID3D12Resource* read_resource(const Parameters* p,const char* key) noexcept {
    ID3D12Resource* v{};return p && succeeded(p->Get(key,&v)) ? v : nullptr;
}
inline thread_local unsigned interception_depth{};
struct Invocation {
    bool outer{interception_depth++==0};
    ~Invocation(){--interception_depth;}
};
class Observer final {
    using Hooks=std::array<safetyhook::InlineHook,4>;
    Hooks evaluations{},creates{},releases{};
    std::array<bool,4> eval_installed{},create_installed{},release_installed{};
    std::mutex lock;
    std::weak_ptr<stock_dibr::DepthCapture> capture;
    uevr::duoview::ngx::Features features;
    std::atomic<uint64_t> seen{},valid{},missing_ticket{},observer_failures{};
    Observer()=default;
    void inspect(ID3D12GraphicsCommandList* cmd,void* handle,const Parameters* p) {
        const uint64_t evaluation=++seen;
        if(!cmd || !handle || !p)return;
        auto* depth=read_resource(p,"Depth");auto* color=read_resource(p,"Color");
        auto* motion=read_resource(p,"MotionVectors");auto* output=read_resource(p,"Output");
        if(!depth || !color || !motion || !output)return;
        uevr::duoview::ngx::Guide g;
        g.producer=uevr::duoview::ngx::current_rhi_ticket;
        if(!g.producer){++missing_ticket;return;}
        g.output_width=read_uint(p,"OutWidth");g.output_height=read_uint(p,"OutHeight");
        g.role=uevr::duoview::ngx::role_for(g.producer,g.output_width,g.output_height);
        if(!g.role)return;
        g.input_width=read_uint(p,"DLSS.Render.Subrect.Dimensions.Width");
        g.input_height=read_uint(p,"DLSS.Render.Subrect.Dimensions.Height");
        if(!g.input_width)g.input_width=read_uint(p,"Width");
        if(!g.input_height)g.input_height=read_uint(p,"Height");
        uint32_t flags{};const bool known=read_bits(p,"DLSS.Feature.Create.Flags",flags);
        std::shared_ptr<stock_dibr::DepthCapture> sink;
        uevr::duoview::ngx::Feature f;
        {
            std::scoped_lock guard(lock);sink=capture.lock();
            f=features.observed(reinterpret_cast<uintptr_t>(handle),flags,known,g.output_width,g.output_height);
        }
        if(!sink || (f.create_observed && f.kind!=1u))return; // SR=1; never repurpose RR/FG.
        g.feature=reinterpret_cast<uintptr_t>(handle);g.output=reinterpret_cast<uintptr_t>(output);
        g.feature_generation=f.generation;g.feature_kind=f.kind;g.flags=f.flags;
        g.flags_known=f.flags_known;g.create_observed=f.create_observed;g.evaluation=evaluation;
        g.reset=read_uint(p,"Reset");
        g.depth_x=read_uint(p,"DLSS.Input.Depth.Subrect.Base.X");
        g.depth_y=read_uint(p,"DLSS.Input.Depth.Subrect.Base.Y");
        g.color_x=read_uint(p,"DLSS.Input.Color.Subrect.Base.X");
        g.color_y=read_uint(p,"DLSS.Input.Color.Subrect.Base.Y");
        g.motion_x=read_uint(p,"DLSS.Input.MV.Subrect.Base.X");
        g.motion_y=read_uint(p,"DLSS.Input.MV.Subrect.Base.Y");
        g.output_x=read_uint(p,"DLSS.Output.Subrect.Base.X");
        g.output_y=read_uint(p,"DLSS.Output.Subrect.Base.Y");
        g.jitter_x=read_float(p,"Jitter.Offset.X");g.jitter_y=read_float(p,"Jitter.Offset.Y");
        g.motion_scale_x=read_float(p,"MV.Scale.X",1.f);g.motion_scale_y=read_float(p,"MV.Scale.Y",1.f);
        // Unknown late-attach flags remain explicit. Motion is not used for
        // temporal history unless its resolution/scale contract is established.
        const auto md=motion->GetDesc();
        g.motion_extent_known=f.flags_known;
        if(f.flags_known)g.motion_low_resolution=(f.flags & 2u)!=0;
        else if(uint64_t(g.motion_x)+g.output_width>md.Width || uint64_t(g.motion_y)+g.output_height>md.Height) {
            // A padded allocation that cannot fit output-resolution motion is
            // unambiguously input resolution, even after late injection.
            g.motion_low_resolution=true;g.motion_extent_known=true;
        }
        // If both layouts fit, capture the full MV allocation explicitly as
        // unknown. Motion is diagnostic-only; uncertainty must not block depth.
        if(!g)return;
        ++valid;
        const auto& sizes=g.producer.outputs;
        sink->configure_duoview_sources(sizes[0],sizes[1],sizes[2],sizes[3]);
        sink->capture_ngx_dlss(cmd,depth,color,motion,g);
    }
    template<unsigned N> static uint32_t __cdecl evaluated(ID3D12GraphicsCommandList* cmd,
            void* handle,Parameters* p,void* callback) {
        auto& self=instance();Invocation invocation;
        const auto result=self.evaluations[N].call<uint32_t>(cmd,handle,p,callback);
        if(invocation.outer && succeeded(result)) {
            try {self.inspect(cmd,handle,p);} catch(...) {++self.observer_failures;}
        }
        return result;
    }
    template<unsigned N> static uint32_t __cdecl created(ID3D12GraphicsCommandList* cmd,
            uint32_t kind,const Parameters* p,void** handle) {
        auto& self=instance();Invocation invocation;
        const auto result=self.creates[N].call<uint32_t>(cmd,kind,p,handle);
        if(invocation.outer && succeeded(result) && handle && *handle) {
            try {
                uint32_t flags{};const bool known=read_bits(p,"DLSS.Feature.Create.Flags",flags);
                std::scoped_lock guard(self.lock);
                self.features.created(reinterpret_cast<uintptr_t>(*handle),kind,flags,known,
                    read_uint(p,"OutWidth"),read_uint(p,"OutHeight"));
            } catch(...) {++self.observer_failures;}
        }
        return result;
    }
    template<unsigned N> static uint32_t __cdecl released(void* handle) {
        auto& self=instance();Invocation invocation;
        const auto result=self.releases[N].call<uint32_t>(handle);
        if(invocation.outer && succeeded(result)) {
            std::scoped_lock guard(self.lock);self.features.released(reinterpret_cast<uintptr_t>(handle));
        }
        return result;
    }
    static void install_group(Hooks& group,std::array<bool,4>& installed,
            const std::array<const char*,2>& names,const std::array<void*,4>& callbacks) {
        static const wchar_t* dlls[]{L"nvngx_dlss.dll",L"_nvngx.dll"};
        for(unsigned dll=0;dll<2;++dll) {
            HMODULE module=GetModuleHandleW(dlls[dll]);if(!module)continue;
            for(unsigned symbol=0;symbol<2;++symbol) {
                const unsigned index=dll*2+symbol;if(installed[index])continue;
                auto* address=GetProcAddress(module,names[symbol]);if(!address)continue;
                bool alias=false;
                for(unsigned k=0;k<4;++k)
                    if(installed[k] && group[k].target()==reinterpret_cast<uint8_t*>(address))alias=true;
                if(alias)continue;
                // Hooks live for process lifetime. Pin a successfully resolved
                // module so a DLSS setting change cannot unload its trampoline.
                HMODULE pinned{};
                if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN,dlls[dll],&pinned))continue;
                auto hook=safetyhook::create_inline(reinterpret_cast<void*>(address),callbacks[index],
                    safetyhook::InlineHook::StartDisabled);
                if(hook) {
                    group[index]=std::move(hook);
                    if(group[index].enable())installed[index]=true;else group[index].reset();
                }
            }
        }
    }
public:
    Observer(const Observer&)=delete;Observer& operator=(const Observer&)=delete;
    static Observer& instance(){static Observer* singleton=new Observer;return *singleton;}
    static bool requested(){
        static const bool enabled=[] {char v[8]{};const auto n=GetEnvironmentVariableA("UEVR_DUOVIEW_NGX_DEPTH",v,sizeof(v));return n==0 || v[0]!='0';}();
        return enabled;
    }
    void bind(const std::shared_ptr<stock_dibr::DepthCapture>& sink,bool active){
        std::scoped_lock guard(lock);capture=active?sink:std::shared_ptr<stock_dibr::DepthCapture>{};
    }
    void install(){
        if(!requested())return;
        std::scoped_lock guard(lock);
        install_group(evaluations,eval_installed,{"NVSDK_NGX_D3D12_EvaluateFeature","NVSDK_NGX_D3D12_EvaluateFeature_C"},
            {reinterpret_cast<void*>(&evaluated<0>),reinterpret_cast<void*>(&evaluated<1>),reinterpret_cast<void*>(&evaluated<2>),reinterpret_cast<void*>(&evaluated<3>)});
        install_group(creates,create_installed,{"NVSDK_NGX_D3D12_CreateFeature","NVSDK_NGX_D3D12_CreateFeature_C"},
            {reinterpret_cast<void*>(&created<0>),reinterpret_cast<void*>(&created<1>),reinterpret_cast<void*>(&created<2>),reinterpret_cast<void*>(&created<3>)});
        install_group(releases,release_installed,{"NVSDK_NGX_D3D12_ReleaseFeature","NVSDK_NGX_D3D12_ReleaseFeature_C"},
            {reinterpret_cast<void*>(&released<0>),reinterpret_cast<void*>(&released<1>),reinterpret_cast<void*>(&released<2>),reinterpret_cast<void*>(&released<3>)});
    }
    uint64_t observed_calls()const{return seen.load();}
    uint64_t sr_calls()const{return valid.load();}
    uint64_t missing_tickets()const{return missing_ticket.load();}
};
}
