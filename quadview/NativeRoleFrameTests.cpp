#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <memory>

using namespace uevr::quadview;

namespace {

struct Packet { uint64_t serial{}; };
using D = Delivery<Packet, 16>;
using N = NativeDelivery<D>;

constexpr std::uintptr_t source_target = 0x200;
constexpr std::uintptr_t scene_id = 0x300;
constexpr std::array<std::uintptr_t, 4> targets{0x501, 0x502, 0x503, 0x504};

struct Owner {
    D::Source source{};
    D::EngineTicket engine{};
};

Owner bind_owner(D& delivery, N& native, uint64_t generation, uint64_t serial,
                 uint32_t engine_frame, std::uintptr_t family,
                 uint64_t target_set, std::array<std::uintptr_t, 4> role_targets = targets,
                 std::uintptr_t scene = scene_id,
                 std::uintptr_t producer_target = source_target) {
    D::Source source{std::make_shared<const Packet>(Packet{serial}), generation, serial,
        engine_frame, serial, family, producer_target, scene,
        {family + 0x401, family + 0x402, family + 0x403, family + 0x404}};
    D::EngineTicket engine{generation, serial, engine_frame, family, producer_target, scene};
    assert(delivery.register_engine_family(engine));
    assert(delivery.register_bound(source));
    assert(native.bind(source, engine, target_set, role_targets, true));
    return {source, engine};
}

std::array<uint32_t, 4> frames_from(uint32_t base) {
    return {base, base + 1, base + 2, base + 3};
}

void test_all_role_orderings() {
    std::array<size_t, 4> order{0, 1, 2, 3};
    do {
        D delivery;
        N native{delivery};
        constexpr uint64_t generation = 17;
        constexpr uint64_t serial = 81;
        constexpr uint32_t engine_frame = 1200;
        const auto role_frames = frames_from(engine_frame);
        const auto owner = bind_owner(delivery, native, generation, serial,
                                      engine_frame, 0x100, 0x44);
        std::array<N::Command, 4> commands{};
        std::array<N::TailTicket, 4> tails{};

        // Each GT role registration arrives immediately before its matching
        // RT callback. The source ledger still claims the canonical frame.
        for (size_t view : order) {
            assert(!native.render(generation, role_frames[view], targets[view], scene_id));
            assert(native.bind_role(generation, serial, view, role_frames[view],
                                   targets[view], scene_id));
            const auto command = native.render(generation, role_frames[view],
                                               targets[view], scene_id);
            assert(command && command->view == view);
            assert(command->source.serial == serial);
            assert(command->source.engine_frame == engine_frame);
            commands[view] = *command;

            const auto attached = native.hook_batch(*command, 0x10000 + view,
                                                    0, 0, role_frames[view]);
            assert(attached.status == N::AttachStatus::attached);
            tails[view] = attached.tail;
            assert(!delivery.select(generation, 77));
        }

        for (size_t view = 0; view < 3; ++view)
            assert(!native.runtime_event(tails[view]));
        const auto role3_event = native.runtime_event(tails[3]);
        assert(role3_event && role3_event.generation == generation &&
               role3_event.serial == serial && role3_event.frame == role_frames[3]);
        N::RuntimeEvent claimed{};
        assert(native.claim_runtime_event(tails[3], claimed));
        assert(claimed.generation == generation && claimed.serial == serial &&
               claimed.frame == role_frames[3]);
        assert(!native.claim_runtime_event(tails[3], claimed));

        size_t executed_count{};
        for (auto it = order.rbegin(); it != order.rend(); ++it) {
            const auto result = native.executed_tail(tails[*it], 77);
            assert(result.accepted);
            ++executed_count;
            const auto selected = delivery.select(generation, 77);
            assert(bool(selected) == (executed_count == 4));
        }
        assert(delivery.engine_commands_retired(generation));
        assert(delivery.pending_engine_commands(generation) == 0);
        assert(native.diagnostics_snapshot(generation).occupied_slots == 0);

        const auto selected = delivery.select(generation, 77);
        assert(selected && selected->generation == generation && selected->serial == serial &&
               selected->engine_frame == engine_frame);
        assert(delivery.submitted(*selected, 0xD00));
        assert(!delivery.select(generation, 77));
    } while (std::next_permutation(order.begin(), order.end()));
}

void test_missing_and_mismatched_role_frames() {
    D delivery;
    N native{delivery};
    constexpr uint64_t generation = 21;
    constexpr uint64_t serial = 91;
    constexpr uint32_t engine_frame = 1700;
    const auto role_frames = frames_from(1800);
    bind_owner(delivery, native, generation, serial, engine_frame, 0x110, 0x45);

    assert(!native.bind_role(generation + 1, serial, 0, role_frames[0], targets[0], scene_id));
    assert(!native.bind_role(generation, serial + 1, 0, role_frames[0], targets[0], scene_id));
    assert(!native.bind_role(generation, serial, 4, role_frames[0], targets[0], scene_id));
    assert(!native.bind_role(generation, serial, 0, UINT32_MAX, targets[0], scene_id));
    assert(!native.bind_role(generation, serial, 0, role_frames[0], targets[0] + 0x10, scene_id));
    assert(!native.bind_role(generation, serial, 0, role_frames[0], targets[0], scene_id + 1));
    assert(!native.render(generation, role_frames[0], targets[0], scene_id));

    for (size_t view = 0; view < 3; ++view)
        assert(native.bind_role(generation, serial, view, role_frames[view], targets[view], scene_id));
    assert(!native.render(generation, role_frames[3], targets[3], scene_id)); // Role 3 is unbound.
    assert(!native.render(generation, role_frames[0], targets[0], scene_id + 1));
    assert(!native.render(generation + 1, role_frames[0], targets[0], scene_id));
    assert(!native.render(generation, role_frames[0] + 1, targets[0], scene_id));
    assert(!native.render(generation, role_frames[0], targets[0] + 0x10, scene_id));

    const auto command = native.render(generation, role_frames[0], targets[0], scene_id);
    assert(command && command->view == 0);
    assert(!native.render(generation, role_frames[0], targets[0], scene_id)); // Duplicate RT callback.
    assert(native.bind_role(generation, serial, 0, role_frames[0], targets[0], scene_id)); // Idempotent GT callback.
}

void test_conflicting_rebind_poisoning() {
    D delivery;
    N native{delivery};
    constexpr uint64_t generation = 25;
    constexpr uint64_t serial = 98;
    constexpr uint32_t engine_frame = 2100;
    const auto role_frames = frames_from(2200);
    bind_owner(delivery, native, generation, serial, engine_frame, 0x120, 0x46);

    assert(native.bind_role(generation, serial, 0, role_frames[0], targets[0], scene_id));
    assert(native.bind_role(generation, serial, 0, role_frames[0], targets[0], scene_id));
    assert(!native.bind_role(generation, serial, 0, role_frames[0] + 50, targets[0], scene_id));
    for (size_t view = 1; view < 4; ++view)
        assert(native.bind_role(generation, serial, view, role_frames[view], targets[view], scene_id));

    std::array<N::TailTicket, 4> tails{};
    for (size_t view = 0; view < 4; ++view) {
        const auto command = native.render(generation, role_frames[view], targets[view], scene_id);
        assert(command && command->view == view);
        const auto attached = native.hook_batch(*command, 0x20000 + view, 0, 0, role_frames[view]);
        assert(attached.status == N::AttachStatus::attached);
        tails[view] = attached.tail;
    }
    for (const auto& tail : tails) assert(native.executed_tail(tail, 77).accepted);
    assert(delivery.engine_commands_retired(generation));
    assert(!delivery.select(generation, 77)); // Conflicting GT frame poisoned publication.
}

void test_reused_targets_require_unique_role_frame() {
    {
        D delivery;
        N native{delivery};
        constexpr uint64_t generation = 31;
        const auto first = bind_owner(delivery, native, generation, 110, 3000, 0x130, 0x51);
        const auto second = bind_owner(delivery, native, generation, 111, 3001, 0x140, 0x52);
        assert(first.engine.engine_frame != second.engine.engine_frame);
        assert(native.bind_role(generation, first.source.serial, 0, 3200, targets[0], scene_id));
        assert(native.bind_role(generation, second.source.serial, 0, 3200, targets[0], scene_id));
        assert(!native.render(generation, 3200, targets[0], scene_id)); // Two exact RT owners.
    }

    {
        D delivery;
        N native{delivery};
        constexpr uint64_t generation = 32;
        const auto first = bind_owner(delivery, native, generation, 120, 3100, 0x150, 0x53);
        const auto second = bind_owner(delivery, native, generation, 121, 3101, 0x160, 0x54);
        const auto first_frames = frames_from(3300);
        const auto second_frames = frames_from(3400);
        for (size_t view = 0; view < 4; ++view) {
            assert(native.bind_role(generation, first.source.serial, view,
                                   first_frames[view], targets[view], scene_id));
            assert(native.bind_role(generation, second.source.serial, view,
                                   second_frames[view], targets[view], scene_id));
        }
        for (size_t view = 0; view < 4; ++view) {
            const auto a = native.render(generation, first_frames[view], targets[view], scene_id);
            const auto b = native.render(generation, second_frames[view], targets[view], scene_id);
            assert(a && a->source.serial == first.source.serial && a->view == view &&
                   a->source.engine_frame == first.engine.engine_frame);
            assert(b && b->source.serial == second.source.serial && b->view == view &&
                   b->source.engine_frame == second.engine.engine_frame);
        }
    }
}

void test_thousand_completed_transactions_leave_no_pending_tickets() {
    D delivery;
    N native{delivery};
    constexpr std::array<size_t, 4> order{3, 2, 1, 0};
    constexpr uint64_t generation = 44;
    for (uint64_t transaction = 1; transaction <= 1000; ++transaction) {
        const auto serial = transaction + 1000;
        const auto engine_frame = static_cast<uint32_t>(5000 + transaction * 4);
        const auto role_frames = frames_from(engine_frame + 20);
        bind_owner(delivery, native, generation, serial, engine_frame,
                   0x100000 + transaction, 0x44);
        std::array<N::TailTicket, 4> tails{};

        for (size_t view : order) {
            assert(native.bind_role(generation, serial, view, role_frames[view],
                                   targets[view], scene_id));
            const auto command = native.render(generation, role_frames[view], targets[view], scene_id);
            assert(command && command->view == view && command->source.engine_frame == engine_frame);
            const auto attached = native.hook_batch(*command,
                static_cast<std::uintptr_t>(0x300000 + transaction * 8 + view),
                0, 0, role_frames[view]);
            assert(attached.status == N::AttachStatus::attached);
            tails[view] = attached.tail;
        }
        for (const auto& tail : tails) assert(native.executed_tail(tail, 77).accepted);
        assert(delivery.pending_engine_commands(generation) == 0);
        assert(delivery.diagnostics_snapshot(generation).pending_engine_tickets == 0);
        assert(delivery.engine_commands_retired(generation));
        assert(native.diagnostics_snapshot(generation).occupied_slots == 0);
        const auto selected = delivery.select(generation, 77);
        assert(selected && selected->serial == serial && selected->engine_frame == engine_frame);
        assert(delivery.submitted(*selected, static_cast<std::uintptr_t>(0x500000 + transaction)));
        assert(delivery.retire(generation, serial));
        assert(!delivery.select(generation, 77));
    }
}

} // namespace

int main() {
    test_all_role_orderings();
    test_missing_and_mismatched_role_frames();
    test_conflicting_rebind_poisoning();
    test_reused_targets_require_unique_role_frame();
    test_thousand_completed_transactions_leave_no_pending_tickets();
}
