#pragma once
#include <atomic>
#include <cstdint>
#include <utility>

namespace uevr::triview {
// One GT writer; nonblocking close while existing XR callbacks drain. New
// callbacks cannot enter between the zero-reader check and world invalidation.
// Nested work on the same thread belongs to its already admitted transaction.
class EpochGate {
public:
    class Read {
    public:
        Read() = default;
        Read(const Read&) = delete;
        Read& operator=(const Read&) = delete;
        Read(Read&& other) noexcept : gate_{std::exchange(other.gate_,nullptr)},
            previous_{other.previous_}, outer_{other.outer_} {}
        ~Read() {
            if (gate_ && outer_) {
                active_=previous_;
                gate_->readers_.fetch_sub(1);
            }
        }
        explicit operator bool() const { return gate_!=nullptr; }
    private:
        friend class EpochGate;
        Read(const EpochGate* gate, const EpochGate* previous, bool outer)
            : gate_{gate}, previous_{previous}, outer_{outer} {}
        const EpochGate* gate_{};
        const EpochGate* previous_{};
        bool outer_{};
    };
    Read read() const {
        if (active_==this) return Read{this,this,false};
        if (closed_.load()) return {};
        readers_.fetch_add(1);
        if (closed_.load()) { readers_.fetch_sub(1); return {}; }
        const auto* previous=active_;
        active_=this;
        return Read{this,previous,true};
    }
    bool try_close() {
        closed_.store(true);
        return readers_.load()==0;
    }
    bool closed() const { return closed_.load(); }
    void open() { closed_.store(false); }
private:
    // Sequential consistency makes admission/close a single total order;
    // relaxed counts would permit both sides to miss the other's operation.
    mutable std::atomic<uint32_t> readers_{};
    std::atomic<bool> closed_{};
    inline static thread_local const EpochGate* active_{};
};
} // namespace uevr::triview
