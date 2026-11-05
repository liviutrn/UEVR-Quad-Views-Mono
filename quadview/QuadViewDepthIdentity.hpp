#pragma once
#include <array>
#include <cstdint>
namespace uevr::quadview::ngx {
// A producer identity, never a lookup by dimensions or current global GT key.
// The adapter may publish it only while executing one authenticated role-0 tail.
struct DepthOwner {
    uint64_t generation{}, serial{}, target_set{};
    uint32_t engine_frame{}, role{~0u}, output_width{}, output_height{};
    std::array<double,16> projection{};
    std::array<float,2> jitter{};
    bool unambiguous{}, ngx_input_state_known{};
    bool valid() const noexcept {
        return generation && serial && target_set && role==0 && output_width && output_height &&
            unambiguous;
    }
    bool same_source(const DepthOwner& other) const noexcept {
        return generation==other.generation && serial==other.serial && target_set==other.target_set &&
            engine_frame==other.engine_frame && role==other.role;
    }
    friend bool operator==(const DepthOwner&,const DepthOwner&)=default;
};
class DepthOwnerScope {
public:
    explicit DepthOwnerScope(const DepthOwner& owner) noexcept : previous_(current_) {
        current_=owner.valid() ? &owner : nullptr;
    }
    ~DepthOwnerScope() { current_=previous_; }
    DepthOwnerScope(const DepthOwnerScope&)=delete;
    static const DepthOwner* current() noexcept { return current_; }
private:
    const DepthOwner* previous_{};
    static inline thread_local const DepthOwner* current_{};
};
// UINT64_MAX is D3D12's device-removal sentinel, never completion proof.
inline bool depth_copy_complete(uint64_t completed,uint64_t required) noexcept {
    return required && completed!=~uint64_t{} && completed>=required;
}
inline bool depth_slot_reusable(bool pending,bool submitted,uint64_t completed,uint64_t required,
                                long references) noexcept {
    return references==1 && !pending && (!submitted || depth_copy_complete(completed,required));
}
}
