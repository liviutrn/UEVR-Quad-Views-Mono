#pragma once
// Independent NGX guide contract. Motion is current -> previous within one eye;
// it is never a stereo disparity. No NVIDIA or third-party implementation code.
#include <array>
#include <cmath>
#include <chrono>
#include <mutex>
#include <cstdint>
#include <optional>
#include <span>
#include <unordered_map>
#include <vector>
#include <algorithm>
#include <utility>

namespace uevr::duoview::ngx {
struct ProducerTicket {
    uint64_t packet{}, generation{}, draw{};
    uint32_t render_frame{}, roles{};
    bool operator==(const ProducerTicket&) const = default;
    std::array<uint32_t,4> outputs{}; // LEFT fovea W/H, RIGHT full-field W/H
    explicit operator bool() const {
        return packet && generation && roles && outputs[0] && outputs[1] && outputs[2] && outputs[3];
    }
};
// An actual PreRenderViewFamily RHI boundary carries its immutable color packet
// onto the executing RHI thread. This is interval association, not a claim that
// a native NGX call exposes UE's per-pass camera or jittered view matrix.
inline thread_local ProducerTicket current_rhi_ticket{};
struct Guide {
    ProducerTicket producer{};
    uint64_t feature_generation{}, evaluation{};
    uintptr_t feature{}, output{};
    uint32_t role{}, feature_kind{}, flags{}, reset{};
    uint32_t input_width{}, input_height{}, output_width{}, output_height{};
    uint32_t depth_x{}, depth_y{}, color_x{}, color_y{}, motion_x{}, motion_y{}, output_x{}, output_y{};
    float jitter_x{}, jitter_y{}, motion_scale_x{1.f}, motion_scale_y{1.f};
    bool flags_known{}, create_observed{}, motion_low_resolution{}, motion_extent_known{},manual_source{};
    bool operator==(const Guide&) const = default;
    explicit operator bool() const {
        return (bool(producer) || manual_source) && feature_generation && evaluation && role>=1 && role<=2 &&
            input_width && input_height && output_width && output_height &&
            std::isfinite(jitter_x) && std::isfinite(jitter_y) &&
            std::abs(jitter_x)<=1.f && std::abs(jitter_y)<=1.f;
    }
    std::array<float,2> jitter_uv() const {
        return {jitter_x/float(input_width),jitter_y/float(input_height)};
    }
};
inline uint32_t role_for(const ProducerTicket& t,uint32_t width,uint32_t height) {
    if(!t)return 0;
    const bool left=width==t.outputs[0] && height==t.outputs[1];
    const bool right=width==t.outputs[2] && height==t.outputs[3];
    if(left==right)return 0;
    const uint32_t role=left?1u:2u;
    return (t.roles & (1u<<(role-1))) ? role : 0u;
}
// Build67: bounded, cross-thread handoff from a complete RHI source-pair.
// This is a short interval association, NOT proof of individual UE cameras.
struct ProducerBridgeCounters {
    uint64_t published{}, empty{}, resolved{}, stale{}, absent{}, shape_rejected{};
};
class ProducerBridge final {
    using Clock=std::chrono::steady_clock;
    mutable std::mutex mutex_;
    ProducerTicket current_{};
    Clock::time_point timestamp_{};
    ProducerBridgeCounters counters_{};
public:
    void publish(const ProducerTicket& ticket) {
        std::lock_guard guard(mutex_);
        // Reject out-of-range owners and equal-size ambiguous roles; single-role
        // RHI handoffs are valid. Two matching roles are required only at pairing.
        current_=ticket && (ticket.roles & ~3u)==0u &&
            (ticket.outputs[0]!=ticket.outputs[2] || ticket.outputs[1]!=ticket.outputs[3])
            ? ticket : ProducerTicket{};
        timestamp_=Clock::now();
        if(current_)++counters_.published;
        else ++counters_.empty;
    }
    ProducerTicket resolve(uint32_t output_width,uint32_t output_height,
                           std::chrono::milliseconds max_age=std::chrono::milliseconds{80}) {
        std::lock_guard guard(mutex_);
        if(!current_){++counters_.absent;return {};}
        if(Clock::now()-timestamp_>max_age){++counters_.stale;return {};}
        if(!role_for(current_,output_width,output_height)){
            ++counters_.shape_rejected;return {};
        }
        ++counters_.resolved;return current_;
    }
    ProducerBridgeCounters counters()const {
        std::lock_guard guard(mutex_);return counters_;
    }
    void reset(){publish({});}
};
inline ProducerBridge& producer_bridge() {
    static ProducerBridge bridge;
    return bridge;
}
// CI69: NGX evaluation identity catalog is independent of old RHI tickets.
// Never infer physical eyes from a handle. A user explicitly pins both roles.
struct ManualCandidate {
    uintptr_t feature{};
    uint64_t generation{}, last_evaluation{};
    uint32_t output_width{},output_height{},input_width{},input_height{},kind{};
    bool create_observed{}, flags_known{};
    uint64_t last_seen_ms{};
};
class ManualNgxRegistry final {
    mutable std::mutex mutex_;
    std::vector<ManualCandidate> candidates_;
    // Physical NGX feature handles can be re-used for different DLSS extents.
    // Pin a stable handle+extent signature, NOT the transient evaluation ordinal
    // or feature generation which changes when alternating output dimensions.
    using SourceKey=std::array<uintptr_t,3>; // handle, output width, output height
    std::array<SourceKey,2> pins_{};
    std::array<uint32_t,4> expected_outputs_{};
    static uint64_t now() {
        return uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }
    static SourceKey key(uintptr_t feature,uint32_t w,uint32_t h) {
        return {feature,uintptr_t(w),uintptr_t(h)};
    }
public:
    // A resize may preserve the user's explicitly selected feature identity,
    // but never transfer that selection to a different/new NGX feature.
    // Roles remain distinguishable by exact active output dimensions.
    void set_outputs(std::array<uint32_t,4> sizes) {
        std::lock_guard guard(mutex_);
        if(sizes==expected_outputs_)return;
        expected_outputs_=sizes;
        const bool distinct=sizes[0]&&sizes[1]&&sizes[2]&&sizes[3] &&
            (sizes[0]!=sizes[2] || sizes[1]!=sizes[3]);
        if(!distinct)return;
        for(unsigned eye=0;eye<2;++eye)if(pins_[eye][0])
            pins_[eye]=key(pins_[eye][0],sizes[eye*2],sizes[eye*2+1]);
    }
    void observe(const ManualCandidate& entry) {
        if(!entry.feature || !entry.output_width || !entry.output_height)return;
        std::lock_guard guard(mutex_);
        auto updated=entry;updated.last_seen_ms=now();
        auto found=std::find_if(candidates_.begin(),candidates_.end(),[&](const ManualCandidate& c){
            return c.feature==entry.feature && c.output_width==entry.output_width &&
                c.output_height==entry.output_height;
        });
        if(found!=candidates_.end())*found=updated;
        else {
            if(candidates_.size()>=24) {
                auto oldest=std::min_element(candidates_.begin(),candidates_.end(),
                    [](auto& a,auto& b){return a.last_seen_ms<b.last_seen_ms;});
                if(oldest!=candidates_.end())candidates_.erase(oldest);
            }
            candidates_.push_back(updated);
        }
    }
    uint64_t age_ms(const ManualCandidate& candidate) const {
        const auto t=now();return t>=candidate.last_seen_ms?t-candidate.last_seen_ms:0;
    }
    std::vector<ManualCandidate> browse() const {
        std::lock_guard guard(mutex_);
        auto result=candidates_;
        std::sort(result.begin(),result.end(),[](const auto&a,const auto&b){
            if(a.output_width!=b.output_width)return a.output_width>b.output_width;
            if(a.output_height!=b.output_height)return a.output_height>b.output_height;
            return a.feature<b.feature;
        });
        return result;
    }
    bool pin(unsigned eye,uintptr_t feature,uint32_t w,uint32_t h) {
        if(eye>=2 || !feature || !w || !h)return false;
        std::lock_guard guard(mutex_);
        const auto found=std::find_if(candidates_.begin(),candidates_.end(),[&](const auto& c){
            return c.feature==feature && c.output_width==w && c.output_height==h;
        });
        if(found==candidates_.end()||now()-found->last_seen_ms>3000)return false;
        if(expected_outputs_[eye*2] &&
           (w!=expected_outputs_[eye*2] || h!=expected_outputs_[eye*2+1]))return false;
        const auto selected=key(feature,w,h);
        if(pins_[1-eye]==selected)return false;
        pins_[eye]=selected;return true;
    }
    void clear(unsigned eye) {
        if(eye>=2)return;
        std::lock_guard guard(mutex_);pins_[eye]={};
    }
    std::array<SourceKey,2> pins()const {
        std::lock_guard guard(mutex_);return pins_;
    }
    unsigned role(uintptr_t feature,uint32_t w,uint32_t h)const {
        std::lock_guard guard(mutex_);
        const auto k=key(feature,w,h);
        for(unsigned i=0;i<2;++i)if(pins_[i]==k)return i+1;
        return 0;
    }
    void released(uintptr_t feature) {
        std::lock_guard guard(mutex_);
        for(auto& p:pins_)if(p[0]==feature)p={};
        candidates_.erase(std::remove_if(candidates_.begin(),candidates_.end(),
            [&](auto& c){return c.feature==feature;}),candidates_.end());
    }
};
inline ManualNgxRegistry& manual_registry() {
    static ManualNgxRegistry singleton;return singleton;
}
inline bool same_pair(const Guide& a,const Guide& b,uint64_t packet,uint64_t generation) {
    return a && b && a.role==1 && b.role==2 && packet && generation &&
        role_for(a.producer,a.output_width,a.output_height)==1 &&
        role_for(b.producer,b.output_width,b.output_height)==2 &&
        a.producer.packet==packet && b.producer.packet==packet &&
        a.producer.generation==generation && b.producer.generation==generation &&
        a.producer.draw==b.producer.draw && a.producer.render_frame==b.producer.render_frame;
}
enum class Plane : uint32_t {none,depth,color,motion};
struct SnapshotIdentity {Guide guide{};uint64_t serial{};Plane plane{};};
inline bool complete_snapshot(std::span<const SnapshotIdentity> images,uint64_t left_serial,
        uint64_t right_serial,uint64_t packet,uint64_t generation) {
    unsigned planes=0;
    std::array<Guide,2> guides{};
    for(const auto& image:images) {
        const auto& g=image.guide;
        if(!g || image.plane==Plane::none)continue;
        if(g.producer.packet!=packet || g.producer.generation!=generation ||
           role_for(g.producer,g.output_width,g.output_height)!=g.role)return false;
        const unsigned index=(g.role-1u)*3u+unsigned(image.plane)-1u;
        if(index>=6 || (planes&(1u<<index)))return false;
        const uint64_t selected=g.role==1?left_serial:right_serial;
        if(!selected || image.serial!=selected)return false;
        auto& first=guides[g.role-1u];
        if(first && first!=g)return false;
        first=g;planes|=1u<<index;
    }
    return planes==63u && same_pair(guides[0],guides[1],packet,generation);
}
struct Feature {
    uint64_t generation{};
    uint32_t kind{},flags{},width{},height{};
    bool flags_known{},create_observed{};
};
// Protected by the observer mutex. A released/reused pointer gets a new serial.
// Late injection is explicit: an SR-shaped evaluation may establish a local
// generation, but is never reported as an observed CreateFeature event.
class Features {
    std::unordered_map<uintptr_t,Feature> live_;
    uint64_t serial_{};
public:
    void created(uintptr_t handle,uint32_t kind,uint32_t flags,bool known,uint32_t w,uint32_t h) {
        if(handle)live_[handle]={++serial_,kind,flags,w,h,known,true};
    }
    void released(uintptr_t handle) {live_.erase(handle);}
    Feature observed(uintptr_t handle,uint32_t flags,bool known,uint32_t w,uint32_t h) {
        auto found=live_.find(handle);
        if(found==live_.end()) {
            // Bound unknown late-attach identities without retaining COM objects.
            if(live_.size()>=128)live_.clear();
            found=live_.emplace(handle,Feature{++serial_,0,flags,w,h,known,false}).first;
        }
        auto& f=found->second;
        if((f.width && f.width!=w)||(f.height && f.height!=h))f.generation=++serial_;
        f.width=w;f.height=h;
        if(known){f.flags=flags;f.flags_known=true;}
        return f;
    }
};
}
