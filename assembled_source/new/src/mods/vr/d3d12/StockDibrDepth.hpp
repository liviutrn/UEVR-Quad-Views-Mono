#pragma once
#include "NgxPairRecovery.hpp"
#include "DepthPolicy.hpp"
#include "../DuoViewNgxGuide.hpp"
#include "CaptureSlotPolicy.hpp"
#include "DepthPinPolicy.hpp"
#include "StableAutoPair.hpp"
#include "ObservedPassCounter.hpp"
#include "DepthCaptureBudget.hpp"
#include "DuoViewDiagnosticDump.hpp"
#include <hooks/D3D12DepthStencilObserver.hpp>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <list>
#include <mutex>
#include <string>
#include <sstream>
#include <cstdint>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

// This existing D3D12Hook TLS guard suppresses recursive barrier-observer callbacks
// while NGX input snapshots record their own resource barriers.
extern thread_local bool g_inside_depth_stencil_observer;
namespace stock_dibr {
// Captures use a verified direct producer queue; alternate queues require an
// explicit producer fence and a GPU wait on the presentation queue. A slot
// belongs to its recording list until actual ExecuteCommandLists, and then to
// its fence until both capture and consumer have retired. No historical image
// is returned when a Present interval contains no newly submitted depth.
class DepthCapture final : public D3D12DepthStencilObserver {
    template<class T> using Ptr = Microsoft::WRL::ComPtr<T>;
    static constexpr size_t Capacity = 48;
    static constexpr size_t NormalCapacity = 12;
    static constexpr size_t DsvCapacity = 4096;
    static constexpr size_t ListCapacity = 256;
    static constexpr size_t ViewportCapacity = 16;
    static constexpr size_t BindingProofCapacity = 64;
    static constexpr size_t ExecutedProofCapacity = 1024;
    static constexpr auto Read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;

    struct Slot {
        Ptr<ID3D12Resource> texture, source;
        Ptr<ID3D12CommandList> list;
        Ptr<IUnknown> list_identity;
        uint64_t epoch{}, serial{}, fence{}, capture_event{};
        uint32_t observed_pass_rank{}; // stamped at the actual depth-write->read barrier
        bool pending{}, leased{};
        // Optional readback-only inputs; all captured on the producer list.
        Ptr<ID3D12Resource> ngx_color, ngx_motion, ngx_color_source, ngx_motion_source;
        uevr::duoview::ngx::Guide ngx_guide{};
        bool ngx_snapshot_complete{};
        bool ngx{};
        uint32_t ngx_role{};
        uintptr_t ngx_handle{};
        uint32_t ngx_out_width{},ngx_out_height{},ngx_in_width{},ngx_in_height{};
        uint32_t ngx_mv_base_x{},ngx_mv_base_y{},ngx_create_flags{},ngx_reset{};
        float ngx_jitter_x{},ngx_jitter_y{},ngx_mv_scale_x{1.f},ngx_mv_scale_y{1.f};
        Ptr<ID3D12Fence> foreign_fence;
        bool quarantined{};
        Layout layout{Layout::Invalid};
        D3D12_VIEWPORT viewport{};
    };
    struct ListState {
        Ptr<ID3D12GraphicsCommandList> owner;
        Ptr<IUnknown> identity;
        SIZE_T bound_dsv_handle{};
        ID3D12Resource* bound_dsv_resource{}; // non-owning; compared only, never dereferenced
        std::array<D3D12_VIEWPORT, ViewportCapacity> viewports{};
        UINT viewport_count{};
        struct BindingProof {
            ID3D12Resource* resource{}; // non-owning; compared only, never dereferenced
            SIZE_T handle{};
            D3D12_VIEWPORT viewport{};
            uint64_t event{};
        };
        std::array<BindingProof, BindingProofCapacity> proofs{};
        UINT proof_count{};
        uint64_t touch{}, event{};
    };
    struct RetiredGeneration {
        Ptr<ID3D12Device> device;
        Ptr<ID3D12CommandQueue> queue;
        Ptr<ID3D12Fence> fence;
        std::array<Slot, Capacity> slots;
        uint64_t signal{};
    };
    struct ExecutedProof {
        ID3D12Resource* resource{}; // non-owning; compared only, never dereferenced
        D3D12_VIEWPORT viewport{};
        Ptr<IUnknown> queue_identity, list_identity;
        uint64_t epoch{}, batch{}, event{};
        UINT list_index{};
    };

    mutable std::mutex mutex;
    std::array<Slot, Capacity> slots;
    Ptr<ID3D12Device> device;
    Ptr<ID3D12CommandQueue> queue;
    Ptr<ID3D12Fence> fence;
    uint64_t width{}, epoch{1}, serial{}, signal{};
    // All recognized source passes, including quota-skipped ones. Interval-local:
    // neither a UE render-stage ID nor an authenticated color-frame token.
    ::duoview::depthpin::ObservedPassCounter observed_passes;
    uint64_t observed_pass_events{}, observed_pass_overflow{};
    uint64_t render_pass_skipped_batches{},late_submit_copy_events{};
    uint64_t selection_transitions{}, selection_failures{}, selection_holds{};
    std::string selection_trace{"not evaluated"};
    std::string selection_identity{"not evaluated"};
    std::array<::duoview::depthpin::Fingerprint,2> last_fresh_pair{}; // full source/layout/pass identities
    uint32_t height{}, recorded_this_interval{}, generic_captures_this_interval{};
    uint64_t pinned_pass_capture_count{}, pinned_pass_slot_exhaustion{},
             reserved_generic_skips{};
    size_t leased{Capacity};
    bool enabled{};
    bool legacy_dsv_capture_enabled{true};
    std::array<uint32_t,4> duoview_source_sizes{};
    std::unordered_map<SIZE_T, ID3D12Resource*> dsv_resources;
    std::unordered_map<SIZE_T, bool> dsv_primary_slice;
    std::deque<SIZE_T> dsv_order;
    std::unordered_map<IUnknown*, ListState> lists;
    std::vector<RetiredGeneration> retired;
    std::deque<ExecutedProof> executed_proofs;
    uint64_t list_touch{};
    uint64_t execute_batch{};
    std::unordered_set<IUnknown*> render_passes;
    std::string last{"waiting for the first scene extent"};
    uint64_t captured{}, submitted{}, consumed{}, exhausted{}, rejected{};
    uint64_t dsv_events{}, bind_events{}, viewport_events{}, read_windows{};
    uint64_t execute_events{}, same_queue_events{}, matched_lists{}, foreign_matches{}, reset_discards{}, cross_queue_consumed{};
    size_t candidate_sources{};
    std::array<uint64_t, 7> reject_reasons{};
    std::string observed{"none"};
    bool snapshot_armed{};
    bool sequence_motion_armed{};
    // This is viewport-SIZE bucketing, deliberately NOT a camera/eye claim.
    // Two distinct scale classes get six producer slots each; previously
    // twelve early, repeated low-resolution passes could exhaust all slots.
    struct NormalSizeBucket { double w{},h{};uint32_t captured{}; };
    std::array<NormalSizeBucket,2> normal_size_buckets{};
    uint64_t normal_bucket_captures[2]{};
    uint64_t normal_bucket_skips[2]{};
    uint64_t normal_extra_shape_skips{};
    // Shape observations are NOT certified left/right producer identity.
    uint64_t ci31_viewport_shape_matches[2]{};
    uint64_t ci31_viewport_shape_copied[2]{};
    uint64_t ci31_viewport_shape_budget_skipped[2]{};
    uint64_t ci31_viewport_shape_ambiguous{};
    uint64_t ci31_viewport_shape_neither{};
    // User-approved per-role source+pass fingerprints, NOT changing ordinals.
    std::array<::duoview::depthpin::RolePins,2> manual_pins{};
    ::duoview::depthpin::RecoveryGate manual_recovery{};
    uevr::duoview::ngx::recovery::PairRecovery ngx_recovery{};
    ::duoview::depthpin::RecoveryGate mixed_switch_recovery{};
    uint64_t mixed_switch_holds{}, mixed_switch_commits{};
    uint64_t pin_generation{1};
    std::array<::duoview::depthpin::Fingerprint,2> auto_candidate_identity{};
    uint64_t auto_last_evaluated_epoch{};
    uint32_t auto_candidate_streak{};
    uint64_t auto_candidate_changes{}, auto_candidate_deferred{};
    uint64_t ngx_copies{}, ngx_rejects{}, ngx_pairs{}, ngx_one_sided{}, ngx_consumed_packet{};
    std::array<uint32_t,2> ngx_copied_this_interval{};

    std::array<bool,Capacity> snapshot_leases{};
    std::unordered_map<std::uintptr_t,std::string> diagnostic_catalog{};
    uint64_t diagnostic_catalog_overflow{};
    // Last successfully submitted DSV/viewport proofs. Metadata only:
    // neither color matching nor a semantic camera/eye assertion.
    std::array<std::string, 4> recent_depth_proofs{};
    uint64_t recent_depth_proof_count{};

