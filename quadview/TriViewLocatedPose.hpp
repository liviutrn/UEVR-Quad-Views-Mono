#pragma once
#include <cstdint>
#include <optional>
#include <utility>

namespace uevr::triview {
// Caller holds the runtime's pose mutex. Only a successful locate may publish.
// Invalidation preserves the sequence so old draw packets cannot match a new epoch.
template<class T> class LocatedPose {
public:
    void publish(const T& pose) {
        // Copy assignment reuses the two-view vector capacity in PipelineState.
        // Copy-constructing a temporary here would allocate on every locate.
        if (value_) *value_=pose;
        else value_.emplace(pose);
        value_->quadview_locate_serial=++serial_;
    }
    void invalidate() { value_.reset(); }
    const std::optional<T>& get() const { return value_; }
private:
    uint64_t serial_{};
    std::optional<T> value_{};
};
}
