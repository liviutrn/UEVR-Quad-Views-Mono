#include "TriViewGammaTables.hpp"
#include <cassert>
#include <thread>
#include <array>
int main() {
    uevr::quadview::PersistentGammaTables<4, 2> cache;
    const std::array<uintptr_t, 4> original{11, 22, 33, 44};
    const auto* a = cache.acquire(100, original, 1, 99);
    assert(a && (*a)[0] == 11 && (*a)[1] == 99 && (*a)[3] == 44);
    // Owner destruction/rebuild never changes the published table or destructor.
    assert(cache.acquire(100, original, 1, 99) == a);
    std::array<const std::array<uintptr_t, 4>*, 8> observed{};
    std::array<std::thread, 8> workers;
    for (size_t i = 0; i < workers.size(); ++i)
        workers[i] = std::thread([&, i] { observed[i] = cache.acquire(100, original, 1, 99); });
    for (auto& t : workers) t.join();
    for (auto* p : observed) assert(p == a);
    auto changed = original; changed[0] = 55;
    const auto* b = cache.acquire(100, changed, 1, 99);
    assert(b && b != a && (*b)[0] == 55 && (*a)[0] == 11);
    assert(!cache.acquire(200, original, 1, 99));
    assert(!cache.acquire(100, original, 4, 99));
    assert(cache.acquire(100, original, 1, 99) == a);
}
