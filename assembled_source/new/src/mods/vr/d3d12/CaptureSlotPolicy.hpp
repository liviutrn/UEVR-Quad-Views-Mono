#pragma once
#include <cstdint>

namespace stock_dibr {
// Producer completion makes a copy safe to READ. It does not mean the
// Present consumer has seen it. DuoView reserves every current-interval
// write version until finish_frame advances that interval, even without a
// preview/readback lease. Stock single-depth behavior remains unchanged.
constexpr bool capture_slot_reusable(bool gpu_retired, bool duoview,
        bool occupied, std::uint64_t slot_epoch, std::uint64_t consumer_epoch) {
    return gpu_retired && (!duoview || !occupied || slot_epoch != consumer_epoch);
}
}
