#pragma once
#include <cstdint>
namespace uevr::quadview {
// Native source creation needs renderer/RHI progress. A warm-up family is
// engine-only: render its context once, never the otherwise unused role 1.
// Restore on every exit so Unreal's view/history bookkeeping stays unchanged.
class BootstrapViewCount {
public:
    explicit BootstrapViewCount(int32_t& count) noexcept : count_(count), saved_(count) {
        if (count_ == 4) count_ = 1;
    }
    ~BootstrapViewCount() { count_ = saved_; }
    BootstrapViewCount(const BootstrapViewCount&) = delete;
private:
    int32_t& count_;
    int32_t saved_;
};
constexpr bool native_triview_publishable(bool shared, bool native_local,
                                         uint64_t target_set_generation) noexcept {
    return shared && native_local && target_set_generation != 0;
}
}
