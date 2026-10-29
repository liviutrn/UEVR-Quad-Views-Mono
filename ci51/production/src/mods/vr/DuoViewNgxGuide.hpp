#pragma once
// Independent NGX guide contract. Motion is current -> previous within one eye;
// it is never a stereo disparity. No NVIDIA or third-party implementation code.
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <span>
#include <unordered_map>

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
    bool flags_known{}, create_observed{}, motion_low_resolution{}, motion_extent_known{};
    bool operator==(const Guide&) const = default;
    explicit operator bool() const {
        return bool(producer) && feature_generation && evaluation && role>=1 && role<=2 &&
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
