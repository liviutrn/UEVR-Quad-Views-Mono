#pragma once
// An immutable DuoView packet is carried onto the executing UE RHI command.
// Do not substitute VR::duoview_producer_key() here: that value may belong to
// a newer game/render thread frame when NGX Evaluate runs on the RHI thread.
#include "DuoViewFrame.hpp"

namespace uevr::duoview::ngx {
inline thread_local FrameKey current_rhi_producer_key{};

class ScopedRhiProducerKey final {
    FrameKey previous_;
public:
    explicit ScopedRhiProducerKey(FrameKey key) noexcept
        : previous_(current_rhi_producer_key) {
        current_rhi_producer_key=key;
    }
    ~ScopedRhiProducerKey() noexcept {current_rhi_producer_key=previous_;}
    ScopedRhiProducerKey(const ScopedRhiProducerKey&)=delete;
    ScopedRhiProducerKey& operator=(const ScopedRhiProducerKey&)=delete;
};
}
