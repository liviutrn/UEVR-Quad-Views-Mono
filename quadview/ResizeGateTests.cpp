// Tri-view B14: the resize gate builds ONE target set per settled size change.
// B12 requested a new four-target build on every 64 px step of a slider drag
// (scenario 1 would have counted one build per step), and could let a replaced
// build publish with sizes the draw no longer knew (scenario 2).
#include "QuadViewGeometry.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace uevr::quadview;
static void check_at(bool b, int line) { if (!b) throw std::runtime_error("resize gate assertion at line " + std::to_string(line)); }
#define check(b) check_at((b), __LINE__)

static SourceExtents ext(uint32_t periphery) {
    return {{{periphery, periphery}, {periphery, periphery}, {1280, 1024}, {1280, 1024}}};
}
static ResizeSizes sizes(float scale) { return {.5f, .5f, scale, 1.f}; }

int main() try {
    {   // 1. a slider drag of 12 steps, 50 ms apart: no build while moving, exactly one after it settles
        ResizeGate g; g.confirm_live(ext(640), sizes(.25f));
        uint64_t t = 1000; int requests = 0; SourceExtents last{};
        for (int step = 1; step <= 12; ++step, t += 50) {
            const auto d = g.update(ext(640), ext(640 + 64 * step), sizes(.25f + .02f * step), t);
            check(d.hold && d.draw.context_scale == .25f); // keep drawing the live sizes
            if (d.request) { ++requests; last = d.request_extents; }
        }
        check(requests == 0);
        for (int frame = 0; frame < 30; ++frame, t += 20) {
            const auto d = g.update(ext(640), ext(640 + 64 * 12), sizes(.49f), t);
            check(d.hold);
            if (d.request) { ++requests; last = d.request_extents; }
        }
        check(requests > 0 && last == ext(640 + 64 * 12));
        check(g.latched());
        // published: the gate learns the new sizes, stops holding and requesting
        const auto d = g.update(ext(640 + 64 * 12), ext(640 + 64 * 12), sizes(.49f), t + 20);
        check(!d.hold && !d.request && !g.latched());
    }
    {   // 2. the user moves on while a build is in flight: the in-flight extents stay requested
        ResizeGate g; g.confirm_live(ext(640), sizes(.25f));
        uint64_t t = 0;
        (void)g.update(ext(640), ext(768), sizes(.30f), t);
        auto d = g.update(ext(640), ext(768), sizes(.30f), t += 500);
        check(d.request && d.request_extents == ext(768));
        int repeats = 0;
        for (int i = 0; i < 40; ++i) {      // moved to 896, then back to 640, build still running
            d = g.update(ext(640), ext(i < 20 ? 896 : 640), sizes(i < 20 ? .35f : .25f), t += 50);
            check(!d.request || d.request_extents == ext(768)); // never anything but the in-flight build
            repeats += d.request;
        }
        check(repeats == 1); // re-requested once after 2 s (a fast-failing build is retried, not every frame)
        check(g.latched());
        // 768 publishes: the gate knows its sizes, holds them, and settles on 640 again
        d = g.update(ext(768), ext(640), sizes(.25f), t += 16);
        check(d.hold && d.draw.context_scale == .30f && !d.request);
        d = g.update(ext(768), ext(640), sizes(.25f), t += 500);
        check(d.hold && d.request && d.request_extents == ext(640));
    }
    {   // 3. sizes of the published set unknown (first draw, world change): never hold
        ResizeGate g;
        auto d = g.update(ext(640), ext(768), sizes(.30f), 0);
        check(!d.hold && !d.request);
        d = g.update(std::nullopt, ext(768), sizes(.30f), 1000);
        check(!d.hold && !d.request);
    }
    {   // 4. unchanged sizes: nothing to do
        ResizeGate g; g.confirm_live(ext(640), sizes(.25f));
        for (uint64_t t = 0; t < 2000; t += 16) {
            const auto d = g.update(ext(640), ext(640), sizes(.25f), t);
            check(!d.hold && !d.request);
        }
    }
    {   // 5. a build that never publishes releases the latch after the timeout
        ResizeGate g; g.confirm_live(ext(640), sizes(.25f));
        (void)g.update(ext(640), ext(768), sizes(.30f), 0);
        check(g.update(ext(640), ext(768), sizes(.30f), 500).request);
        check(g.latched());
        (void)g.update(ext(640), ext(768), sizes(.30f), 500 + ResizeGate::latch_timeout_ms + 1);
        check(g.latched()); // re-latched by the same, still settled wish
        // the published set disappears (world change): the old request is dropped
        check(!g.update(std::nullopt, ext(768), sizes(.30f), 600 + ResizeGate::latch_timeout_ms).request);
        check(!g.latched());
        g.reset();
        check(!g.latched() && !g.update(ext(640), ext(768), sizes(.30f), 0).hold);
    }
    {   // 6. B42 cooldown: after a publish the next build waits for the pause; reset keeps it
        ResizeGate g; g.set_cooldown_ms(1500); g.confirm_live(ext(640), sizes(.25f));
        uint64_t t = 10000;
        (void)g.update(ext(640), ext(768), sizes(.30f), t);
        check(g.update(ext(640), ext(768), sizes(.30f), t += 500).request);
        auto d = g.update(ext(768), ext(896), sizes(.35f), t += 16);   // 768 published, user wants 896
        check(d.hold && !d.request);
        d = g.update(ext(768), ext(896), sizes(.35f), t += 600);       // settled, but inside the pause
        check(d.hold && !d.request);
        d = g.update(ext(768), ext(896), sizes(.35f), t += 1000);      // pause over
        check(d.request && d.request_extents == ext(896));
        g.reset(); check(g.cooldown_ms() == 1500);
    }
    {   // 7. B42 cancel_latch: a refused build is dropped and a new wish settles normally
        ResizeGate g; g.confirm_live(ext(640), sizes(.25f));
        (void)g.update(ext(640), ext(1024), sizes(.40f), 0);
        check(g.update(ext(640), ext(1024), sizes(.40f), 500).request);
        g.cancel_latch(); check(!g.latched());
        auto d = g.update(ext(640), ext(768), sizes(.30f), 520);      // smaller wish, keeps drawing live
        check(d.hold && !d.request && d.draw.context_scale == .25f);
        d = g.update(ext(640), ext(768), sizes(.30f), 1000);
        check(d.request && d.request_extents == ext(768));
    }
    std::cout << "resize gate: ok\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << "\n";
    return 1;
}
