#include "QuadViewDelivery.hpp"
#include "QuadViewFamilyRouting.hpp"
#include "QuadViewNativeDelivery.hpp"
#include "QuadViewRenderOrder.hpp"
#include "QuadViewSettings.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

using namespace uevr::quadview;

namespace {

struct Packet { uint64_t serial{}; };
using D = Delivery<Packet, 16>;
using N = NativeDelivery<D>;

constexpr uint64_t generation = 53;
constexpr uint64_t serial = 9001;
constexpr uint32_t canonical_frame = 1200;
constexpr uintptr_t family = 0x100;
constexpr uintptr_t producer_target = 0x200;
constexpr uintptr_t scene = 0x300;
constexpr uint64_t target_set = 0x44;
constexpr uint32_t render_thread = 77;
constexpr std::array<uintptr_t, 4> targets{0x501, 0x502, 0x503, 0x504};
constexpr std::array<uint32_t, 4> role_frames{2100, 2201, 2302, 2403};
constexpr std::array<uintptr_t, 4> views{0x801, 0x802, 0x803, 0x804};

struct DispatchContext { uintptr_t target{}; };

void test_dispatch_accepts_every_permutation_and_restores_state() {
    RenderOrder order{0, 1, 2, 3};
    do {
        auto storage = views;
        const auto original = storage;
        int32_t count = 4;
        DispatchContext context{0x900};
        const auto original_target = context.target;
        std::vector<size_t> before_roles;
        std::vector<size_t> callback_roles;
        size_t first_batch_count{};
        size_t singleton_count{};
        size_t active_role{};

        const auto result = dispatch_main_views(
            storage.data(), storage.size(), count, context, views, targets,
            [](const DispatchContext& value) { return value.target; },
            [](DispatchContext& value, uintptr_t target) { value.target = target; },
            [&](size_t role) { active_role = role; before_roles.push_back(role); return true; },
            [&] { ++first_batch_count; callback_roles.push_back(active_role); },
            [&] { ++singleton_count; callback_roles.push_back(active_role); },
            [&](size_t role) { return role == active_role && context.target == targets[role]; },
            order);

        assert(result && result.completed == 4);
        assert(before_roles == std::vector<size_t>(order.begin(), order.end()));
        assert((callback_roles == std::vector<size_t>{order[0], order[1], order[2], order[3]}));
        assert(first_batch_count == 1 && singleton_count == 3);
        assert(storage == original && count == 4 && context.target == original_target);
    } while (std::next_permutation(order.begin(), order.end()));
}

void test_dispatch_failure_exception_and_invalid_orders_restore_or_reject() {
    {
        auto storage = views;
        const auto original = storage;
        int32_t count = 4;
        DispatchContext context{0x900};
        constexpr RenderOrder order{2, 3, 0, 1};
        std::vector<size_t> callback_roles;
        size_t first_batch_role = 99;
        const auto result = dispatch_main_views(
            storage.data(), storage.size(), count, context, views, targets,
            [](const DispatchContext& value) { return value.target; },
            [](DispatchContext& value, uintptr_t target) { value.target = target; },
            [](size_t) { return true; },
            [&] { first_batch_role = order[0]; callback_roles.push_back(order[0]); },
            [&] { callback_roles.push_back(order[callback_roles.size()]); },
            [](size_t role) { return role != 0; }, order);
        assert(result.status == MainFamilyDispatchStatus::callback_validation_failed);
        assert(result.completed == 2);
        assert(first_batch_role == order[0]);
        assert((callback_roles == std::vector<size_t>{2, 3, 0}));
        assert(storage == original && count == 4 && context.target == 0x900);
    }
    {
        auto storage = views;
        const auto original = storage;
        int32_t count = 4;
        DispatchContext context{0x900};
        constexpr RenderOrder order{3, 2, 1, 0};
        size_t calls{};
        bool caught{};
        try {
            (void)dispatch_main_views(
                storage.data(), storage.size(), count, context, views, targets,
                [](const DispatchContext& value) { return value.target; },
                [](DispatchContext& value, uintptr_t target) { value.target = target; },
                [](size_t) { return true; }, [] { throw std::runtime_error("first callback"); },
                [&] { ++calls; }, [](size_t) { return true; }, order);
        } catch (const std::runtime_error&) { caught = true; }
        assert(caught && calls == 0);
        assert(storage == original && count == 4 && context.target == 0x900);
    }
    for (const RenderOrder invalid : {RenderOrder{0, 0, 1, 2}, RenderOrder{0, 1, 2, 4}}) {
        auto storage = views;
        const auto original = storage;
        int32_t count = 4;
        DispatchContext context{0x900};
        unsigned calls{};
        const auto result = dispatch_main_views(
            storage.data(), storage.size(), count, context, views, targets,
            [](const DispatchContext& value) { return value.target; },
            [](DispatchContext& value, uintptr_t target) { value.target = target; },
            [&](size_t) { ++calls; return true; }, [&] { ++calls; }, [&] { ++calls; },
            [&](size_t) { ++calls; return true; }, invalid);
        assert(result.status == MainFamilyDispatchStatus::invalid_order);
        assert(calls == 0 && storage == original && count == 4 && context.target == 0x900);
    }
}

void test_render_order_sequence_freezes_retries_and_resets_by_generation() {
    RenderOrderSequence sequence;
    const auto first = sequence.prepare(1, 10, 3);
    assert(first && first.sequence == 0 && first.mode == 3);
    assert((first.order == RenderOrder{2, 3, 0, 1}));
    assert(sequence.prepare(1, 10, 2) == first); // UI changes wait for a new source.
    assert(!sequence.prepare(1, 9, 3));
    assert(!sequence.prepare(0, 11, 3));
    assert(!sequence.complete({1, 10, 3, 3, RenderOrder{3, 2, 0, 1}}));
    assert(sequence.prepare(1, 10, 1) == first); // Failed quartet retries the frozen plan.
    assert(sequence.complete(first));
    assert(!sequence.complete(first)); // Duplicate completion cannot advance twice.

    const auto second = sequence.prepare(1, 11, 3);
    assert(second && second.sequence == 1 && (second.order == RenderOrder{3, 2, 0, 1}));
    assert(sequence.prepare(1, 11, 0) == second);
    assert(sequence.prepare(1, 10, 3) == RenderOrderPlan{});
    assert(sequence.complete(second));
    const auto third = sequence.prepare(1, 12, 3);
    assert(third && third.sequence == 2 && (third.order == RenderOrder{2, 3, 0, 1}));
    assert(sequence.complete(third));

    const auto reset = sequence.prepare(2, 1, 3);
    assert(reset && reset.sequence == 0 && (reset.order == RenderOrder{2, 3, 0, 1}));
    assert(!sequence.prepare(1, 2, 3)); // A stale generation cannot roll back phase.
    assert(sequence.prepare(2, 1, 0) == reset);
    assert(sequence.complete(reset));

    assert((render_order(0, 99) == canonical_render_order));
    assert((render_order(1, 99) == RenderOrder{2, 3, 0, 1}));
    assert((render_order(2, 99) == RenderOrder{3, 2, 0, 1}));
}

void test_settings_reject_invalid_render_order() {
    Settings current{};
    current.render_order_mode = 2;
    Settings requested = current;
    requested.render_order_mode = 4;
    const auto result = reconcile_settings(requested, current, 1920, 1080);
    assert((result.rejected & reject_render_order) != 0);
    assert(result.settings.render_order_mode == 2);
}

void test_all_dispatch_orders_keep_canonical_roles_and_native_retirement() {
    RenderOrder order{0, 1, 2, 3};
    do {
        D delivery;
        N native{delivery};
        D::Source source{std::make_shared<const Packet>(Packet{serial}), generation, serial,
            canonical_frame, serial, family, producer_target, scene,
            {0x401, 0x402, 0x403, 0x404}};
        const D::EngineTicket engine{generation, serial, canonical_frame,
            family, producer_target, scene};
        assert(delivery.register_engine_family(engine));
        assert(delivery.register_bound(source));
        assert(!native.bind(source, engine, target_set, targets, true, 4));
        assert(native.diagnostics_snapshot(generation).occupied_slots == 0);
        const auto runtime_role = static_cast<uint8_t>(order.back());
        assert(native.bind(source, engine, target_set, targets, true, runtime_role));

        auto storage = views;
        int32_t count = 4;
        DispatchContext context{0x900};
        std::array<N::Command, 4> commands{};
        std::array<N::TailTicket, 4> tails{};
        std::array<N::RenderTrace, 4> traces{};
        std::array<bool, 4> processed{};
        size_t first_batch_count{};
        size_t singleton_count{};
        size_t active_role{};

        const auto process_role = [&] {
            const auto role = active_role;
            assert(role < 4 && !processed[role]);
            N::RenderTrace trace{};
            const auto command = native.render(generation, role_frames[role],
                targets[role], scene, &trace);
            assert(command && command->view == role && command->target == targets[role]);
            assert(command->source.engine_frame == canonical_frame);
            assert(command->source.serial == serial);
            assert(trace.role == role && trace.canonical_frame == canonical_frame);
            traces[role] = trace;
            const auto attached = native.hook_batch(*command, 0x10000 + role,
                0, 0, role_frames[role]);
            assert(attached.status == N::AttachStatus::attached);
            commands[role] = *command;
            tails[role] = attached.tail;
            processed[role] = true;
        };

        const auto result = dispatch_main_views(
            storage.data(), storage.size(), count, context, views, targets,
            [](const DispatchContext& value) { return value.target; },
            [](DispatchContext& value, uintptr_t target) { value.target = target; },
            [&](size_t role) {
                active_role = role;
                return native.bind_role(generation, serial, role, role_frames[role],
                    targets[role], scene);
            },
            [&] { ++first_batch_count; process_role(); },
            [&] { ++singleton_count; process_role(); },
            [&](size_t role) { return processed[role] && context.target == targets[role]; },
            order);

        assert(result && first_batch_count == 1 && singleton_count == 3);
        assert(storage == views && count == 4 && context.target == 0x900);
        for (size_t role = 0; role < 4; ++role) {
            assert(processed[role]);
            assert(traces[role].engine_claim == (role == order[0]));
            assert(traces[role].source_claim == (role == order[0]));
            const auto event = native.runtime_event(tails[role]);
            assert(bool(event) == (role == runtime_role));
            if (role == runtime_role) {
                assert(event.generation == generation && event.serial == serial &&
                       event.frame == role_frames[role]);
            }
        }

        N::RuntimeEvent claimed{};
        size_t claims{};
        for (size_t role = 0; role < 4; ++role)
            if (native.claim_runtime_event(tails[role], claimed)) ++claims;
        assert(claims == 1 && claimed.generation == generation && claimed.serial == serial &&
               claimed.frame == role_frames[runtime_role]);

        assert(!delivery.engine_commands_retired(generation));
        assert(delivery.pending_engine_commands(generation) == 1);
        assert(!delivery.select(generation, render_thread));
        for (size_t ordinal = 0; ordinal < 3; ++ordinal) {
            const auto role = order[ordinal];
            assert(native.executed_tail(tails[role], render_thread).accepted);
            assert(!delivery.engine_commands_retired(generation));
            assert(!delivery.select(generation, render_thread));
        }
        assert(native.diagnostics_snapshot(generation).occupied_slots == 1);
        assert(native.executed_tail(tails[runtime_role], render_thread).accepted);
        assert(delivery.engine_commands_retired(generation));
        assert(delivery.pending_engine_commands(generation) == 0);
        const auto selected = delivery.select(generation, render_thread);
        assert(selected && selected->serial == serial && selected->engine_frame == canonical_frame);
    } while (std::next_permutation(order.begin(), order.end()));
}

} // namespace

int main() {
    test_dispatch_accepts_every_permutation_and_restores_state();
    test_dispatch_failure_exception_and_invalid_orders_restore_or_reject();
    test_render_order_sequence_freezes_retries_and_resets_by_generation();
    test_settings_reject_invalid_render_order();
    test_all_dispatch_orders_keep_canonical_roles_and_native_retirement();
    std::cout << "QuadView render-order contracts passed\n";
}
