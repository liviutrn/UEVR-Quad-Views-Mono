#include "TriViewEpochGate.hpp"
#include <cassert>
#include <latch>
#include <thread>
int main() {
    uevr::triview::EpochGate gate;
    std::latch entered{1}, finish{1};
    std::thread callback([&] {
        auto original=gate.read(); assert(original);
        entered.count_down(); finish.wait();
        // A callback admitted before close must be able to finish nested XR
        // work. The writer still cannot mutate the world under this lease.
        auto nested=gate.read(); assert(nested);
    });
    entered.wait();
    assert(!gate.try_close());
    assert(!gate.read()); // New work cannot race the invalidation boundary.
    finish.count_down(); callback.join();
    assert(gate.try_close());
    assert(!gate.read());
    gate.open(); assert(gate.read());
    // Repeat the close/admit race; no writer may observe zero admitted readers
    // while one of them is inside a protected state mutation.
    for (int n=0;n<1000;++n) {
        std::atomic<int> active{};
        std::latch start{1};
        std::thread reader([&] {
            start.wait(); auto lease=gate.read();
            if (lease) { active.fetch_add(1); std::this_thread::yield(); active.fetch_sub(1); }
        });
        start.count_down();
        if (gate.try_close()) assert(active.load()==0);
        reader.join(); assert(gate.try_close()); gate.open();
    }
}
