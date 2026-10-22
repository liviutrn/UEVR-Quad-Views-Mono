#include "QuadViewDelivery.hpp"

#include <cassert>
#include <cstdint>

using uevr::quadview::Delivery;

namespace {

template <class Ledger>
typename Ledger::EngineTicket ticket(uint64_t generation, uint64_t serial,
                                     uint32_t frame, uintptr_t family,
                                     uintptr_t target = 0x200,
                                     uintptr_t scene = 0x300) {
    return {generation, serial, frame, family, target, scene};
}

template <class Ledger>
void assert_result(const typename Ledger::EngineRegistrationResult& result,
                   typename Ledger::EngineRegistrationStatus status,
                   size_t pending, size_t capacity, uint64_t oldest_serial) {
    assert(result.status == status);
    assert(result.pending == pending);
    assert(result.capacity == capacity);
    assert(result.oldest_serial == oldest_serial);
}

} // namespace

int main() {
    {
        using Ledger = Delivery<int, 3>;
        using Status = Ledger::EngineRegistrationStatus;
        Ledger ledger;

        assert_result<Ledger>(ledger.register_engine_family_detailed({}),
                              Status::invalid_ticket, 0, 3, 0);
        assert(!ledger.register_engine_family({}));

        const auto first = ticket<Ledger>(4, 11, 100, 0x101);
        assert_result<Ledger>(ledger.register_engine_family_detailed(first),
                              Status::accepted, 1, 3, 11);
        // The legacy bool API keeps its idempotent success for duplicates.
        assert(ledger.register_engine_family(first));
        assert_result<Ledger>(ledger.register_engine_family_detailed(first),
                              Status::duplicate_same_owner, 1, 3, 11);

        // A valid new generation resets the previous ledger before reporting
        // its post-registration occupancy.
        const auto next_generation = ticket<Ledger>(5, 27, 200, 0x102);
        assert_result<Ledger>(ledger.register_engine_family_detailed(next_generation),
                              Status::accepted, 1, 3, 27);

        const auto stale = ticket<Ledger>(4, 28, 201, 0x103);
        assert_result<Ledger>(ledger.register_engine_family_detailed(stale),
                              Status::stale_generation, 1, 3, 27);
        assert(!ledger.register_engine_family(stale));

        const Ledger::EngineTicket invalid_frame{5, 29, 0xffffffffu, 0x104, 0x200, 0x300};
        assert_result<Ledger>(ledger.register_engine_family_detailed(invalid_frame),
                              Status::invalid_ticket, 1, 3, 27);
        assert(ledger.pending_engine_commands(5) == 1);
    }

    {
        using Ledger = Delivery<int, 4>;
        using Status = Ledger::EngineRegistrationStatus;
        Ledger ledger;

        const auto owner = ticket<Ledger>(8, 40, 700, 0x401, 0x501, 0x601);
        assert_result<Ledger>(ledger.register_engine_family_detailed(owner),
                              Status::accepted, 1, 4, 40);

        // Family/serial differ, but the RT frame/target/scene key collides.
        const auto ambiguous = ticket<Ledger>(8, 41, 700, 0x402, 0x501, 0x601);
        assert_result<Ledger>(ledger.register_engine_family_detailed(ambiguous),
                              Status::ambiguous_rt_key, 1, 4, 40);
        assert(!ledger.register_engine_family(ambiguous));
        assert(ledger.engine_tracking_overflowed(8));
        assert(ledger.pending_engine_commands(8) == 1);
    }

    {
        using Ledger = Delivery<int, 2>;
        using Status = Ledger::EngineRegistrationStatus;
        Ledger ledger;

        const auto later = ticket<Ledger>(12, 92, 901, 0x701, 0x801, 0x901);
        const auto earlier = ticket<Ledger>(12, 73, 902, 0x702, 0x802, 0x902);
        assert(ledger.register_engine_family(later));
        assert_result<Ledger>(ledger.register_engine_family_detailed(earlier),
                              Status::accepted, 2, 2, 73);

        const auto overflow = ticket<Ledger>(12, 101, 903, 0x703, 0x803, 0x903);
        assert_result<Ledger>(ledger.register_engine_family_detailed(overflow),
                              Status::capacity_exhausted, 2, 2, 73);
        assert(!ledger.register_engine_family(overflow));
        assert(ledger.engine_tracking_overflowed(12));
        assert(ledger.pending_engine_commands(12) == 2);
    }
}
