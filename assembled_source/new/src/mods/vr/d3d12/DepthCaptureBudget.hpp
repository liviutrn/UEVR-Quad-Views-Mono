#pragma once
// CPU-only admission contract. User-approved manual depth sources receive
// reserved places in the SAME existing normal capture quota. No extra GPU
// copies, no stale slots, no producer eye/frame claims.
#include <algorithm>
#include <cstdint>
namespace duoview::depthpin {
struct CaptureBudget {
    static constexpr unsigned MaxNormal=12;
    static constexpr unsigned MaxManualReservations=4;
    static unsigned reserved(unsigned requested) {
        return (std::min)(requested, MaxManualReservations);
    }
    static bool admit(unsigned total, unsigned generic, unsigned reserved_count,
                      bool approved_pin, bool snapshot=false) {
        if (snapshot) return total<48;
        if(total>=MaxNormal)return false;
        if(approved_pin)return true;
        return generic < MaxNormal - reserved(reserved_count);
    }
};
}
