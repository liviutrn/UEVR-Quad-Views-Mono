#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::quadview {

// Canonical identities never move: LC=0, RC=1, LF=2, RF=3. Only the
// invocation order of already-constructed native singleton renders changes.
using RenderOrder = std::array<size_t,4>;
inline constexpr RenderOrder canonical_render_order{0,1,2,3};

constexpr bool valid_render_order(const RenderOrder& order) {
    unsigned mask{};
    for (auto role : order) {
        if (role>=4 || (mask & (1u<<role))) return false;
        mask|=1u<<role;
    }
    return mask==15;
}

constexpr RenderOrder render_order(uint32_t mode,uint64_t sequence) {
    // 0 baseline; 1 fixed LF first; 2 fixed RF first; 3 alternate LF/RF first.
    if (mode==1 || (mode==3 && !(sequence&1))) return {2,3,0,1};
    if (mode==2 || mode==3) return {3,2,0,1};
    return canonical_render_order;
}

struct RenderOrderPlan {
    uint64_t generation{},serial{},sequence{};
    uint32_t mode{};
    RenderOrder order{canonical_render_order};
    explicit operator bool() const {
        return generation && serial && mode<=3 && valid_render_order(order);
    }
    friend bool operator==(const RenderOrderPlan&,const RenderOrderPlan&)=default;
};

// GT dispatch sequencing only: completion is NOT an RHI/GPU retirement proof.
// Failed/incomplete quartets do not advance the alternating phase; a source
// retry freezes its plan. UI changes apply only to the next source draw.
class RenderOrderSequence {
public:
    RenderOrderPlan prepare(uint64_t generation,uint64_t serial,uint32_t mode) {
        std::scoped_lock lock{mutex_};
        if (!generation || !serial || mode>3 || generation<generation_) return {};
        if (generation!=generation_) {
            generation_=generation; sequence_=0; current_.reset(); completed_=false;
        }
        if (current_) {
            if (serial<current_->serial) return {};
            if (serial==current_->serial) return completed_ ? RenderOrderPlan{} : *current_;
        }
        current_=RenderOrderPlan{generation,serial,sequence_,mode,render_order(mode,sequence_)};
        completed_=false;
        return *current_;
    }
    bool complete(const RenderOrderPlan& plan) {
        std::scoped_lock lock{mutex_};
        if (!current_ || completed_ || !plan || plan!=*current_) return false;
        completed_=true;
        ++sequence_;
        return true;
    }
private:
    std::mutex mutex_;
    uint64_t generation_{},sequence_{};
    std::optional<RenderOrderPlan> current_;
    bool completed_{};
};
}
