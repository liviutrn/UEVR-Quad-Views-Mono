#include "CaptureSlotPolicy.hpp"
#include <cassert>
#include <iostream>

int main() {
    using stock_dibr::capture_slot_reusable;
    // Real failure schedule: foveal producer finishes before the next small
    // pass is recorded, but both precede the same Present consumer.
    assert(!capture_slot_reusable(true, true, true, 17, 17));
    assert(capture_slot_reusable(true, true, true, 17, 18));
    assert(capture_slot_reusable(true, true, false, 0, 17));
    assert(capture_slot_reusable(true, false, true, 17, 17));
    for (bool duoview : {false, true}) {
        for (bool occupied : {false, true}) {
            assert(!capture_slot_reusable(false, duoview, occupied, 17, 18));
        }
    }
    std::cout << "PASS: producer completion cannot erase an unread current DuoView capture; consumer retirement and stock reuse remain legal\n";
}
