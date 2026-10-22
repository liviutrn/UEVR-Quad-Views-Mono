#include "QuadViewDelivery.hpp"
#include "QuadViewRetirement.hpp"

#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <memory>

using namespace uevr::quadview;

struct NativeTarget {
    uintptr_t identity{};
};

struct TargetSetSnapshot {
    std::array<std::shared_ptr<const NativeTarget>, 4> targets{};
};

struct Packet {
    uint64_t serial{};
    std::shared_ptr<const TargetSetSnapshot> target_set_owner{};
};

using Ledger = Delivery<Packet, 8>;

struct GpuRetirement {
    bool quadview_compositor{true};
    bool copy_commands{true};
    bool presentation_resources{true};
};

bool can_reset_presentation(
    RetirementScope scope,
    const Ledger& ledger,
    const GpuRetirement& gpu,
    uint64_t generation) {
    if (requires_engine_retirement(scope) && !ledger.engine_commands_retired(generation)) {
        return false;
    }
    return gpu.quadview_compositor && gpu.copy_commands && gpu.presentation_resources;
}

Ledger::EngineTicket make_ticket(uint64_t serial) {
    return Ledger::EngineTicket{
        1,
        serial,
        static_cast<uint32_t>(5000 + serial),
        0x10000 + serial,
        0x20000 + serial,
        0x30000 + serial,
    };
}

int main() {
    static_assert(!requires_engine_retirement(RetirementScope::presentation));
    static_assert(requires_engine_retirement(RetirementScope::mode_transition));
    static_assert(requires_engine_retirement(static_cast<RetirementScope>(0xff)));

    {
        Ledger ledger;
        GpuRetirement gpu{};

        // The producer keeps adding engine owners while setup polls. The old
        // mode-transition gate stays closed, but presentation reset can pass
        // whenever its independent GPU users have retired.
        std::array<Ledger::EngineTicket, 3> owners{};
        for (std::size_t index = 0; index < owners.size(); ++index) {
            owners[index] = make_ticket(index + 1);
            assert(ledger.register_engine_family(owners[index]));
            assert(ledger.pending_engine_commands(1) == index + 1);
            assert(!ledger.engine_commands_retired(1));
            assert(can_reset_presentation(RetirementScope::presentation, ledger, gpu, 1));
            assert(!can_reset_presentation(RetirementScope::mode_transition, ledger, gpu, 1));
        }

        // Each GPU fence class independently remains mandatory for setup.
        gpu.quadview_compositor = false;
        assert(!can_reset_presentation(RetirementScope::presentation, ledger, gpu, 1));
        gpu.quadview_compositor = true;
        gpu.copy_commands = false;
        assert(!can_reset_presentation(RetirementScope::presentation, ledger, gpu, 1));
        gpu.copy_commands = true;
        gpu.presentation_resources = false;
        assert(!can_reset_presentation(RetirementScope::presentation, ledger, gpu, 1));
        gpu.presentation_resources = true;
        assert(can_reset_presentation(RetirementScope::presentation, ledger, gpu, 1));

        // The mode-transition scope opens only after every actual engine
        // render-thread/RHI owner has run its tail.
        for (const auto& owner : owners) {
            const auto rendered = ledger.render_engine_family(
                owner.generation, owner.engine_frame, owner.target, owner.scene);
            assert(rendered && rendered->same_owner(owner));
            const uintptr_t command = 0x40000 + owner.serial;
            assert(ledger.tail_hooked_engine_family(*rendered, command));
            assert(ledger.executed_engine_family(*rendered, command));
        }
        assert(ledger.engine_commands_retired(1));
        assert(can_reset_presentation(RetirementScope::mode_transition, ledger, gpu, 1));
    }

    {
        Ledger ledger;
        auto manager_snapshot = std::make_shared<TargetSetSnapshot>();
        for (std::size_t index = 0; index < manager_snapshot->targets.size(); ++index) {
            manager_snapshot->targets[index] = std::make_shared<NativeTarget>(NativeTarget{0x50000 + index});
        }
        std::weak_ptr<const TargetSetSnapshot> weak_snapshot = manager_snapshot;
        std::weak_ptr<const NativeTarget> weak_target = manager_snapshot->targets[3];

        auto packet = std::make_shared<const Packet>(Packet{1, manager_snapshot});
        Ledger::Source source{
            std::move(packet), 1, 1, 6000, 7000, 0x11000, 0x21000, 0x31000,
            {0x41000, 0x41008, 0x41010, 0x41018},
        };
        assert(ledger.register_bound(std::move(source)));
        assert(!ledger.engine_commands_retired(1));

        auto rendered = ledger.render(1, 6000, 0x11000, 0x21000, 0x31000);
        assert(rendered);
        assert(ledger.tail_hooked(*rendered, 0x61000));
        assert(ledger.executed(*rendered, 0x61000, 42));
        assert(ledger.engine_commands_retired(1));
        rendered.reset();

        // Dropping the manager's current target-set snapshot must not release
        // native targets still retained by the packet in the delivery ledger.
        manager_snapshot.reset();
        assert(!weak_snapshot.expired());
        assert(!weak_target.expired());
        ledger.retire_generation(1);
        assert(weak_snapshot.expired());
        assert(weak_target.expired());
    }
}
