// B41: behavioural tests for the TriView hold window (TriViewHold.hpp).
#include "TriViewHold.hpp"

#include <cstdio>
#include <cstdlib>

using uevr::quadview::TriViewHold;

static int failures = 0;
static void check(bool ok, const char* what) {
    if (!ok) { std::printf("TriViewHold FAILED: %s\n", what); ++failures; }
}

int main() {
    constexpr uint64_t gen = 7, swap = 0x1000, t0 = 50'000;

    // Default window and clamping.
    check(TriViewHold::window_ms() == TriViewHold::default_window_ms, "default window is 250 ms");
    TriViewHold::set_window_ms(5);
    check(TriViewHold::window_ms() == 100, "window clamps up to 100 ms");
    TriViewHold::set_window_ms(5000);
    check(TriViewHold::window_ms() == 1000, "window clamps down to 1000 ms");
    TriViewHold::set_window_ms(250);

    TriViewHold hold;
    // Nothing to hold before the first real submit.
    check(!hold.ready() && !hold.can_hold(gen, swap, t0), "no hold before first submit");
    check(hold.age_ms(t0) == 0, "age 0 before first submit");

    // Missed frames inside the window are held; the timeout is inclusive.
    hold.submitted(gen, swap, t0);
    check(hold.can_hold(gen, swap, t0 + 16), "hold after one missed frame");
    check(hold.can_hold(gen, swap, t0 + 250), "hold exactly at the window edge");
    check(!hold.can_hold(gen, swap, t0 + 251), "no hold after the window (250 ms)");
    check(hold.age_ms(t0 + 251) == 251, "age reports time since last real submit");

    // Holding does not refresh the window: only a real submit does.
    for (uint64_t t = t0 + 16; t <= t0 + 240; t += 16) check(hold.can_hold(gen, swap, t), "consecutive held frames");
    check(!hold.can_hold(gen, swap, t0 + 260), "held frames do not extend the window");

    // A longer user window covers a longer gap.
    TriViewHold::set_window_ms(1000);
    check(hold.can_hold(gen, swap, t0 + 900), "1000 ms window covers a 900 ms gap");
    check(!hold.can_hold(gen, swap, t0 + 1001), "1000 ms window ends");
    TriViewHold::set_window_ms(250);

    // Mode/generation change and swapchain replacement never hold the old image.
    check(!hold.can_hold(gen + 1, swap, t0 + 16), "no hold across a generation change");
    check(!hold.can_hold(gen, swap + 1, t0 + 16), "no hold across a swapchain change");
    check(!hold.can_hold(gen, 0, t0 + 16), "no hold with a null swapchain");

    // Clock going backwards is treated as unsafe.
    check(!hold.can_hold(gen, swap, t0 - 1), "no hold if time goes backwards");

    // Recovery: a new valid frame re-arms the window from its own time.
    hold.submitted(gen, swap, t0 + 2000);
    check(hold.can_hold(gen, swap, t0 + 2100), "re-armed after a valid frame");
    check(!hold.can_hold(gen, swap, t0 + 2251), "re-armed window still times out");

    // A new generation/swapchain is accepted after its own submit.
    hold.submitted(gen + 1, swap + 1, t0 + 3000);
    check(hold.can_hold(gen + 1, swap + 1, t0 + 3016), "hold for the new generation/swapchain");
    check(!hold.can_hold(gen, swap, t0 + 3016), "old generation/swapchain no longer held");

    // reset() (world change, failed submit, mode change) disables holding.
    hold.reset();
    check(!hold.ready() && !hold.can_hold(gen + 1, swap + 1, t0 + 3016), "no hold after reset");

    if (failures) return EXIT_FAILURE;
    std::printf("TriViewHold: window clamp, timeout, no refresh while holding, generation/swapchain/reset guards, recovery OK\n");
    return EXIT_SUCCESS;
}