    static DXGI_FORMAT storage(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_R32G8X24_TYPELESS: case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
            return DXGI_FORMAT_R32G8X24_TYPELESS;
        case DXGI_FORMAT_D32_FLOAT: case DXGI_FORMAT_R32_FLOAT: case DXGI_FORMAT_R32_TYPELESS:
            return DXGI_FORMAT_R32_TYPELESS;
        case DXGI_FORMAT_D24_UNORM_S8_UINT: case DXGI_FORMAT_R24G8_TYPELESS:
            return DXGI_FORMAT_R24G8_TYPELESS;
        case DXGI_FORMAT_R16_FLOAT: return DXGI_FORMAT_R16_FLOAT;
        case DXGI_FORMAT_D16_UNORM: case DXGI_FORMAT_R16_UNORM: case DXGI_FORMAT_R16_TYPELESS:
            return DXGI_FORMAT_R16_TYPELESS;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    static bool close_extent(double value, double expected) {
        return std::isfinite(value) && std::abs(value - expected) <= 8.0;
    }
    static bool primary_slice(const D3D12_DEPTH_STENCIL_VIEW_DESC* dsv) {
        if (!dsv) return true;
        switch (dsv->ViewDimension) {
        case D3D12_DSV_DIMENSION_TEXTURE2DARRAY: return dsv->Texture2DArray.FirstArraySlice == 0;
        case D3D12_DSV_DIMENSION_TEXTURE2DMSARRAY: return dsv->Texture2DMSArray.FirstArraySlice == 0;
        default: return true;
        }
    }
    bool main_viewport_shape(const D3D12_VIEWPORT& v) const {
        if(duoview_source_sizes[0]) {
            return std::isfinite(v.TopLeftX) && std::isfinite(v.TopLeftY) &&
                v.TopLeftX>=0 && v.TopLeftY>=0 &&
                (duoview_depth_shape(v.Width,v.Height,duoview_source_sizes[0],duoview_source_sizes[1]) ||
                 duoview_depth_shape(v.Width,v.Height,duoview_source_sizes[2],duoview_source_sizes[3]));
        }
        if (!width || !height || !(v.Width > 0.0f) || !(v.Height > 0.0f) ||
            !close_extent(v.TopLeftX, 0.0) || !close_extent(v.TopLeftY, 0.0)) return false;
        const double scale = double(v.Height) / double(height);
        if (scale < 0.20 || scale > 1.01) return false;
        const double eye_width = double(width / 2) * scale;
        const double packed_width = double(width) * scale;
        return close_extent(v.Width, eye_width) || close_extent(v.Width, packed_width);
    }
    Layout classify_viewport(const D3D12_VIEWPORT& v) const {
        if(duoview_source_sizes[0])return main_viewport_shape(v)?Layout::Eye:Layout::Invalid;
        return stock_dibr::layout(static_cast<uint64_t>(std::lround(v.Width)),
            static_cast<uint32_t>(std::lround(v.Height)),width,height);
    }
    bool viewport_matches_source(const D3D12_VIEWPORT& v,
        const D3D12_RESOURCE_DESC& depth, Layout) const {
        // RDG can retain an oversized allocation after a resolution change.
        // The bound viewport, not the allocation, defines current scene pixels.
        return main_viewport_shape(v) && v.TopLeftX >= 0 && v.TopLeftY >= 0 &&
            double(v.TopLeftX) + v.Width <= double(depth.Width) + 0.01 &&
            double(v.TopLeftY) + v.Height <= double(depth.Height) + 0.01;
    }
    void remember_main_bindings(ListState& state) {
        if (!state.bound_dsv_resource) return;
        for (UINT i = 0; i < state.viewport_count; ++i) {
            const auto& viewport = state.viewports[i];
            if (!main_viewport_shape(viewport)) continue;
            bool exists{};
            // Collapse consecutive equal bindings only. A -> B -> A must
            // retain the last A so publication sees the current rectangle.
            for (UINT j = state.proof_count; j > 0; --j) {
                const auto& proof = state.proofs[j - 1];
                if (proof.resource != state.bound_dsv_resource) continue;
                exists = proof.handle == state.bound_dsv_handle &&
                    proof.viewport.TopLeftX == viewport.TopLeftX && proof.viewport.TopLeftY == viewport.TopLeftY &&
                    proof.viewport.Width == viewport.Width && proof.viewport.Height == viewport.Height;
                break;
            }
            if (exists) continue;
            if (state.proof_count == BindingProofCapacity) {
                std::move(state.proofs.begin() + 1, state.proofs.end(), state.proofs.begin());
                --state.proof_count;
            }
            state.proofs[state.proof_count++] = {state.bound_dsv_resource, state.bound_dsv_handle, viewport, state.event};
        }
    }
    bool recorded_viewport(ID3D12Resource* resource,
        const D3D12_RESOURCE_DESC& depth, D3D12_VIEWPORT& selected) const {
        double best{};
        const auto consider = [&](ID3D12Resource* r, const D3D12_VIEWPORT& vp) {
            if (r == resource && viewport_matches_source(vp, depth, Layout::Eye) &&
                double(vp.Width) * vp.Height > best) {
                selected = vp; best = double(vp.Width) * vp.Height;
            }
        };
        for (const auto& [cmd, state] : lists) {
            (void)cmd;
            for (UINT i = 0; i < state.proof_count; ++i) consider(state.proofs[i].resource, state.proofs[i].viewport);
        }
        for (const auto& proof : executed_proofs)
            if (proof.epoch == epoch) consider(proof.resource, proof.viewport);
        return best > 0;
    }
    bool select_executed_main_binding(ID3D12Resource* resource, const D3D12_RESOURCE_DESC& depth,
        IUnknown* producer, IUnknown* capture_list, uint64_t capture_event, uint64_t batch, UINT list_index,
        D3D12_VIEWPORT& selected) const {
        const ExecutedProof* latest{};
        for (const auto& proof : executed_proofs) {
            if (proof.epoch != epoch || proof.resource != resource || proof.queue_identity.Get() != producer ||
                proof.batch > batch || (proof.batch == batch && proof.list_index > list_index)) continue;
            if (proof.batch == batch && proof.list_index == list_index &&
                proof.list_identity.Get() == capture_list && proof.event > capture_event) continue;
            if (!viewport_matches_source(proof.viewport, depth, Layout::Eye)) continue;
            if (!latest || proof.batch > latest->batch ||
                (proof.batch == latest->batch && proof.list_index > latest->list_index) ||
                (proof.batch == latest->batch && proof.list_index == latest->list_index && proof.event > latest->event))
                latest = &proof;
        }
        if (!latest) return false;
        selected = latest->viewport;
        return true;
    }
    bool retire_ready(const Slot& s, ID3D12Fence* f) const {
        if (s.quarantined || s.pending || s.leased) return false;
        if (s.foreign_fence && !completed(s.foreign_fence->GetCompletedValue(), 1)) return false;
        return !s.pending && !s.leased && (!s.fence || (f && completed(f->GetCompletedValue(), s.fence)));
    }
    static Ptr<IUnknown> object_identity(IUnknown* object) {
        Ptr<IUnknown> result;
        if (object) object->QueryInterface(IID_PPV_ARGS(&result));
        return result;
    }
    ListState& list_state(ID3D12GraphicsCommandList* cmd) {
        auto identity = object_identity(cmd);
        auto found = lists.find(identity.Get());
        if (found != lists.end()) { found->second.touch = ++list_touch; return found->second; }
        if (lists.size() >= ListCapacity) {
            auto oldest = lists.begin();
            for (auto it = lists.begin(); it != lists.end(); ++it)
                if (it->second.touch < oldest->second.touch) oldest = it;
            render_passes.erase(oldest->first);
            lists.erase(oldest);
        }
        auto [it, inserted] = lists.emplace(identity.Get(), ListState{});
        (void)inserted;
        it->second.owner = cmd;
        it->second.identity = std::move(identity);
        it->second.touch = ++list_touch;
        return it->second;
    }
    void collect_retired() {
        for (auto generation = retired.begin(); generation != retired.end();) {
            bool ready = true;
            for (auto& s : generation->slots) {
                if (retire_ready(s, generation->fence.Get())) s = {};
                else ready = false;
            }
            if (ready) generation = retired.erase(generation);
            else ++generation;
        }
    }
    void reset_pending_list(std::array<Slot, Capacity>& slots_to_check, ID3D12GraphicsCommandList* cmd) {
        for (auto& s : slots_to_check) if (s.pending && !s.quarantined && s.list_identity.Get() == object_identity(cmd).Get()) {
            s.pending = false; s.epoch = 0; s.fence = 0;
        }
    }
    static bool submitted_by(const Slot& s, UINT count, ID3D12CommandList* const* submitted_lists) {
        if (!s.pending || !submitted_lists) return false;
        for (UINT i = 0; i < count; ++i) if (submitted_lists[i] == s.list.Get() ||
            (s.list_identity && object_identity(submitted_lists[i]).Get() == s.list_identity.Get())) return true;
        return false;
    }
    static bool same_queue(ID3D12CommandQueue* a, ID3D12CommandQueue* b) {
        if (!a || !b) return false;
        if (a == b) return true;
        Ptr<IUnknown> left, right;
        return SUCCEEDED(a->QueryInterface(IID_PPV_ARGS(&left))) &&
            SUCCEEDED(b->QueryInterface(IID_PPV_ARGS(&right))) && left.Get() == right.Get();
    }
    void submit_retired(ID3D12CommandQueue* q, UINT count, ID3D12CommandList* const* submitted_lists) {
        for (auto& generation : retired) {
            for (auto& s : generation.slots) if (submitted_by(s, count, submitted_lists)) {
                s.epoch = 0;
                if (same_queue(q, generation.queue.Get())) {
                    const auto value = ++generation.signal;
                    if (SUCCEEDED(q->Signal(generation.fence.Get(), value))) {
                        s.pending = false; s.fence = value;
                    } else s.quarantined = true;
                } else {
                    Ptr<ID3D12Device> producer_device;
                    if (SUCCEEDED(s.source->GetDevice(IID_PPV_ARGS(&producer_device))) &&
                        SUCCEEDED(producer_device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&s.foreign_fence))) &&
                        SUCCEEDED(q->Signal(s.foreign_fence.Get(), 1))) {
                        s.pending = false; s.fence = 0;
                    } else s.quarantined = true;
                }
            }
        }
    }

public:
    static bool ngx_depth_requested() {
        char value[8]{};
        const auto n=GetEnvironmentVariableA("UEVR_DUOVIEW_NGX_DEPTH",value,sizeof(value));
        return n==0 || value[0]!='0';
    }
    void configure_duoview_sources(uint32_t fw,uint32_t fh,uint32_t pw,uint32_t ph) {
        std::scoped_lock lock{mutex};
        const std::array<uint32_t,4> requested{fw,fh,pw,ph};
        if(requested==duoview_source_sizes)return;
        duoview_source_sizes=requested;
        // Preserve only the explicitly pinned feature; require fresh copies
        // at the new dimensions before recovery can re-enable stereo.
        uevr::duoview::ngx::manual_registry().set_outputs(requested);
        ngx_recovery.reset();
        ++pin_generation; // explicit re-pin required when producer extent changes
        auto_candidate_identity={};auto_candidate_streak=0;auto_last_evaluated_epoch=0;
        last_fresh_pair={};
        ++epoch;recorded_this_interval=0;generic_captures_this_interval=0;
        normal_size_buckets={};diagnostic_catalog.clear();ngx_copied_this_interval={};
        manual_recovery={};mixed_switch_recovery={};
        observed_passes.clear();executed_proofs.clear();
        for(auto& [cmd,state]:lists){(void)cmd;state.proof_count=0;}
    }
    // All inputs are copied AFTER successful native Evaluate, in its documented
    // NPS state (NVIDIA guide 3.4), then restored exactly. Owned copies remain
    // NPS on DIRECT/COMPUTE producers; only the direct consumer adds PS access.
    void capture_ngx_dlss(ID3D12GraphicsCommandList* cmd,ID3D12Resource* src,
        ID3D12Resource* color,ID3D12Resource* mv,const uevr::duoview::ngx::Guide& guide) {
        if(!cmd || !src || !guide.manual_source)return;
        std::scoped_lock guard(mutex);
        const auto type=cmd->GetType();
        if(!enabled || (type!=D3D12_COMMAND_LIST_TYPE_DIRECT && type!=D3D12_COMMAND_LIST_TYPE_COMPUTE))return;
        if(render_passes.contains(object_identity(cmd).Get())){++ngx_rejects;return;}
        // Gallery captures all valid NGX resources, even without an RHI ticket
        // or manual role. Only explicit pins with matching output extents can
        // become stereo candidates; an unassigned capture is diagnostics-only.
        const auto selected_role=guide.role;
        const bool role_compatible=selected_role>=1 && selected_role<=2 && duoview_source_sizes[0] &&
            guide.output_width==duoview_source_sizes[(selected_role-1u)*2] &&
            guide.output_height==duoview_source_sizes[(selected_role-1u)*2+1];
        const auto role=role_compatible?selected_role:0u;
        if(!role_compatible && !snapshot_armed){++ngx_rejects;return;}
        const auto desc=src->GetDesc();
        const auto cd=color?color->GetDesc():D3D12_RESOURCE_DESC{};
        const auto md=mv?mv->GetDesc():D3D12_RESOURCE_DESC{};
        const auto fmt=storage(desc.Format);
        const auto region_valid=[](const D3D12_RESOURCE_DESC& d,UINT x,UINT y,UINT w,UINT h) {
            return d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D && d.DepthOrArraySize==1 &&
                d.SampleDesc.Count==1 && d.MipLevels==1 && w && h && w<=16384 && h<=16384 &&
                uint64_t(x)+w<=d.Width && uint64_t(y)+h<=d.Height;
        };
        const UINT inw=guide.input_width,inh=guide.input_height;
        const UINT mx=guide.motion_extent_known?guide.motion_x:0u;
        const UINT my=guide.motion_extent_known?guide.motion_y:0u;
        const UINT mw=guide.motion_extent_known?(guide.motion_low_resolution?inw:guide.output_width):UINT(md.Width);
        const UINT mh=guide.motion_extent_known?(guide.motion_low_resolution?inh:guide.output_height):md.Height;
        if(fmt==DXGI_FORMAT_UNKNOWN || !region_valid(desc,guide.depth_x,guide.depth_y,inw,inh)) {
            ++ngx_rejects;return;
        }
        const bool color_ok=color && region_valid(cd,guide.color_x,guide.color_y,inw,inh);
        const bool motion_ok=mv && region_valid(md,mx,my,mw,mh) &&
            (md.Format==DXGI_FORMAT_R16G16_FLOAT || md.Format==DXGI_FORMAT_R32G32_FLOAT ||
             md.Format==DXGI_FORMAT_R16G16_SNORM);
        // Color and motion are optional diagnostic planes; neither may veto
        // a valid NGX SR depth sample. The compositor consumes only depth.
        Ptr<IUnknown> expected,owner,command_owner;
        if(!device || FAILED(device.As(&expected)) || FAILED(cmd->GetDevice(IID_PPV_ARGS(&command_owner))) ||
           command_owner.Get()!=expected.Get()){++ngx_rejects;return;}
        owner.Reset();if(FAILED(src->GetDevice(IID_PPV_ARGS(&owner))) || owner.Get()!=expected.Get()) {
            ++ngx_rejects;return;
        }
        const auto same_device=[&](ID3D12Resource* r){
            Ptr<IUnknown> o;return r && SUCCEEDED(r->GetDevice(IID_PPV_ARGS(&o))) && o.Get()==expected.Get();
        };
        const bool capture_color=snapshot_armed && color_ok && same_device(color);
        const bool capture_motion=motion_ok && same_device(mv) && (snapshot_armed || (sequence_motion_armed && role_compatible && uint64_t(mw)*mh*8<=16ull*1024*1024));
        auto candidate=std::find_if(slots.begin(),slots.end(),[&](const Slot& slot){
            const bool unconsumed=slot.ngx && slot.ngx_guide.producer.packet>ngx_consumed_packet &&
                slot.ngx_guide.producer.packet+4>=guide.producer.packet;
            return !unconsumed && capture_slot_reusable(retire_ready(slot,fence.Get()),true,
                slot.texture.Get()!=nullptr,slot.epoch,epoch);
        });
        if(candidate==slots.end()){++ngx_rejects;return;}
        auto& s=*candidate;s.foreign_fence.Reset();
        if(!s.ngx)s.texture.Reset();
        constexpr auto saved_state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        const auto allocate=[&](ID3D12Resource* input,Ptr<ID3D12Resource>& saved,UINT w,UINT h,DXGI_FORMAT format) {
            if(saved) {
                const auto d=saved->GetDesc();
                if(d.Width==w && d.Height==h && d.Format==format)return true;
                saved.Reset();
            }
            auto d=input->GetDesc();d.Width=w;d.Height=h;d.Format=format;d.Flags=D3D12_RESOURCE_FLAG_NONE;d.Alignment=0;
            D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
            return SUCCEEDED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,saved_state,
                nullptr,IID_PPV_ARGS(&saved)));
        };
        const bool full_depth=(desc.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)!=0;
        const UINT dw=full_depth?UINT(desc.Width):inw,dh=full_depth?desc.Height:inh;
        if(!allocate(src,s.texture,dw,dh,fmt)){++ngx_rejects;return;}
        s.ngx_snapshot_complete=false;
        if(snapshot_armed || (sequence_motion_armed && role_compatible)) {
            if(capture_color && !allocate(color,s.ngx_color,inw,inh,cd.Format)) {
                ++ngx_rejects;return;
            }
            if(capture_motion && !allocate(mv,s.ngx_motion,mw,mh,md.Format)) {
                ++ngx_rejects;return;
            }
            if(!capture_color)s.ngx_color.Reset();
            if(!capture_motion)s.ngx_motion.Reset();
        }
        struct Guard {
            bool previous{g_inside_depth_stencil_observer};
            Guard(){g_inside_depth_stencil_observer=true;}
            ~Guard(){g_inside_depth_stencil_observer=previous;}
        } observer_guard;
        const auto copy=[&](ID3D12Resource* input,ID3D12Resource* saved,UINT x,UINT y,UINT w,UINT h) {
            D3D12_RESOURCE_BARRIER barriers[2]{};
            for(auto& b:barriers)b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[0].Transition={input,0,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE};
            barriers[1].Transition={saved,0,saved_state,D3D12_RESOURCE_STATE_COPY_DEST};
            cmd->ResourceBarrier(2,barriers);
            D3D12_TEXTURE_COPY_LOCATION from{},to{};
            from.pResource=input;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            to.pResource=saved;to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            const D3D12_BOX box{x,y,0,x+w,y+h,1};
            const bool full=(input->GetDesc().Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)!=0;
            cmd->CopyTextureRegion(&to,0,0,0,&from,full?nullptr:&box);
            for(auto& b:barriers)std::swap(b.Transition.StateBefore,b.Transition.StateAfter);
            cmd->ResourceBarrier(2,barriers);
        };
        copy(src,s.texture.Get(),guide.depth_x,guide.depth_y,inw,inh);
        if(snapshot_armed || (sequence_motion_armed && role_compatible)) {
            if(capture_color)copy(color,s.ngx_color.Get(),guide.color_x,guide.color_y,inw,inh);
            if(capture_motion)copy(mv,s.ngx_motion.Get(),mx,my,mw,mh);
            s.ngx_color_source=capture_color?color:nullptr;
            s.ngx_motion_source=capture_motion?mv:nullptr;
            s.ngx_snapshot_complete=true;
        } else {s.ngx_color_source.Reset();s.ngx_motion_source.Reset();}
        s.source=src;s.list=cmd;s.list_identity=object_identity(cmd);
        s.epoch=epoch;s.serial=++serial;s.pending=true;s.fence=0;
        s.capture_event=++list_state(cmd).event;s.observed_pass_rank=role;s.layout=Layout::Eye;
        s.viewport={full_depth?float(guide.depth_x):0.f,full_depth?float(guide.depth_y):0.f,float(inw),float(inh),0.f,1.f};
        s.ngx=true;s.ngx_role=role;s.ngx_handle=guide.feature;s.ngx_guide=guide;
        s.ngx_out_width=guide.output_width;s.ngx_out_height=guide.output_height;
        s.ngx_in_width=inw;s.ngx_in_height=inh;s.ngx_mv_base_x=guide.motion_x;s.ngx_mv_base_y=guide.motion_y;
        s.ngx_jitter_x=guide.jitter_x;s.ngx_jitter_y=guide.jitter_y;
        s.ngx_mv_scale_x=guide.motion_scale_x;s.ngx_mv_scale_y=guide.motion_scale_y;
        s.ngx_create_flags=guide.flags;s.ngx_reset=guide.reset;
        ++ngx_copies;
        if(role_compatible)++ngx_copied_this_interval[role-1];
    }
    void set_legacy_dsv_capture_enabled(bool value) {
        std::scoped_lock guard(mutex);legacy_dsv_capture_enabled=value;
    }
    void set_sequence_motion_capture(bool active) {
        std::scoped_lock guard(mutex);sequence_motion_armed=active;
    }
    bool diagnostic_capture_armed() const {
        std::scoped_lock guard(mutex);return snapshot_armed;
    }
    void arm_diagnostic_capture() {
        std::scoped_lock lock{mutex};
        snapshot_armed=true;
    }
    std::string diagnostic_inventory() const {
        std::scoped_lock lock{mutex};
        std::ostringstream o;
        o << "LAST_DEPTH_SELECTION=" << selection_trace
          << " snapshot_armed=" << snapshot_armed << " interval=" << epoch
          << " observer_source_count=" << observed_passes.source_count() << "\n";
        o << "all_DSV_resources_seen=" << (diagnostic_catalog.size()+diagnostic_catalog_overflow)
          << " inventory_capped=" << diagnostic_catalog_overflow
          << " producer_copies_this_interval=" << recorded_this_interval
          << " producer_capacity=" << (snapshot_armed ? Capacity : NormalCapacity);
        o << "\nCURRENT COPY SLOTS (producer completion is not consumer retirement):";
        for(size_t i=0;i<slots.size();++i) {
            const auto& s=slots[i];if(!s.texture)continue;
            o << "\nslot="<<i<<" serial="<<s.serial<<" epoch="<<s.epoch
              <<" currentEpoch="<<epoch<<" pending="<<s.pending<<" leased="<<s.leased
              <<" captureLease="<<snapshot_leases[i]<<" quarantined="<<s.quarantined
              <<" fence="<<s.fence<<" foreign="<<bool(s.foreign_fence)
              <<" viewport="<<s.viewport.Width<<"x"<<s.viewport.Height
              <<" observedPass="<<s.observed_pass_rank
              <<" srcDSV=0x"<<std::hex<<reinterpret_cast<std::uintptr_t>(s.source.Get())<<std::dec;
        }
        for (const auto& [ptr,detail] : diagnostic_catalog) o << "\n" << detail;
        return o.str();
    }
    std::vector<uevr::duoview::diag::Candidate> snapshot_candidates(uint64_t selected_left_serial=0,uint64_t selected_right_serial=0,bool gallery=false) {
        std::scoped_lock lock{mutex};
        std::vector<uevr::duoview::diag::Candidate> result;
        if(!enabled || !snapshot_armed) return result;
        if(!gallery && (!selected_left_serial || !selected_right_serial)) return result;
        result.reserve(Capacity);
        for (size_t i=0;i<slots.size();++i) {
            auto& s=slots[i];
            if(!s.ngx)continue; // CI69: DLSS-only gallery, never DSV.
            if(!gallery && s.serial!=selected_left_serial && s.serial!=selected_right_serial)continue;
            if(!s.texture || s.pending || (s.leased && !snapshot_leases[i]) ||
               s.quarantined || (s.epoch!=epoch && !s.ngx) ||
               (!s.fence && !s.foreign_fence)) continue;
            if(s.foreign_fence && (!queue || FAILED(queue->Wait(s.foreign_fence.Get(),1)))) {
                last="diagnostic candidate foreign-queue GPU wait rejected";
                continue;
            }
            uevr::duoview::diag::Candidate c;
            c.source=s.texture;c.state=s.ngx?D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE:Read;c.serial=s.serial;
            const auto d=s.texture->GetDesc();
            std::ostringstream label;
            label << "NGX_DepthSource=0x" << std::hex << reinterpret_cast<std::uintptr_t>(s.source.Get())
                  << " NGX_feature=0x" << s.ngx_handle << std::dec
                  << " evaluation=" << s.ngx_guide.evaluation
                  << " role=" << s.ngx_role
                  << " output=" << s.ngx_out_width << "x" << s.ngx_out_height
                  << " input=" << s.ngx_in_width << "x" << s.ngx_in_height
                  << " epoch=" << s.epoch << " serial=" << s.serial
                  << " observedPass=" << s.observed_pass_rank
                  << " gpuCopyState=SUBMITTED_ELIGIBLE_UNVERIFIED_FRAME"
                  << " depthImage=depth_" << s.serial
                  << " format=" << unsigned(d.Format)
                  << " viewport=(" << s.viewport.TopLeftX << "," << s.viewport.TopLeftY
                  << "," << s.viewport.Width << "," << s.viewport.Height << ")"
                  << " layout=" << (s.layout==Layout::Eye ? "eye" : "packed")
                  << " eyeAttribution=UNPROVEN";
            c.details=label.str();
            c.ngx_guide=s.ngx_guide;c.plane=s.ngx?uevr::duoview::diag::GuidePlane::depth:uevr::duoview::diag::GuidePlane::none;
            if(s.ngx)
                c.label="ngx_feature_"+std::to_string(s.ngx_handle)+"_eval_"+
                    std::to_string(s.ngx_guide.evaluation)+"_depth";
            result.push_back(std::move(c));
            if(s.ngx && (gallery || s.serial==selected_left_serial || s.serial==selected_right_serial)) {
                const auto role=s.ngx_role==1?"left_fovea":s.ngx_role==2?"right_periphery":"unassigned";
                const auto details=std::string("serial=")+std::to_string(s.serial)+
                    " out="+std::to_string(s.ngx_out_width)+"x"+std::to_string(s.ngx_out_height)+
                    " in="+std::to_string(s.ngx_in_width)+"x"+std::to_string(s.ngx_in_height)+
                    " jitter=("+std::to_string(s.ngx_jitter_x)+","+std::to_string(s.ngx_jitter_y)+")"+
                    " MVscale=("+std::to_string(s.ngx_mv_scale_x)+","+std::to_string(s.ngx_mv_scale_y)+")"+
                    " MVbase=("+std::to_string(s.ngx_mv_base_x)+","+std::to_string(s.ngx_mv_base_y)+")"+
                    " flags="+std::to_string(s.ngx_create_flags)+" reset="+std::to_string(s.ngx_reset);
                if(s.ngx_snapshot_complete && s.ngx_color) {
                    uevr::duoview::diag::Candidate c;
                    c.source=s.ngx_color;c.state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;c.serial=s.serial;
                    c.label=std::string("ngx_")+role+"_color";c.depth=false;c.details=details;c.ngx_guide=s.ngx_guide;c.plane=uevr::duoview::diag::GuidePlane::color;
                    result.push_back(std::move(c));
                }
                if(s.ngx_snapshot_complete && s.ngx_motion) {
                    uevr::duoview::diag::Candidate c;
                    c.source=s.ngx_motion;c.state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;c.serial=s.serial;
                    c.label=std::string("ngx_")+role+"_motion";c.depth=false;c.details=details;c.ngx_guide=s.ngx_guide;c.plane=uevr::duoview::diag::GuidePlane::motion;
                    result.push_back(std::move(c));
                }
            }
            s.leased=true;
            snapshot_leases[i]=true;
        }
        return result;
    }
    struct PreviewPair {
        Ptr<ID3D12Resource> left, right;
        std::array<Ptr<ID3D12Resource>,2> selected_motion{};
        uint64_t left_serial{},right_serial{},left_epoch{},right_epoch{};
        std::array<uevr::duoview::ngx::Guide,2> ngx_guides{};
        uint32_t left_pass{},right_pass{};
        bool left_backup_latched{},right_backup_latched{};
        std::uintptr_t left_dsv{},right_dsv{};
        std::string decision{"not evaluated"};
        D3D12_VIEWPORT left_viewport{}, right_viewport{};
        std::string label;
        size_t count{};
    };
    std::vector<size_t> preview_indices() const {
        // Preserve separately captured source passes even when Unreal reuses a DSV.
        std::vector<size_t> out;
        for(size_t i=0;i<slots.size();++i) {
            const auto& s=slots[i];
            if(!s.texture || !s.source || (s.epoch!=epoch && !s.ngx) || s.pending ||
               (s.leased && !snapshot_leases[i]) || s.quarantined || (!s.fence && !s.foreign_fence)) continue;
            out.push_back(i);
        }
        std::sort(out.begin(),out.end(),[&](size_t a,size_t b) {
            const auto pa=reinterpret_cast<std::uintptr_t>(slots[a].source.Get());
            const auto pb=reinterpret_cast<std::uintptr_t>(slots[b].source.Get());
            return pa==pb ? slots[a].serial<slots[b].serial : pa<pb;
        });
        return out;
    }
    // Every frame supplies *new* captured textures. These fingerprints only
    // identify the preferred pass amongst current-epoch eligible submissions.
    std::vector<::duoview::depthpin::Fingerprint> preview_fingerprints(
        const std::vector<size_t>& ids) const {
        std::vector<::duoview::depthpin::Observation> observations;
        observations.reserve(ids.size());
        for(const auto idx:ids) {
            const auto& s=slots[idx];
            const auto d=s.texture->GetDesc();
            const auto u=[](float f)->uint32_t {
                return std::isfinite(f) && f>=0.0f ? uint32_t(std::lround(f)) : 0u;
            };
            // Immutable at the original barrier; not reconstructed from the
            // currently retained GPU slot inventory (which may lose skipped
            // and overwritten passes).
            observations.push_back({reinterpret_cast<std::uintptr_t>(s.source.Get()),
                u(s.viewport.TopLeftX),u(s.viewport.TopLeftY),
                u(s.viewport.Width),u(s.viewport.Height),
                uint32_t(d.Width),d.Height,uint32_t(d.Format),s.observed_pass_rank});
        }
        return ::duoview::depthpin::fingerprint(observations,pin_generation);
    }
    struct Browser {
        std::vector<::duoview::depthpin::Fingerprint> keys;
        std::string inventory;
    };
    Browser browse_preview_candidates() const {
        std::scoped_lock lock{mutex};
        Browser snapshot;
        const auto indices=preview_indices();
        snapshot.keys=preview_fingerprints(indices);
        std::ostringstream out;
        out<<"Candidates: "<<indices.size()
           <<"; numbers TEMPORARY. observedPass counts recognized DSV barriers BEFORE capture budget skips."
           <<" Resource/pass may rotate after save/reload; neither eye nor frame is authenticated.";
        for(size_t k=0;k<indices.size();++k) {
            const auto& s=slots[indices[k]];
            const auto& f=snapshot.keys[k];
            const bool fovea=duoview_depth_shape(s.viewport.Width,s.viewport.Height,
                duoview_source_sizes[0],duoview_source_sizes[1]);
            const bool periph=duoview_depth_shape(s.viewport.Width,s.viewport.Height,
                duoview_source_sizes[2],duoview_source_sizes[3]);
            out<<"\n#"<<k+1<<" DSV=0x"<<std::hex<<f.source<<std::dec
               <<" pass="<<f.stage<<" vp="<<f.viewport_w<<"x"<<f.viewport_h
               <<" depthTex="<<f.texture_w<<"x"<<f.texture_h
               <<" fmt="<<f.format <<" copySerial="<<s.serial
               <<" interval="<<s.epoch <<" observedPass="<<s.observed_pass_rank
               <<" candidate-for="<<(fovea?"LEFT-fovea ":"")
               <<(periph?"RIGHT-periphery":"")
               <<(!fovea&&!periph?"UNMATCHED":"")
               <<" [shape only; not proven eye]";
        }
        snapshot.inventory=out.str();
        return snapshot;
    }
    bool pin_preview_candidate(int role,bool backup,
        const ::duoview::depthpin::Fingerprint& expected) {
        std::scoped_lock lock{mutex};
        if(role<0 || role>=2 || !enabled)return false;
        const auto ids=preview_indices();
        const auto keys=preview_fingerprints(ids);
        const auto match=std::find(keys.begin(),keys.end(),expected);
        if(match==keys.end())return false; // UI snapshot changed: never pin a different ordinal
        // Role-aware shape check. Does NOT pretend to prove eye/camera attribution.
        const int k=role*2;
        if(!duoview_depth_shape(expected.viewport_w,expected.viewport_h,
            duoview_source_sizes[size_t(k)],duoview_source_sizes[size_t(k+1)]))return false;
        const bool ok=::duoview::depthpin::set_pin(manual_pins[size_t(role)],backup,keys,
            int(std::distance(keys.begin(),match))+1);
        if(ok) {
            auto_candidate_identity={};auto_candidate_streak=0;auto_last_evaluated_epoch=0;
            last_fresh_pair={};
            manual_recovery={};mixed_switch_recovery={};
            last="Build46 manual depth fingerprint pinned; waiting for current-epoch match";
        }
        return ok;
    }
    void clear_preview_pins(int role) {
        std::scoped_lock lock{mutex};
        if(role<0 || role>=2)return;
        ::duoview::depthpin::clear(manual_pins[size_t(role)]);
        auto_candidate_identity={};auto_candidate_streak=0;auto_last_evaluated_epoch=0;
        last_fresh_pair={};
        manual_recovery={};mixed_switch_recovery={};
        last="Build46 manual pin cleared; role returned to automatic heuristic";
    }
    std::string selection_status() const {
        std::scoped_lock lock{mutex};
        return selection_trace;
    }
    std::string preview_pin_status() const {
        std::scoped_lock lock{mutex};
        const auto ids=preview_indices();
        const auto keys=preview_fingerprints(ids);
        std::ostringstream out;
        for(int role=0;role<2;++role) {
            if(role)out<<"\n";
            out<<(role==0?"LEFT FOVEA":"RIGHT PERIPHERY")<<": ";
            const auto& pins=manual_pins[size_t(role)];
            if(!pins.primary.enabled) {out<<"AUTO (heuristic; may switch)";continue;}
            const auto print=[&](const char* name,const ::duoview::depthpin::Pin& pin) {
                if(!pin.enabled) {out<<name<<" none";return;}
                const int match=::duoview::depthpin::find_exact(keys,pin);
                out<<name<<" DSV=0x"<<std::hex<<pin.key.source<<std::dec
                   <<" stage="<<pin.key.stage<<" viewport="
                   <<pin.key.viewport_w<<"x"<<pin.key.viewport_h
                   <<" ("<<(match>0?"READY #"+std::to_string(match):"NOT PRESENT / RE-PIN IF NEEDED")<<")";
            };
            print("PRIMARY",pins.primary);
            out<<"; ";print("BACKUP",pins.backup);
            if(pins.backup_latched)out<<" [BACKUP LATCHED until Pin PRIMARY or Clear]";
        }
        if(manual_recovery.waiting)
            out<<"\nCURRENT OUTPUT: V3 mono recovery hold; valid pinned pairs "
               <<manual_recovery.consecutive<<"/8 consecutive Present epochs required";
        return out.str();
    }
    size_t preview_count() const {
        std::scoped_lock lock{mutex};
        return preview_indices().size();
    }
    std::string preview_inventory() const {
        std::scoped_lock lock{mutex};
        std::ostringstream out;
        const auto indices=preview_indices();
        out<<"GPU-submitted eligible snapshots: "<<indices.size()
           <<"; same source DSV may have MULTIPLE pass captures;"
              " ordinals by DSV identity then serial (may change on reload)";
        const auto keys=preview_fingerprints(indices);
        for(size_t k=0;k<indices.size()&&k<48;++k) {
            const auto& s=slots[indices[k]];
            const auto d=s.texture->GetDesc();
            out<<"\n"<<k+1<<": DSV=0x"<<std::hex
               <<reinterpret_cast<std::uintptr_t>(s.source.Get())<<std::dec
               <<" PASS="<<keys[k].stage<<" serial="<<s.serial<<" epoch="<<s.epoch
               <<" size="<<d.Width<<"x"<<d.Height
               <<" viewport="<<s.viewport.Width<<"x"<<s.viewport.Height
               <<" fmt="<<static_cast<unsigned>(d.Format)<<" eye=UNVERIFIED";
        }
        return out.str();
    }
    PreviewPair select_preview(int left_selector,int right_selector,
                               UINT left_width,UINT left_height,
                               UINT right_width,UINT right_height,bool require_probation=true,
                               uint64_t color_packet=0,uint64_t color_generation=0,
                               unsigned debug_preview_mode=0u) {
        std::scoped_lock lock{mutex};
        (void)require_probation; // all stereo modes now use the same Auto probation
        PreviewPair r{};
        auto trace=[&](std::string state, std::string stable_identity={}) {
            if(stable_identity.empty())stable_identity=state;
            if(selection_identity!=stable_identity) {
                ++selection_transitions;selection_identity=std::move(stable_identity);
            }
            selection_trace=std::move(state); // latest serials, not a transition counter
            r.decision=selection_trace;
        };
        if(!enabled) {trace("capture_inactive");++selection_failures;return r;}
        auto ids=preview_indices();
        // Opt-in NGX source takes priority ONLY with a fresh TWO-role pair.
        if(ngx_depth_requested()) {
            size_t l=Capacity,rr=Capacity;
            for(const auto index:ids){
                const auto& s=slots[index];
                if(!s.ngx || s.ngx_role<1 || s.ngx_role>2 ||
                   !s.ngx_guide.manual_source ||
                   uevr::duoview::ngx::manual_registry().role(s.ngx_guide.feature,s.ngx_out_width,s.ngx_out_height)!=s.ngx_role ||
                   s.epoch+2<epoch)continue;
                auto& chosen=s.ngx_role==1?l:rr;
                if(chosen==Capacity || s.serial>slots[chosen].serial)chosen=index;
            }
            // CI70 independent debug preview: no nearby-evaluation stereo
            // assumptions. A single valid manually pinned NGX depth is enough.
            if(debug_preview_mode>=1u && debug_preview_mode<=3u) {
                const auto accepted=[&](size_t i,unsigned role) -> bool {
                    if(i==Capacity)return false;
                    auto& slot=slots[i];
                    if(slot.ngx_role!=role || slot.ngx_guide.output_width!=
                        (role==1?left_width:right_width) || slot.ngx_guide.output_height!=
                        (role==1?left_height:right_height))return false;
                    if(slot.foreign_fence && (!queue || FAILED(queue->Wait(slot.foreign_fence.Get(),1))))return false;
                    slot.leased=true;snapshot_leases[i]=true;
                    return true;
                };
                const bool left_ok=debug_preview_mode!=2u && accepted(l,1u);
                const bool right_ok=debug_preview_mode!=1u && accepted(rr,2u);
                if(left_ok) {
                    auto& s=slots[l];r.left=s.texture;r.left_serial=s.serial;r.left_epoch=s.epoch;
                    r.left_pass=1u;r.left_viewport=s.viewport;r.ngx_guides[0]=s.ngx_guide;
                }
                if(right_ok) {
                    auto& s=slots[rr];r.right=s.texture;r.right_serial=s.serial;r.right_epoch=s.epoch;
                    r.right_pass=2u;r.right_viewport=s.viewport;r.ngx_guides[1]=s.ngx_guide;
                }
                const bool success=(debug_preview_mode==1u?left_ok:
                                   debug_preview_mode==2u?right_ok:(left_ok&&right_ok));
                r.decision=success?"NGX_INDEPENDENT_DEPTH_PREVIEW_NO_STEREO_PROVENANCE":"NGX_PREVIEW_SOURCE_MISSING";
                r.label=r.decision+" L="+std::to_string(r.left_serial)+" R="+std::to_string(r.right_serial);
                selection_trace=r.label;r.count=ids.size();return r;
            }
            if(l!=Capacity && rr!=Capacity && l!=rr &&
               !(slots[l].ngx_handle==slots[rr].ngx_handle &&
                 slots[l].ngx_out_width==slots[rr].ngx_out_width &&
                 slots[l].ngx_out_height==slots[rr].ngx_out_height) &&
               slots[l].ngx_guide.output_width==left_width && slots[l].ngx_guide.output_height==left_height &&
               slots[rr].ngx_guide.output_width==right_width && slots[rr].ngx_guide.output_height==right_height &&
               (std::max)(slots[l].epoch,slots[rr].epoch)-(std::min)(slots[l].epoch,slots[rr].epoch)<=1 &&
               (std::max)(slots[l].ngx_guide.evaluation,slots[rr].ngx_guide.evaluation)-
                   (std::min)(slots[l].ngx_guide.evaluation,slots[rr].ngx_guide.evaluation)<=6) {
                auto& left=slots[l];auto& right=slots[rr];
                const auto wait_foreign=[&](const Slot& s){
                    return !s.foreign_fence || (queue && SUCCEEDED(queue->Wait(s.foreign_fence.Get(),1)));
                };
                if(wait_foreign(left) && wait_foreign(right)) {
                    namespace recovery=uevr::duoview::ngx::recovery;
                    const recovery::Observation recovery_observation{true,
                        {uint64_t(left.ngx_guide.feature),left.ngx_out_width,left.ngx_out_height,
                         uint64_t(right.ngx_guide.feature),right.ngx_out_width,right.ngx_out_height},
                        epoch,{left.serial,right.serial},
                        {left.ngx_guide.evaluation,right.ngx_guide.evaluation}};
                    const auto recovered=ngx_recovery.observe(recovery_observation);
                    if(!recovered.allow) {
                        std::ostringstream status;
                        status<<"CI76_NGX_RECOVERY "<<unsigned(recovered.consecutive_fresh_pairs)
                              <<"/8 fresh pairs; "<<recovery::reason_name(recovered.reason)
                              <<" expected L="<<left_width<<"x"<<left_height
                              <<" R="<<right_width<<"x"<<right_height;
                        r.label=status.str();r.decision=r.label;selection_trace=r.label;
                        return r; // no retained depth; deliberate current-source mono
                    }
                    left.leased=true;right.leased=true;
                    snapshot_leases[l]=true;snapshot_leases[rr]=true;
                    r.left=left.texture;r.right=right.texture;r.ngx_guides={left.ngx_guide,right.ngx_guide};
                    if(left.ngx_snapshot_complete)r.selected_motion[0]=left.ngx_motion;
                    if(right.ngx_snapshot_complete)r.selected_motion[1]=right.ngx_motion;
                    r.left_serial=left.serial;r.right_serial=right.serial;
                    r.left_epoch=left.epoch;r.right_epoch=right.epoch;
                    r.left_pass=1;r.right_pass=2;
                    r.left_dsv=reinterpret_cast<uintptr_t>(left.source.Get());
                    r.right_dsv=reinterpret_cast<uintptr_t>(right.source.Get());
                    r.left_viewport=left.viewport;r.right_viewport=right.viewport;
                    r.decision="CI76_NGX_FRESH_PAIR_8of8_MANUAL_CAMERA_FRAME_UNVERIFIED";
                    r.label=r.decision+" L="+std::to_string(left.serial)+" R="+std::to_string(right.serial);
                    r.count=ids.size();trace(r.label,"ngx_pair");++ngx_pairs;
                    ngx_consumed_packet=(std::max)(ngx_consumed_packet,color_packet);
                    return r;
                }
            }
            ngx_recovery.reject();
            ++ngx_one_sided;
            r.decision="NGX_MANUAL_PAIR_UNAVAILABLE_MONO_FALLBACK";
            r.label="CI76 DLSS pair missing for packet="+std::to_string(color_packet)+
                "; current-source mono, expected L="+std::to_string(left_width)+"x"+std::to_string(left_height)+
                " R="+std::to_string(right_width)+"x"+std::to_string(right_height)+
                "; same-feature pins follow resize; a released/replaced feature requires re-pin";
            selection_trace=r.label;
            return r;
        }
        ids.erase(std::remove_if(ids.begin(),ids.end(),[&](size_t i){return slots[i].ngx;}),ids.end());
        r.count=ids.size();
        if(ids.size()<2) {
            trace("missing_eligible_depth_pair");++selection_failures;
            if(manual_pins[0].primary.enabled || manual_pins[1].primary.enabled)
                ::duoview::depthpin::lost_pair(manual_recovery);
            auto_candidate_streak=0;
            auto_candidate_identity={};
            return r;
        }
        std::array<DepthShape,Capacity> shapes{};
        for(size_t k=0;k<ids.size();++k) {
            const auto& s=slots[ids[k]];
            shapes[k]={s.viewport.Width,s.viewport.Height,s.serial};
        }
        // Joint relative-scale matching accommodates DLSS. Two 50%-scale
        // foveal copies cannot substitute for the 20%-size periphery source.
        // Manual ordinals remain exact; this is still NOT semantic eye proof.
        const auto fingerprints=preview_fingerprints(ids);
        const auto ls=::duoview::depthpin::alternatives(fingerprints,manual_pins[0]);
        const auto rs=::duoview::depthpin::alternatives(fingerprints,manual_pins[1]);
        // User pins override old per-frame ordinals. Missing pin means no
        // alternative unless the user has explicitly approved a backup.
        // Try primary/backup combinations, each checked by existing geometry
        // and coherent-scale restrictions; never invent producer identity.
        DepthPairChoice chosen{};
        for(const int l:ls) {
            for(const int rr:rs) {
                chosen=choose_duoview_depth_pair(
                    std::span<const DepthShape>{shapes.data(),ids.size()},
                    l,rr,left_width,left_height,right_width,right_height);
                if(chosen.valid)break;
            }
            if(chosen.valid)break;
        }
        if(!chosen.valid) {
            trace("invalid_pair_or_pinned_pass_absent");++selection_failures;
            if(manual_pins[0].primary.enabled || manual_pins[1].primary.enabled)
                ::duoview::depthpin::lost_pair(manual_recovery);
            auto_candidate_streak=0;
            auto_candidate_identity={};
            return r;
        }
        if(manual_pins[0].primary.enabled != manual_pins[1].primary.enabled &&
           last_fresh_pair[0].source && last_fresh_pair[1].source) {
            chosen=::duoview::depthpin::prefer_allowed_previous_pair_exact(
                std::span<const DepthShape>{shapes.data(),ids.size()},fingerprints,
                last_fresh_pair,chosen,ls,rs,
                left_width,left_height,right_width,right_height);
        }
        size_t a=ids[chosen.left],b=ids[chosen.right];
        if(left_selector==0 && right_selector==0 &&
            !manual_pins[0].primary.enabled && !manual_pins[1].primary.enabled) {
            // Source identity alone is not pass identity: the same DSV can
            // be reused many times. Include the ordered write-version rank
            // WITHIN each resource's submitted passes in this epoch.
            // Use rank over ALL captured passes, not just currently eligible
            // copies (an earlier pending copy must not renumber this pass).
            auto full_key=[&](size_t slot)->::duoview::depthpin::Fingerprint {
                const auto it=std::find(ids.begin(),ids.end(),slot);
                return fingerprints[size_t(it-ids.begin())];
            };
            // If the prior fully confirmed pair is still present and its
            // geometry remains legal, keep it even when heuristic tie-order
            // chooses another valid-looking pass. No old GPU resource is used.
            // Preserve a legal prior pair in BOTH legacy and surface modes.
            // New and legacy Auto pairs require confirmation before first use or switching.
            // This is fresh-copy stickiness, not reuse of a depth texture.
            if(auto_candidate_streak >= 3u) {
                const auto prior=::duoview::depthpin::prefer_previous_pair_exact(
                    std::span<const DepthShape>{shapes.data(),ids.size()},fingerprints,
                    auto_candidate_identity,chosen,left_width,left_height,right_width,right_height);
                if(prior.valid){a=ids[prior.left];b=ids[prior.right];}
            }
            const std::array<::duoview::depthpin::Fingerprint,2> current{
                full_key(a),full_key(b)
            };
            // No reuse of stale *textures*: this key ONLY gates fresh epoch
            // candidates, which still must have passed the geometry test.
            // It is a flicker safety gate, NOT source eye/stage verification.
            if(auto_last_evaluated_epoch!=epoch) {
                const bool consecutive=auto_last_evaluated_epoch &&
                    epoch==auto_last_evaluated_epoch+1;
                if(!consecutive || current!=auto_candidate_identity) {
                    if(auto_last_evaluated_epoch &&
                       current!=auto_candidate_identity)++auto_candidate_changes;
                    auto_candidate_identity=current;
                    auto_candidate_streak=1;
                } else if(auto_candidate_streak<1000000u) {
                    ++auto_candidate_streak;
                }
                auto_last_evaluated_epoch=epoch;
            }
            if(auto_candidate_streak<3) {
                ++auto_candidate_deferred;
                last="Auto depth pair unconfirmed; waiting in V3 mono";
                trace("auto_pair_probation");++selection_holds;
                return r;
            }
        }
        // Queue waits are GPU operations and can fail independently. Preflight
        // BOTH before leasing EITHER slot; a failed second wait must not strand
        // the left source for the rest of this epoch.
        auto queue_ready=[&](size_t i)->bool {
            const auto& s=slots[i];
            return !s.foreign_fence || (queue &&
                SUCCEEDED(queue->Wait(s.foreign_fence.Get(),1)));
        };
        if(!queue_ready(a)||!queue_ready(b)) {
            trace("queue_wait_failed");++selection_failures;
            if(manual_pins[0].primary.enabled || manual_pins[1].primary.enabled)
                ::duoview::depthpin::lost_pair(manual_recovery);
            return r;
        }
        // An automatic partner of a manual pin may not silently change on
        // one plausible frame. If a previous fresh pair disappears, confirm
        // the NEW exact partner for three consecutive eligible epochs.
        const bool mixed_pin=manual_pins[0].primary.enabled != manual_pins[1].primary.enabled;
        const bool prior_mixed=last_fresh_pair[0].source && last_fresh_pair[1].source;
        const bool changing_mixed=mixed_pin && prior_mixed &&
            (fingerprints[chosen.left]!=last_fresh_pair[0] ||
             fingerprints[chosen.right]!=last_fresh_pair[1]);
        if(changing_mixed) {
            if(!mixed_switch_recovery.waiting)
                ::duoview::depthpin::lost_pair(mixed_switch_recovery);
            if(!::duoview::depthpin::allow_stable_fresh_pair(mixed_switch_recovery,epoch,
                fingerprints[chosen.left],fingerprints[chosen.right],3)) {
                trace("mixed_auto_partner_unconfirmed");
                ++selection_holds;++mixed_switch_holds;
                return r;
            }
            ++mixed_switch_commits;
        } else mixed_switch_recovery={};
        if((manual_pins[0].primary.enabled || manual_pins[1].primary.enabled) &&
            !::duoview::depthpin::allow_stable_fresh_pair(manual_recovery,epoch,
                fingerprints[chosen.left],fingerprints[chosen.right])) {
            trace("manual_recovery_hold");++selection_holds;
            return r; // stable V3 mono, resume after 8 fresh pairs
        }
        auto lease=[&](size_t i)->Ptr<ID3D12Resource> {
            auto& s=slots[i];
            s.leased=true;snapshot_leases[i]=true;return s.texture;
        };
        // Full fresh pair identity is retained for partially manual selections.
        // Only source identity and observed pass rank are held, not GPU depth.
        last_fresh_pair={fingerprints[size_t(std::find(ids.begin(),ids.end(),a)-ids.begin())],
            fingerprints[size_t(std::find(ids.begin(),ids.end(),b)-ids.begin())]};
        // Backup becomes sticky only after BOTH producer queue waits succeed.
        // It never switches back on a transient primary recovery.
        ::duoview::depthpin::commit_backup(manual_pins[0],
            int(std::find(ids.begin(),ids.end(),a)-ids.begin())+1,fingerprints);
        ::duoview::depthpin::commit_backup(manual_pins[1],
            int(std::find(ids.begin(),ids.end(),b)-ids.begin())+1,fingerprints);
        r.left_backup_latched=manual_pins[0].backup_latched;
        r.right_backup_latched=manual_pins[1].backup_latched;
        r.left=lease(a);
        r.right=lease(b);
        r.left_serial=slots[a].serial;r.right_serial=slots[b].serial;
        r.left_epoch=slots[a].epoch;r.right_epoch=slots[b].epoch;
        r.left_pass=slots[a].observed_pass_rank;r.right_pass=slots[b].observed_pass_rank;
        r.left_dsv=reinterpret_cast<std::uintptr_t>(slots[a].source.Get());
        r.right_dsv=reinterpret_cast<std::uintptr_t>(slots[b].source.Get());
        r.decision="fresh_pair_selected_UNAUTHENTICATED";
        { std::ostringstream decision;
          decision<<"selected_L:DSV=0x"<<std::hex<<r.left_dsv<<std::dec
                  <<"/pass="<<r.left_pass<<"/serial="<<r.left_serial
                  <<" selected_R:DSV=0x"<<std::hex<<r.right_dsv<<std::dec
                  <<"/pass="<<r.right_pass<<"/serial="<<r.right_serial
                  <<" interval="<<epoch
                  <<" pins="<<manual_pins[0].primary.enabled<<","<<manual_pins[1].primary.enabled
                  <<" backupLatched="<<r.left_backup_latched<<","<<r.right_backup_latched
                  <<" generation="<<pin_generation;
          std::ostringstream identity;
          identity<<std::hex<<r.left_dsv<<":"<<std::dec<<r.left_pass
                  <<":"<<std::hex<<r.right_dsv<<":"<<std::dec<<r.right_pass
                  <<":"<<manual_pins[0].primary.enabled<<":"<<manual_pins[1].primary.enabled
                  <<":"<<r.left_backup_latched<<":"<<r.right_backup_latched
                  <<":"<<pin_generation;
          trace(decision.str(),identity.str()); }
        r.left_viewport=slots[a].viewport;
        r.right_viewport=slots[b].viewport;
        std::ostringstream label;
        label<<"left_pin="<<(manual_pins[0].primary.enabled?"LOCKED":"AUTO")
             <<" right_pin="<<(manual_pins[1].primary.enabled?"LOCKED":"AUTO")
             <<" left_pass="<<r.left_pass
             <<" right_pass="<<r.right_pass
             <<" left_copy_serial="<<r.left_serial
             <<" right_copy_serial="<<r.right_serial
             <<" interval="<<r.left_epoch<<" "
             <<"left_choice="<<left_selector<<" left_DSV=0x"<<std::hex
             <<reinterpret_cast<std::uintptr_t>(slots[a].source.Get())
             <<" right_choice="<<std::dec<<right_selector<<" right_DSV=0x"<<std::hex
             <<reinterpret_cast<std::uintptr_t>(slots[b].source.Get())<<std::dec
             <<" serials="<<slots[a].serial<<","<<slots[b].serial
             <<" wantedViewports=L:"<<left_width<<"x"<<left_height
             <<" R:"<<right_width<<"x"<<right_height
             <<" actualViewports=L:("<<slots[a].viewport.TopLeftX<<","<<slots[a].viewport.TopLeftY
             <<","<<slots[a].viewport.Width<<","<<slots[a].viewport.Height
             <<") R:("<<slots[b].viewport.TopLeftX<<","<<slots[b].viewport.TopLeftY
             <<","<<slots[b].viewport.Width<<","<<slots[b].viewport.Height<<")"
             <<" depthRanges=L:("<<slots[a].viewport.MinDepth<<","<<slots[a].viewport.MaxDepth
             <<") R:("<<slots[b].viewport.MinDepth<<","<<slots[b].viewport.MaxDepth<<")"
             <<" matchedEyes=UNVERIFIED";
        r.label=label.str();
        return r;
    }
    bool accepts_cached_dsv_metadata() const override { return true; }
    bool has_pending_retirement() override {
        std::scoped_lock lock{mutex};
        collect_retired();
        if (!retired.empty()) return true;
        for (const auto& slot : slots) if (!retire_ready(slot, fence.Get())) return true;
        return false;
    }
    void configure(ID3D12Device* dev, ID3D12CommandQueue* q, uint64_t w, uint32_t h, bool active) {
        std::scoped_lock lock{mutex};
        collect_retired();
        enabled = active && dev && q && q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (!enabled) return;
        if (device && (device.Get() != dev || queue.Get() != q)) {
            enabled = false; last = "device/queue changed without reset"; return;
        }
        if (!device) {
            device = dev; queue = q;
            if (FAILED(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) {
                enabled = false; last = "depth fence creation failed"; return;
            }
        }
        if (w && h && (w != width || h != height)) {
            ++epoch; ++pin_generation; width = w; height = h;
            recorded_this_interval=0;generic_captures_this_interval=0;
            normal_size_buckets={};diagnostic_catalog.clear();ngx_copied_this_interval={};
            manual_recovery={};mixed_switch_recovery={};
            observed_passes.clear();executed_proofs.clear();
            auto_candidate_identity={};auto_candidate_streak=0;auto_last_evaluated_epoch=0;
            last_fresh_pair={};
            for (auto& [cmd, state] : lists) { (void)cmd; state.proof_count = 0; }
        }
    }
    void on_depth_stencil_view_created(ID3D12Resource* resource,
        const D3D12_DEPTH_STENCIL_VIEW_DESC* dsv, D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override {
        if (!descriptor.ptr) return;
        std::scoped_lock lock{mutex};
        ++dsv_events;
        if (resource) {
            const auto key_id=reinterpret_cast<std::uintptr_t>(resource);
            if (!diagnostic_catalog.contains(key_id)) {
                if (diagnostic_catalog.size()<256) {
                    // Cache replay supplies a non-owning pointer identity.
                    // Its resource may already be destroyed: NEVER call COM here.
                    std::ostringstream label;
                    label << "DSV=0x" << std::hex << key_id << std::dec
                          << " viewFormat=" << unsigned(dsv ? dsv->Format : DXGI_FORMAT_UNKNOWN)
                          << " allocation=UNKNOWN_UNTIL_LIVE_BARRIER"
                          << " classification=METADATA_ONLY_NONOWNING";
                    diagnostic_catalog.emplace(key_id,label.str());
                } else ++diagnostic_catalog_overflow;
            }
        }
        const auto key = descriptor.ptr;
        const bool primary = resource && primary_slice(dsv);
        const auto existing = dsv_resources.find(key);
        if (existing != dsv_resources.end()) {
            existing->second = resource;
            dsv_primary_slice[key] = primary;
        } else {
            if (dsv_resources.size() >= DsvCapacity) {
                const auto evicted = dsv_order.front(); dsv_order.pop_front();
                dsv_resources.erase(evicted);
                dsv_primary_slice.erase(evicted);
                for (auto& [cmd, state] : lists) {
                    (void)cmd;
                    if (state.bound_dsv_handle == evicted) state.bound_dsv_resource = nullptr;
                    for (UINT i = 0; i < state.proof_count;) {
                        if (state.proofs[i].handle == evicted) {
                            std::move(state.proofs.begin() + i + 1, state.proofs.begin() + state.proof_count,
                                state.proofs.begin() + i);
                            --state.proof_count;
                        } else ++i;
                    }
                }
            }
            dsv_resources.emplace(key, resource);
            dsv_primary_slice.emplace(key, primary);
            dsv_order.push_back(key);
        }
        for (auto& [cmd, state] : lists) {
            (void)cmd;
            for (UINT i = 0; i < state.proof_count;) {
                if (state.proofs[i].handle == key) {
                    std::move(state.proofs.begin() + i + 1, state.proofs.begin() + state.proof_count,
                        state.proofs.begin() + i);
                    --state.proof_count;
                } else ++i;
            }
            if (state.bound_dsv_handle == key) {
                state.bound_dsv_resource = primary ? resource : nullptr;
                ++state.event;
                remember_main_bindings(state);
            }
        }
    }
    void on_resource_barriers(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) override {}
    void on_render_targets(ID3D12GraphicsCommandList* cmd, UINT, D3D12_CPU_DESCRIPTOR_HANDLE dsv) override {
        if (!cmd) return;
        std::scoped_lock lock{mutex};
        auto& state = list_state(cmd);
        ++bind_events; ++state.event;
        state.bound_dsv_handle = dsv.ptr;
        const auto found = dsv_resources.find(dsv.ptr);
        const auto primary = dsv_primary_slice.find(dsv.ptr);
        state.bound_dsv_resource = dsv.ptr && found != dsv_resources.end() &&
            primary != dsv_primary_slice.end() && primary->second ? found->second : nullptr;
        remember_main_bindings(state);
    }
    void on_viewports(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_VIEWPORT* viewports) override {
        if (!cmd) return;
        std::scoped_lock lock{mutex};
        auto& state = list_state(cmd);
        ++viewport_events; ++state.event;
        state.viewport_count = viewports && count <= ViewportCapacity ? count : 0;
        for (UINT i = 0; i < state.viewport_count; ++i) state.viewports[i] = viewports[i];
        remember_main_bindings(state);
    }
    void on_render_pass(ID3D12GraphicsCommandList* cmd, bool begin) override {
        std::scoped_lock lock{mutex};
        if (begin) { (void)list_state(cmd); render_passes.insert(object_identity(cmd).Get()); }
        else render_passes.erase(object_identity(cmd).Get());
    }
    void on_command_list_reset(ID3D12GraphicsCommandList* cmd) override {
        std::scoped_lock lock{mutex};
        for (const auto& s : slots) if (s.pending && s.list_identity.Get() == object_identity(cmd).Get()) ++reset_discards;
        render_passes.erase(object_identity(cmd).Get());
        lists.erase(object_identity(cmd).Get());
        reset_pending_list(slots, cmd);
        for (auto& generation : retired) reset_pending_list(generation.slots, cmd);
        collect_retired();
    }
    void on_post_resource_barriers(ID3D12GraphicsCommandList* cmd, UINT count,
        const D3D12_RESOURCE_BARRIER* barriers) override {
        if (!cmd || !barriers || cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return;
        std::scoped_lock lock{mutex};
        if (!enabled || !width || !height || !legacy_dsv_capture_enabled) return;
        if(render_passes.contains(object_identity(cmd).Get())) {
            ++render_pass_skipped_batches;
            return; // commands inside a render pass are not safely copyable here
        }
        const auto capture_event = ++list_state(cmd).event;
        for (UINT i = 0; i < count; ++i) {
            const auto& b = barriers[i];
            if (b.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                b.Flags != D3D12_RESOURCE_BARRIER_FLAG_NONE ||
                (b.Transition.StateBefore & (D3D12_RESOURCE_STATE_DEPTH_WRITE | D3D12_RESOURCE_STATE_DEPTH_READ)) == 0 ||
                (b.Transition.StateAfter & Read) == 0) continue;
            if(!capture_boundary_supported(duoview_source_sizes[0]!=0,
               (b.Transition.StateBefore&D3D12_RESOURCE_STATE_DEPTH_WRITE)!=0))continue;
            auto* source = b.Transition.pResource;
            if (!source) continue;
            ++read_windows;
            // The whole barrier batch has executed. A later transition or
            // aliasing operation can invalidate this entry's apparent state.
            bool superseded{};
            for (UINT j = i + 1; j < count; ++j) {
                const auto& later = barriers[j];
                if (later.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION && later.Transition.pResource == source) superseded = true;
                if (later.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING &&
                    (!later.Aliasing.pResourceBefore || !later.Aliasing.pResourceAfter ||
                     later.Aliasing.pResourceBefore == source || later.Aliasing.pResourceAfter == source)) superseded = true;
            }
            if (superseded) { ++reject_reasons[0]; continue; }
            const auto desc = source->GetDesc();
            D3D12_VIEWPORT source_viewport{};
            const auto format = storage(desc.Format);
            if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
                desc.SampleDesc.Count != 1 || desc.MipLevels != 1 || !desc.DepthOrArraySize ||
                (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) == 0 ||
                desc.Width > 32768 || desc.Height > 32768 || format == DXGI_FORMAT_UNKNOWN) {
                ++rejected; ++reject_reasons[1]; continue;
            }
            // Only the live ResourceBarrier callback supplies a resource
            // whose lifetime is guaranteed by the executing engine call.
            const auto live_key=reinterpret_cast<std::uintptr_t>(source);
            if(diagnostic_catalog.contains(live_key) || diagnostic_catalog.size()<256) {
                std::ostringstream label;
                label << "DSV=0x" << std::hex << live_key << std::dec
                      << " allocation=" << desc.Width << "x" << desc.Height
                      << " format=" << unsigned(desc.Format)
                      << " array=" << desc.DepthOrArraySize
                      << " MSAA=" << desc.SampleDesc.Count
                      << " classification=LIVE_BARRIER_OBSERVED_ONLY";
                diagnostic_catalog[live_key]=label.str();
            }
            observed = std::to_string(desc.Width) + "x" + std::to_string(desc.Height) + " fmt=" + std::to_string(desc.Format);
            if (!recorded_viewport(source, desc, source_viewport)) {
                ++rejected; ++reject_reasons[2]; continue;
            }
            const auto kind = classify_viewport(source_viewport);
            if (kind == Layout::Invalid) { ++rejected; ++reject_reasons[3]; continue; }
            // Count recognized barriers BEFORE size-class/capacity skips. A missing
            // earlier captured slot cannot renumber a later captured pass.
            // Repeated use of a DSV across multiple Unreal frames inside one
            // Present interval still cannot be separated without producer stamps.
            const auto observed_rank=observed_passes.observe(
                reinterpret_cast<std::uintptr_t>(source));
            ++observed_pass_events;
            if(!observed_rank) {++observed_pass_overflow;++rejected;continue;} // bounded, fail closed
            // Reserve part of the EXISTING 12-copy budget for explicit pins.
            // Rank was observed BEFORE admission so skipped writes keep order.
            const auto compatible_pin=[&](const ::duoview::depthpin::Pin& pin)->bool {
                if(!pin.enabled)return false;
                const auto& k=pin.key;
                const auto dim=[](float x)->uint32_t {
                    return std::isfinite(x)&&x>=0.f ? uint32_t(std::lround(x)):0u;
                };
                return k.generation==pin_generation &&
                    k.source==reinterpret_cast<std::uintptr_t>(source) &&
                    k.stage==observed_rank && k.texture_w==desc.Width &&
                    k.texture_h==desc.Height && k.format==uint32_t(format) &&
                    k.viewport_x==dim(source_viewport.TopLeftX) &&
                    k.viewport_y==dim(source_viewport.TopLeftY) &&
                    k.viewport_w==dim(source_viewport.Width) &&
                    k.viewport_h==dim(source_viewport.Height);
            };
            uint32_t manual_reservations=0;
            bool approved_pin=false;
            if(duoview_source_sizes[0] && !snapshot_armed) {
                for(const auto& pins:manual_pins) {
                    manual_reservations+=unsigned(pins.primary.enabled);
                    manual_reservations+=unsigned(pins.backup.enabled);
                    approved_pin|=compatible_pin(pins.primary) || compatible_pin(pins.backup);
                }
            }
            if(!::duoview::depthpin::CaptureBudget::admit(recorded_this_interval,
                    generic_captures_this_interval,manual_reservations,approved_pin,
                    snapshot_armed)) {
                if(manual_reservations && !approved_pin)++reserved_generic_skips;
                continue;
            }
            std::array<bool,2> ci31_shape_matches{};
            if(duoview_source_sizes[0] && !snapshot_armed) {
                for(size_t k=0;k<2;++k) {
                    ci31_shape_matches[k]=duoview_depth_shape(
                        source_viewport.Width,source_viewport.Height,
                        duoview_source_sizes[2*k],duoview_source_sizes[2*k+1]);
                    if(ci31_shape_matches[k])++ci31_viewport_shape_matches[k];
                }
                if(ci31_shape_matches[0] && ci31_shape_matches[1])
                    ++ci31_viewport_shape_ambiguous;
                if(!ci31_shape_matches[0] && !ci31_shape_matches[1]) {
                    ++ci31_viewport_shape_neither;
                    ++normal_extra_shape_skips;
                    continue; // never let an irrelevant viewport monopolize a stereo bucket
                }
            }
            size_t normal_bucket = 2;
            if (duoview_source_sizes[0] && !snapshot_armed && !approved_pin) {
                // Dimensions of a SINGLE candidate cannot prove L versus R:
                // at different DLSS scales both can match either source.
                // Reserve capacity for two distinct viewport size classes.
                for(size_t k=0;k<normal_size_buckets.size();++k) {
                    const auto& c=normal_size_buckets[k];
                    if(c.w>0 && std::abs(c.w-source_viewport.Width)/c.w<0.25 &&
                                  std::abs(c.h-source_viewport.Height)/c.h<0.25) {
                        normal_bucket=k;break;
                    }
                }
                if(normal_bucket==2) {
                    for(size_t k=0;k<normal_size_buckets.size();++k) {
                        if(normal_size_buckets[k].w==0) {
                            normal_bucket=k;
                            normal_size_buckets[k].w=source_viewport.Width;
                            normal_size_buckets[k].h=source_viewport.Height;
                            break;
                        }
                    }
                }
                if(normal_bucket==2) {
                    ++normal_extra_shape_skips;
                    for(size_t k=0;k<2;++k)if(ci31_shape_matches[k])
                        ++ci31_viewport_shape_budget_skipped[k];
                    continue;
                }
                if(normal_size_buckets[normal_bucket].captured>=NormalCapacity/2) {
                    ++normal_bucket_skips[normal_bucket];
                    for(size_t k=0;k<2;++k)if(ci31_shape_matches[k])
                        ++ci31_viewport_shape_budget_skipped[k];
                    continue;
                }
            }
            Ptr<IUnknown> source_device, command_device, expected_device;
            if (FAILED(source->GetDevice(IID_PPV_ARGS(&source_device))) ||
                FAILED(cmd->GetDevice(IID_PPV_ARGS(&command_device))) ||
                FAILED(device.As(&expected_device)) || source_device.Get() != expected_device.Get() ||
                command_device.Get() != expected_device.Get()) { ++rejected; ++reject_reasons[4]; continue; }
            // Source is the left camera: slice zero, plane zero only. Never
            // copy the right slice or a stencil-only transition.
            if (b.Transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES &&
                b.Transition.Subresource != 0) { ++reject_reasons[5]; continue; }
            auto it = std::find_if(slots.begin(), slots.end(), [&](const Slot& s) {
                return capture_slot_reusable(retire_ready(s, fence.Get()),
                    duoview_source_sizes[0]!=0, s.texture.Get()!=nullptr, s.epoch, epoch);
            });
            if (it == slots.end()) {
                ++exhausted;
                if(approved_pin)++pinned_pass_slot_exhaustion;
                continue;
            }
            auto& s = *it;
            s.foreign_fence.Reset();
            if(s.ngx)s.texture.Reset();
            if (!s.texture || s.texture->GetDesc().Width != desc.Width ||
                s.texture->GetDesc().Height != desc.Height || s.texture->GetDesc().Format != format) {
                auto dst = desc; dst.Format = format; dst.DepthOrArraySize = 1;
                dst.Alignment = 0; dst.Flags = D3D12_RESOURCE_FLAG_NONE;
                D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
                s.texture.Reset();
                if (FAILED(device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &dst,
                    Read, nullptr, IID_PPV_ARGS(&s.texture)))) {
                    last = "live depth allocation failed"; continue;
                }
                s.texture->SetName(L"Stock Joey DIBR live depth");
            }
            D3D12_RESOURCE_BARRIER copy[2]{};
            for (auto& c : copy) c.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            // Original write->read has already been recorded on the list.
            // Only plane zero changes state here, preserving stencil/other eye.
            copy[0].Transition = {source, 0, b.Transition.StateAfter, D3D12_RESOURCE_STATE_COPY_SOURCE};
            copy[1].Transition = {s.texture.Get(), 0, Read, D3D12_RESOURCE_STATE_COPY_DEST};
            cmd->ResourceBarrier(2, copy);
            D3D12_TEXTURE_COPY_LOCATION from{}, to{};
            from.pResource = source; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            to.pResource = s.texture.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
            std::swap(copy[0].Transition.StateBefore, copy[0].Transition.StateAfter);
            std::swap(copy[1].Transition.StateBefore, copy[1].Transition.StateAfter);
            cmd->ResourceBarrier(2, copy);
            s.source = source; s.list = cmd; s.list_identity = object_identity(cmd); s.epoch = epoch; s.serial = ++serial;
            s.pending = true; s.fence = 0; s.capture_event = capture_event;
            s.ngx=false;s.ngx_role=0;s.ngx_handle=0;s.ngx_guide={};s.ngx_snapshot_complete=false;
            s.ngx_color_source.Reset();s.ngx_motion_source.Reset();
            s.ngx_color.Reset();s.ngx_motion.Reset();
            s.observed_pass_rank = observed_rank;
            s.layout = kind; s.viewport = source_viewport;
            ++recorded_this_interval; ++captured;
            if(approved_pin)++pinned_pass_capture_count;
            else ++generic_captures_this_interval;
            if(normal_bucket<2){
                ++normal_size_buckets[normal_bucket].captured;
                ++normal_bucket_captures[normal_bucket];
                for(size_t k=0;k<2;++k)if(ci31_shape_matches[k])
                    ++ci31_viewport_shape_copied[k];
            }
            // Continue observing the current barrier batch's pass events even
            // when no additional copies are allowed; no extra GPU copies.
        }
    }
    void on_command_lists_executed(ID3D12CommandQueue* q, UINT count, ID3D12CommandList* const* submitted_lists) override {
        std::scoped_lock lock{mutex};
        if (!q || !submitted_lists) return;
        ++execute_events;
        const bool current_queue = fence && same_queue(q, queue.Get());
        if (current_queue) ++same_queue_events;
        const auto producer_identity = object_identity(q);
        Ptr<IUnknown> producer_device, expected_device;
        const bool valid_producer = device && (q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT ||
            q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_COMPUTE) &&
            SUCCEEDED(q->GetDevice(IID_PPV_ARGS(&producer_device))) &&
            SUCCEEDED(device.As(&expected_device)) && producer_device.Get() == expected_device.Get();
        const auto batch = ++execute_batch;
        if (valid_producer) {
            for (UINT i = 0; i < count; ++i) {
                if (submitted_lists[i] == nullptr || submitted_lists[i]->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT)
                    continue;
                const auto identity = object_identity(submitted_lists[i]);
                const auto found = lists.find(identity.Get());
                if (found == lists.end()) continue;
                for (UINT j = 0; j < found->second.proof_count; ++j) {
                    const auto& proof = found->second.proofs[j];
                    executed_proofs.push_back({proof.resource, proof.viewport, producer_identity, identity, epoch, batch, proof.event, i});
                    if (executed_proofs.size() > ExecutedProofCapacity) executed_proofs.pop_front();
                }
            }
        }
        bool found{};
        for (auto& s : slots) {
            if (!submitted_by(s, count, submitted_lists)) continue;
            ++matched_lists;
            if(s.epoch!=epoch)++late_submit_copy_events; // record/Present boundary, NOT UE frame proof
            UINT capture_index{};
            for (; capture_index < count; ++capture_index)
                if (submitted_lists[capture_index] == s.list.Get() ||
                    object_identity(submitted_lists[capture_index]).Get() == s.list_identity.Get()) break;
            const auto desc = s.source->GetDesc();
            // Recording-time metadata only establishes whether a copy is worth
            // recording. Its viewport may belong to an unsubmitted list. Use
            // the actual ordered producer proof for the published sample rect.
            const bool provenance_ok=enabled && valid_producer &&
                (s.ngx ? (s.ngx_guide.manual_source && s.list_identity.Get()!=nullptr) :
                q->GetDesc().Type==D3D12_COMMAND_LIST_TYPE_DIRECT &&
                select_executed_main_binding(s.source.Get(),desc,producer_identity.Get(),
                    s.list_identity.Get(),s.capture_event,batch,capture_index,s.viewport));
            if (provenance_ok) s.layout = s.ngx ? Layout::Eye : classify_viewport(s.viewport);
            if (current_queue) {
                if (!found) {
                    if (FAILED(q->Signal(fence.Get(), ++signal))) {
                        // Execute already happened. Reset of its recording list
                        // does not prove GPU retirement after a failed Signal.
                        for (auto& affected : slots) if (submitted_by(affected, count, submitted_lists)) {
                            affected.pending = false; affected.quarantined = true; affected.epoch = 0;
                        }
                        enabled = false; last = "depth submission signal failed; submitted slots quarantined";
                        submit_retired(q, count, submitted_lists);
                        return;
                    }
                    found = true;
                }
                s.pending = false; s.fence = signal;
            } else {
                // Alternate direct scene queues are supported only after a real
                // submission and producer-local DSV/viewport ordering proof.
                // Give this owned copy a producer fence; acquire adds a GPU
                // wait on the presentation queue before the synthesis dispatch.
                ++foreign_matches; s.fence = 0;
                if (SUCCEEDED(s.source->GetDevice(IID_PPV_ARGS(&producer_device))) &&
                    SUCCEEDED(q->GetDevice(IID_PPV_ARGS(&expected_device))) &&
                    producer_device.Get() == expected_device.Get() &&
                    SUCCEEDED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&s.foreign_fence))) &&
                    SUCCEEDED(q->Signal(s.foreign_fence.Get(), 1))) {
                    s.pending = false;
                } else {
                    s.pending = false; // Do not leave a quarantined pending slot permanently stuck.
                    s.epoch = 0; s.quarantined = true;
                    last = "alternate queue submission could not be fenced; slot quarantined";
                    continue;
                }
            }
            if (!provenance_ok) { s.epoch = 0; ++rejected; ++reject_reasons[6]; last = "capture rejected: no prior same-queue main DSV/viewport proof"; }
            else {
                ++submitted;
                const auto desc = s.source->GetDesc();
                const auto& vp = s.viewport;
                std::ostringstream proof;
                proof << "#" << s.serial << " epoch=" << s.epoch
                      << " source=0x" << std::hex
                      << reinterpret_cast<std::uintptr_t>(s.source.Get()) << std::dec
                      << " allocation=" << desc.Width << "x" << desc.Height
                      << " format=" << static_cast<unsigned>(desc.Format)
                      << " viewport=(" << vp.TopLeftX << "," << vp.TopLeftY
                      << "," << vp.Width << "," << vp.Height << ")"
                      << " eyeAttribution=UNKNOWN"
                      << " queue=" << (current_queue ? "present" : "fenced-foreign");
                recent_depth_proofs[recent_depth_proof_count % recent_depth_proofs.size()] = proof.str();
                ++recent_depth_proof_count;
            }
        }
        submit_retired(q, count, submitted_lists);
        collect_retired();
    }
    Ptr<ID3D12Resource> acquire() {
        std::scoped_lock lock{mutex};
        collect_retired();
        Slot* best{};
        std::array<ID3D12Resource*, Capacity> sources{};
        candidate_sources = 0;
        for (auto& s : slots) {
            if (s.pending || (!s.fence && !s.foreign_fence) || s.epoch != epoch || s.leased || s.quarantined) continue;
            if (std::find(sources.begin(), sources.begin() + candidate_sources, s.source.Get()) == sources.begin() + candidate_sources)
                sources[candidate_sources++] = s.source.Get();
            if (!best || double(s.viewport.Width) * s.viewport.Height > double(best->viewport.Width) * best->viewport.Height ||
                (s.viewport.Width == best->viewport.Width && s.serial > best->serial)) best = &s;
        }
        if (!best) { last = "no new submitted main-view depth in this Present interval"; return {}; }
        if (best->foreign_fence) {
            if (!queue || FAILED(queue->Wait(best->foreign_fence.Get(), 1))) {
                best->epoch = 0; last = "alternate queue consumer wait failed"; return {};
            }
            ++cross_queue_consumed;
        }
        best->leased = true; leased = static_cast<size_t>(best - slots.data()); ++consumed;
        const auto d = best->texture->GetDesc();
        last = "live main-view " + std::to_string(d.Width) + "x" + std::to_string(d.Height) +
            (best->layout == Layout::Packed ? " packed" : " eye") + " copy=" + std::to_string(best->serial);
        return best->texture;
    }
    std::array<float, 4> sample_uv() const {
        std::scoped_lock lock{mutex};
        if (leased >= Capacity) return {};
        const auto& s = slots[leased]; const auto d = s.texture->GetDesc();
        const auto left_width = s.viewport.Width / (s.layout == Layout::Packed ? 2.0f : 1.0f);
        return {left_width / float(d.Width), s.viewport.Height / float(d.Height),
            s.viewport.TopLeftX / float(d.Width), s.viewport.TopLeftY / float(d.Height)};
    }
    void finish_frame(bool keep_snapshot_armed=false) {
        std::scoped_lock lock{mutex};
        if (leased < Capacity) {
            auto& s = slots[leased];
            if (queue && fence && SUCCEEDED(queue->Signal(fence.Get(), ++signal))) s.fence = signal;
            else {
                enabled = false; s.pending = false; s.quarantined = true; s.epoch = 0;
                last = "depth consumer signal failed; leased slot quarantined";
            }
            s.leased = false; leased = Capacity;
        }
        // Captures were copied into the same present queue before this call.
        // Fence ALL manually leased candidates past the snapshot consumer,
        // not only the one best candidate used by stock DIBR.
        bool any_snapshot_lease=false;
        for (bool x:snapshot_leases) any_snapshot_lease|=x;
        if (any_snapshot_lease) {
            const bool signalled = queue && fence &&
                SUCCEEDED(queue->Signal(fence.Get(), ++signal));
            for(size_t i=0;i<snapshot_leases.size();++i) if(snapshot_leases[i]) {
                auto& s=slots[i];
                if(signalled){s.fence=signal;s.leased=false;}
                else {enabled=false;s.quarantined=true;s.epoch=0;s.leased=false;}
                snapshot_leases[i]=false;
            }
            if(!signalled)last="diagnostic producer retirement signal failure; slots quarantined";
        }
        snapshot_armed=keep_snapshot_armed;
        ++epoch; recorded_this_interval = 0; generic_captures_this_interval = 0; observed_passes.clear();
        normal_size_buckets={};ngx_copied_this_interval={};
        executed_proofs.clear();
        collect_retired();
    }
    std::string summary() const {
        std::scoped_lock lock{mutex};
        size_t quarantined_slots=0;
        for(const auto& s:slots)if(s.quarantined)++quarantined_slots;
        std::string proofs;
        const auto count = std::min<uint64_t>(recent_depth_proof_count, recent_depth_proofs.size());
        for (uint64_t index = 0; index < count; ++index) {
            const auto slot = (recent_depth_proof_count - count + index) % recent_depth_proofs.size();
            if (!proofs.empty()) proofs += " | ";
            proofs += recent_depth_proofs[slot];
        }
        if (proofs.empty()) proofs = "none submitted";
        return last + " | captured=" + std::to_string(captured) + " submitted=" +
            std::to_string(submitted) + " consumed=" + std::to_string(consumed) +
            " busy=" + std::to_string(exhausted) + " rejected=" + std::to_string(rejected) +
            " retired=" + std::to_string(retired.size()) +
            " hooks[dsv/bind/vp]=" + std::to_string(dsv_events) + "/" + std::to_string(bind_events) + "/" + std::to_string(viewport_events) +
            " exec[all/same/matched/alternate/resetDiscard]=" + std::to_string(execute_events) + "/" +
            std::to_string(same_queue_events) + "/" + std::to_string(matched_lists) + "/" +
            std::to_string(foreign_matches) + "/" + std::to_string(reset_discards) +
            " crossQueueUsed=" + std::to_string(cross_queue_consumed) +
            " candidateSources=" + std::to_string(candidate_sources) +
            " windows=" + std::to_string(read_windows) + " rejects[batch/shape/binding/layout/device/slice/order]=" +
            std::to_string(reject_reasons[0]) + "/" + std::to_string(reject_reasons[1]) + "/" + std::to_string(reject_reasons[2]) + "/" +
            std::to_string(reject_reasons[3]) + "/" + std::to_string(reject_reasons[4]) + "/" + std::to_string(reject_reasons[5]) + "/" + std::to_string(reject_reasons[6]) +
            " observed=" + observed +
            " proofHistory=[" + proofs + "]" +
            " CI30sizeClassesCaptured=" + std::to_string(normal_bucket_captures[0]) + "," + std::to_string(normal_bucket_captures[1]) +
            " classBudgetSkips=" + std::to_string(normal_bucket_skips[0]) + "," + std::to_string(normal_bucket_skips[1]) +
            " extraShapes=" + std::to_string(normal_extra_shape_skips) +
            " observedPassEvents=" + std::to_string(observed_pass_events) +
            " passSourceOverflow=" + std::to_string(observed_pass_overflow) +
            " pinnedPassCaptures=" + std::to_string(pinned_pass_capture_count) +
            " pinnedSlotExhaustion=" + std::to_string(pinned_pass_slot_exhaustion) +
            " reservedGenericSkips=" + std::to_string(reserved_generic_skips) +
            " renderPassSkippedBatches=" + std::to_string(render_pass_skipped_batches) +
            " lateSubmittedCopyEvents=" + std::to_string(late_submit_copy_events) +
            " quarantinedLiveSlots=" + std::to_string(quarantined_slots) +
            " pairDecisionTransitions=" + std::to_string(selection_transitions) +
            " pairSelectionFailures=" + std::to_string(selection_failures) +
            " pairRecoveryHolds=" + std::to_string(selection_holds) +
            " mixedSwitchHolds=" + std::to_string(mixed_switch_holds) +
            " mixedSwitchCommits=" + std::to_string(mixed_switch_commits) +
            " lastPairDecision=[" + selection_trace + "]" +
            " autoPairChanges=" + std::to_string(auto_candidate_changes) +
            " autoDeferred=" + std::to_string(auto_candidate_deferred) +
            " NGXSRcopies=" + std::to_string(ngx_copies) +
            " NGXSRrejects=" + std::to_string(ngx_rejects) +
            " NGXSRpairs=" + std::to_string(ngx_pairs) +
            " NGXSRfallbacks=" + std::to_string(ngx_one_sided) +
            " CI31normalViewportMatches=" + std::to_string(ci31_viewport_shape_matches[0]) + "," + std::to_string(ci31_viewport_shape_matches[1]) +
            " CI31normalCopies=" + std::to_string(ci31_viewport_shape_copied[0]) + "," + std::to_string(ci31_viewport_shape_copied[1]) +
            " CI31budgetSkipped=" + std::to_string(ci31_viewport_shape_budget_skipped[0]) + "," + std::to_string(ci31_viewport_shape_budget_skipped[1]) +
            " CI31ambiguousShapes=" + std::to_string(ci31_viewport_shape_ambiguous) +
            " CI31neitherShape=" + std::to_string(ci31_viewport_shape_neither) +
            " matchedEyes=UNVERIFIED";
    }
    void reset() {
        std::scoped_lock lock{mutex};
        enabled = false;
        if (device || queue || fence) {
            RetiredGeneration generation{};
            generation.device = std::move(device);
            generation.queue = std::move(queue);
            generation.fence = std::move(fence);
            generation.signal = signal;
            generation.slots = std::move(slots);
            // This signal is only a retirement marker for work already queued;
            // unsubmitted recordings remain pending until their list is Reset.
            const auto drain = generation.signal + 1;
            if (generation.queue && generation.fence && SUCCEEDED(generation.queue->Signal(generation.fence.Get(), drain))) {
                generation.signal = drain;
                for (auto& s : generation.slots) if (!s.pending) {
                    s.leased = false;
                    s.fence = drain;
                }
            }
            retired.push_back(std::move(generation));
        }
        slots = {};
        width = 0; height = 0; ++epoch; ++pin_generation; leased = Capacity; signal = 0;
        recorded_this_interval = 0; generic_captures_this_interval = 0;
        // Reset diagnostic and probation metadata with the source generation.
        // Preserve user pins but invalidate them via pin_generation, so reset
        // never silently returns a manually locked role to uncontrolled Auto.
        snapshot_leases={};snapshot_armed=false;manual_recovery={};mixed_switch_recovery={};
        auto_candidate_identity={};auto_candidate_streak=0;auto_last_evaluated_epoch=0;
        normal_size_buckets={};diagnostic_catalog.clear();ngx_copied_this_interval={};observed_passes.clear();
        selection_trace="reset; selection not evaluated";
        selection_identity=selection_trace;last_fresh_pair={};
        candidate_sources = 0;
        lists.clear(); render_passes.clear(); executed_proofs.clear(); execute_batch = 0;
        captured = submitted = consumed = exhausted = rejected = 0;
        collect_retired();
        last = "reset; waiting for scene depth";
    }
};
}
