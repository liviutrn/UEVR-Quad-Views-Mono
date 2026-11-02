#pragma once
// v210: observe LIVE NGX D3D12-SR depth calls, never interfere with DLSS.
// This is a source browser, not yet a GPU depth texture capture. Every
// source is manually pinned. Borrowed resources are inspected synchronously
// inside the original NGX invocation and are NOT retained past the callback.
#include <Windows.h>
#include <d3d12.h>
#include <d3d11.h>
#include <safetyhook.hpp>
#include <algorithm>
#include <array>
#include <atomic>
#include <mutex>
#include <unordered_map>
#include "../DuoViewNgxManualDepth.hpp"
#include "../DuoViewNgxDepthCapture.hpp"
#include "../DuoViewNgxRhiTicket.hpp"

namespace uevr::duoview::ngx {
struct NgxParameters {
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
inline bool ngx_success(uint32_t result) noexcept {
    return (result & 0xfff00000u)!=0xbad00000u;
}
inline uint32_t ngx_uint(const NgxParameters* p,const char* k) noexcept {
    if(!p)return 0u;
    unsigned int u{};
    if(ngx_success(p->Get(k,&u)))return u;
    int s{};
    return ngx_success(p->Get(k,&s)) && s>0?uint32_t(s):0u;
}
inline float ngx_float(const NgxParameters* p,const char* k) noexcept {
    float v{};
    return p && ngx_success(p->Get(k,&v)) ? v:0.f;
}
inline ID3D12Resource* ngx_resource(const NgxParameters* p,const char* k) noexcept {
    ID3D12Resource* v{};
    return p && ngx_success(p->Get(k,&v)) ? v:nullptr;
}
class ManualNgxObserver final {
    using Hooks=std::array<safetyhook::InlineHook,4>;
    Hooks evals_{},creates_{},releases_{};
    safetyhook::InlineHook execute_{};
    bool execute_ok_{};
    std::array<bool,4> eval_ok_{},create_ok_{},release_ok_{};
    mutable std::mutex mutex_;
    struct Feature {uint32_t kind{};bool created{};};
    std::unordered_map<uintptr_t,Feature> features_;
    std::atomic<bool> active_{false};
    std::atomic<uint64_t> eval_count_{},qualified_{},errors_{},missing_rhi_ticket_{};
    std::atomic<uint64_t> selected_count_{},inactive_renderer_{},stale_packet_{},capture_attempts_{};
    std::atomic<uint32_t> last_output_w_{},last_output_h_{},last_render_w_{},last_render_h_{},
        last_depth_format_{},last_command_type_{},last_selected_thread_{};
    static inline thread_local unsigned nested_calls_{};
    struct Guard {
        bool outer{nested_calls_++==0};
        ~Guard(){--nested_calls_;}
    };
    void inspect(ID3D12GraphicsCommandList* cmd,void* feature,const NgxParameters* p) {
        if(!active_.load(std::memory_order_acquire)||!cmd||!feature||!p)return;
        auto* depth=ngx_resource(p,"Depth");
        auto* color=ngx_resource(p,"Color");
        auto* output=ngx_resource(p,"Output");
        if(!depth || !color || !output)return;
        const auto desc=depth->GetDesc();
        if(desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count!=1 ||
           desc.DepthOrArraySize!=1 || desc.Width==0 || desc.Width>UINT32_MAX || !desc.Height)return;
        const auto out_width=ngx_uint(p,"OutWidth"),out_height=ngx_uint(p,"OutHeight");
        if(!out_width || !out_height)return;
        const auto feature_id=reinterpret_cast<uintptr_t>(feature);
        Feature meta{};
        {
            std::scoped_lock guard(mutex_);
            if(auto it=features_.find(feature_id);it!=features_.end())meta=it->second;
        }
        if(meta.created && meta.kind!=1u)return; // Only native DLSS-SR, not RR/FG.
        DepthCandidate sample{};
        sample.feature=feature_id;
        sample.evaluation=eval_count_.load(std::memory_order_relaxed);
        sample.output_width=out_width;sample.output_height=out_height;
        sample.render_width=ngx_uint(p,"DLSS.Render.Subrect.Dimensions.Width");
        sample.render_height=ngx_uint(p,"DLSS.Render.Subrect.Dimensions.Height");
        if(!sample.render_width)sample.render_width=ngx_uint(p,"Width");
        if(!sample.render_height)sample.render_height=ngx_uint(p,"Height");
        sample.depth_width=uint32_t(desc.Width);sample.depth_height=desc.Height;
        sample.depth_x=ngx_uint(p,"DLSS.Input.Depth.Subrect.Base.X");
        sample.depth_y=ngx_uint(p,"DLSS.Input.Depth.Subrect.Base.Y");
        sample.format=uint32_t(desc.Format);
        sample.jitter_x=ngx_float(p,"Jitter.Offset.X");
        sample.jitter_y=ngx_float(p,"Jitter.Offset.Y");
        sample.feature_kind=meta.kind;sample.create_observed=meta.created;
        sample.depth_present=true;sample.color_present=true;
        if(uint64_t(sample.depth_x)+sample.render_width>desc.Width ||
           uint64_t(sample.depth_y)+sample.render_height>desc.Height)return;
        candidates().observe(sample);
        ++qualified_;
        // Proven on this CPU producer draw key, not inferred from "largest texture".
        // The native compositor independently checks the SAME packet key,
        // exact output rectangle and already-submitted original game queue.
        const auto pick=candidates().choose();
        if(pick.source!=std::array<uintptr_t,3>{feature_id,out_width,out_height} ||
           (!pick.exact && !pick.manual)) return;
        ++selected_count_;
        last_output_w_.store(out_width,std::memory_order_relaxed);
        last_output_h_.store(out_height,std::memory_order_relaxed);
        last_render_w_.store(sample.render_width,std::memory_order_relaxed);
        last_render_h_.store(sample.render_height,std::memory_order_relaxed);
        last_depth_format_.store(sample.format,std::memory_order_relaxed);
        last_command_type_.store(static_cast<uint32_t>(cmd->GetType()),std::memory_order_relaxed);
        last_selected_thread_.store(GetCurrentThreadId(),std::memory_order_relaxed);
        const auto vr=::VR::get();
        if(!vr || !vr->is_duoview_renderer_active()) {++inactive_renderer_;return;}
        const auto key=current_rhi_producer_key;
        if(!key.generation || !key.frame) {
            ++missing_rhi_ticket_;
            // NGX may execute outside UE's hooked RHI scope. Capture here
            // with *actual NGX Output identity*, NOT guessed frame identity.
            // Only a same-queue, submitted, output-identity match may consume it.
            ++capture_attempts_;
            depth_snapshots().capture(cmd,depth,sample,{},output);
            return;
        }
        const auto frozen=vr->duoview_state().snapshot(key);
        if(!frozen || frozen->config.key!=key ||
           (!pick.manual &&
            (frozen->config.layout.fovea.width!=out_width ||
             frozen->config.layout.fovea.height!=out_height))) {++stale_packet_;return;}
        ++capture_attempts_;
        depth_snapshots().capture(cmd,depth,sample,key);
    }
    template<unsigned N> static uint32_t __cdecl evaluate(
        ID3D12GraphicsCommandList* cmd,void* feature,NgxParameters* p,void* cb) {
        auto& instance=self();
        Guard g;
        const auto result=instance.evals_[N].call<uint32_t>(cmd,feature,p,cb);
        if(g.outer && ngx_success(result)) {
            ++instance.eval_count_;
            try {instance.inspect(cmd,feature,p);}catch(...){++instance.errors_;}
        }
        return result;
    }
    template<unsigned N> static uint32_t __cdecl create(
        ID3D12GraphicsCommandList* cmd,uint32_t kind,const NgxParameters* p,void** feature) {
        auto& instance=self();Guard g;
        const auto result=instance.creates_[N].call<uint32_t>(cmd,kind,p,feature);
        if(g.outer && ngx_success(result) && feature && *feature) {
            std::scoped_lock lock(instance.mutex_);
            if(instance.features_.size()>=128)instance.features_.clear();
            instance.features_[reinterpret_cast<uintptr_t>(*feature)]={kind,true};
        }
        return result;
    }
    template<unsigned N> static uint32_t __cdecl release(void* feature) {
        auto& instance=self();Guard g;
        const auto result=instance.releases_[N].call<uint32_t>(feature);
        if(g.outer && ngx_success(result)) {
            {
                std::scoped_lock lock(instance.mutex_);
                instance.features_.erase(reinterpret_cast<uintptr_t>(feature));
            }
            candidates().released(reinterpret_cast<uintptr_t>(feature));
        }
        return result;
    }
    static void __cdecl execute_commands(ID3D12CommandQueue* queue,
        UINT count,ID3D12CommandList* const* lists) {
        auto& instance=self();
        instance.execute_.call<void>(queue,count,lists);
        // Publish only if the actual producer list was submitted on the
        // original game's DIRECT queue. No CPU or GPU blocking.
        depth_snapshots().submitted(queue,count,lists);
    }
    static void install_group(Hooks& hooks,std::array<bool,4>& installed,
        std::array<const char*,2> exports,std::array<void*,4> callbacks) {
        static const wchar_t* dlls[]{L"nvngx_dlss.dll",L"_nvngx.dll"};
        for(unsigned dll=0;dll<2;++dll) {
            HMODULE module=GetModuleHandleW(dlls[dll]);if(!module)continue;
            for(unsigned export_id=0;export_id<2;++export_id) {
                const unsigned slot=dll*2+export_id;
                if(installed[slot])continue;
                void* address=reinterpret_cast<void*>(GetProcAddress(module,exports[export_id]));
                if(!address)continue;
                bool duplicate=false;
                for(unsigned k=0;k<4;++k)
                    if(installed[k] && hooks[k].target()==reinterpret_cast<uint8_t*>(address))
                        duplicate=true;
                if(duplicate)continue;
                HMODULE pinned{};
                if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN,dlls[dll],&pinned))continue;
                auto hook=safetyhook::create_inline(address,callbacks[slot],
                    safetyhook::InlineHook::StartDisabled);
                if(hook) {
                    hooks[slot]=std::move(hook);
                    if(hooks[slot].enable())installed[slot]=true;
                    else hooks[slot].reset();
                }
            }
        }
    }
public:
    static ManualNgxObserver& self() {
        static ManualNgxObserver* instance=new ManualNgxObserver;
        return *instance;
    }
    void set_active(bool active) {
        active_.store(active,std::memory_order_release);
        depth_snapshots().set_enabled(active);
        if(!active)candidates().clear();
    }
    void install() {
        if(!active_.load(std::memory_order_acquire))return;
        std::scoped_lock lock(mutex_);
        install_group(evals_,eval_ok_,
            {"NVSDK_NGX_D3D12_EvaluateFeature","NVSDK_NGX_D3D12_EvaluateFeature_C"},
            {reinterpret_cast<void*>(&evaluate<0>),reinterpret_cast<void*>(&evaluate<1>),
             reinterpret_cast<void*>(&evaluate<2>),reinterpret_cast<void*>(&evaluate<3>)});
        install_group(creates_,create_ok_,
            {"NVSDK_NGX_D3D12_CreateFeature","NVSDK_NGX_D3D12_CreateFeature_C"},
            {reinterpret_cast<void*>(&create<0>),reinterpret_cast<void*>(&create<1>),
             reinterpret_cast<void*>(&create<2>),reinterpret_cast<void*>(&create<3>)});
        install_group(releases_,release_ok_,
            {"NVSDK_NGX_D3D12_ReleaseFeature","NVSDK_NGX_D3D12_ReleaseFeature_C"},
            {reinterpret_cast<void*>(&release<0>),reinterpret_cast<void*>(&release<1>),
             reinterpret_cast<void*>(&release<2>),reinterpret_cast<void*>(&release<3>)});
    }
    void install_queue(ID3D12CommandQueue* queue) {
        if(!active_.load(std::memory_order_acquire) || !queue)return;
        std::scoped_lock lock(mutex_);
        if(!execute_ok_) {
            // ID3D12CommandQueue vtable index 10 = ExecuteCommandLists.
            // 8 UpdateTileMappings, 9 CopyTileMappings, 10 ExecuteCommandLists.
            // ID3D12Pageable has no additional virtual methods.
            auto* vtbl=*reinterpret_cast<void***>(queue);
            if(!vtbl || !vtbl[10])return;
            auto hook=safetyhook::create_inline(vtbl[10],
                reinterpret_cast<void*>(&execute_commands),
                safetyhook::InlineHook::StartDisabled);
            if(hook) {
                execute_=std::move(hook);
                if(execute_.enable())execute_ok_=true;
                else execute_.reset();
            }
        }
        if(execute_ok_)depth_snapshots().bind_queue(queue);
    }
    uint64_t calls()const{return eval_count_.load();}
    uint64_t candidates_seen()const{return qualified_.load();}
    uint64_t errors()const{return errors_.load();}
    uint64_t missing_rhi_ticket()const{return missing_rhi_ticket_.load();}
    uint64_t selected_calls()const{return selected_count_.load();}
    uint64_t inactive_renderer()const{return inactive_renderer_.load();}
    uint64_t stale_packet()const{return stale_packet_.load();}
    uint64_t capture_attempts()const{return capture_attempts_.load();}
    uint32_t last_output_w()const{return last_output_w_.load();}
    uint32_t last_output_h()const{return last_output_h_.load();}
    uint32_t last_render_w()const{return last_render_w_.load();}
    uint32_t last_render_h()const{return last_render_h_.load();}
    uint32_t last_depth_format()const{return last_depth_format_.load();}
    uint32_t last_command_type()const{return last_command_type_.load();}
    uint32_t last_selected_thread()const{return last_selected_thread_.load();}
    uint32_t installed_evaluators() const {
        std::scoped_lock guard(mutex_);
        return static_cast<uint32_t>(std::count(eval_ok_.begin(),eval_ok_.end(),true));
    }
    bool queue_hook_installed() const {
        std::scoped_lock guard(mutex_);
        return execute_ok_;
    }
};
} // namespace uevr::duoview::ngx
