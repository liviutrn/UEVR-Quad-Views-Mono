#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <chrono>
#include <mutex>
#include <unordered_map>
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
    bool matches(const DepthOwner& other) const noexcept {
        return valid() && other.valid() && same_source(other) &&
            output_width==other.output_width && output_height==other.output_height &&
            projection==other.projection;
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
// Kept separate from the snapshot-data lock: no data lock crosses a driver
// call, but Reset cannot overtake Execute's post-call submission bookkeeping.
class DepthSubmissionSequence {
public:
    auto acquire() { return std::unique_lock<std::recursive_mutex>(mutex_); }
    auto try_acquire() { return std::unique_lock<std::recursive_mutex>(mutex_,std::try_to_lock); }
private:
    std::recursive_mutex mutex_;
};
// Access is serialized by PeripheryDepth's mutex. An object pointer identifies
// a command-list object; only pointer + epoch identifies its recorded commands.
// Publish both dimensions as one identity. Independent width/height atomics
// can expose a mixed layout while the game thread resizes the periphery.
class ExpectedPeripheryExtent {
public:
    void store(uint32_t width, uint32_t height) noexcept {
        packed_.store((uint64_t(width) << 32) | uint64_t(height), std::memory_order_release);
    }
    std::array<uint32_t,2> load() const noexcept {
        const auto dimensions = packed_.load(std::memory_order_acquire);
        return {uint32_t(dimensions >> 32), uint32_t(dimensions)};
    }
private:
    std::atomic<uint64_t> packed_{0};
};
class DepthRecordingEpochs {
public:
    uint64_t current(uintptr_t list) {
        const auto found=epochs_.find(list);
        if(found!=epochs_.end()) return found->second;
        if(!list || epochs_.size()>=256) return 0;
        return epochs_.emplace(list,++next_epoch_).first->second;
    }
    uint64_t reset(uintptr_t list) {
        const auto found=epochs_.find(list);
        return found==epochs_.end() ? 0 : (found->second=++next_epoch_);
    }
    template<class Keep> void prune(Keep keep) {
        for(auto it=epochs_.begin();it!=epochs_.end();) {
            if(!keep(it->first)) it=epochs_.erase(it); else ++it;
        }
    }
    bool matches(uintptr_t list,uint64_t epoch) const {
        const auto it=epochs_.find(list);
        return epoch && it!=epochs_.end() && it->second==epoch;
    }
private:
    std::unordered_map<uintptr_t,uint64_t> epochs_{};
    uint64_t next_epoch_{};
};
inline bool depth_capture_in_window(std::chrono::steady_clock::time_point captured,
        std::chrono::steady_clock::time_point packet_born,std::chrono::steady_clock::time_point now) {
    return packet_born.time_since_epoch().count()>0 && captured>=packet_born && captured<=now &&
        now-captured<std::chrono::milliseconds(250);
}
// UINT64_MAX is D3D12's device-removal sentinel, never completion proof.
inline bool depth_copy_complete(uint64_t completed,uint64_t required) noexcept {
    return required && completed!=~uint64_t{} && completed>=required;
}
inline bool depth_slot_reusable(bool pending,bool submitted,uint64_t completed,uint64_t required,
                                long references) noexcept {
    return references==1 && !pending && (!submitted || depth_copy_complete(completed,required));
}
}
