#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <memory>
#include <optional>

using namespace uevr::quadview;

namespace {

struct Packet { uint64_t serial{}; };
using D = Delivery<Packet, 16>;
using N = NativeDelivery<D>;

constexpr uint64_t generation = 7;
constexpr uint32_t canonical_frame = 1000;
constexpr uint32_t role_frame = 1200;
constexpr uintptr_t source_target = 0x200;
constexpr uintptr_t scene = 0x300;
constexpr std::array<uintptr_t, 4> targets{0x501, 0x502, 0x503, 0x504};

enum class Scenario {
    missing_role_key,
    duplicate_rt_role,
    ambiguous_role_key,
    missing_engine_claim,
    mismatched_engine_claim,
    engine_only_drain,
};

struct State {
    bool found{};
    uint64_t serial{};
    unsigned view{};
    uint32_t source_slots{}, incomplete_sources{}, pending_engine{};
    bool engine_overflow{};
    uint32_t native_slots{}, active_tails{};
    uint64_t oldest_serial{};
    uint8_t rendered{}, hooked{}, executed{}, written{};
    bool publish{}, overwritten{};

    bool operator==(const State&) const = default;
};

struct Run {
    State state{};
    N::RenderTrace trace{};
};

struct Owner {
    D::Source source{};
    D::EngineTicket engine{};
};

Owner make_owner(D& delivery, N& native, uint64_t serial, uint32_t engine_frame,
                 uintptr_t family, bool register_engine = true,
                 bool register_source = true, uintptr_t ledger_family = 0) {
    D::Source source{std::make_shared<const Packet>(Packet{serial}), generation, serial,
        engine_frame, serial, family, source_target, scene,
        {family + 0x401, family + 0x402, family + 0x403, family + 0x404}};
    D::EngineTicket expected{generation, serial, engine_frame, family, source_target, scene};
    if (register_engine) {
        auto ledger = expected;
        if (ledger_family) ledger.family = ledger_family;
        assert(delivery.register_engine_family(ledger));
    }
    if (register_source) assert(delivery.register_bound(source));
    assert(native.bind(source, expected, 0x40 + serial, targets, true));
    return {source, expected};
}

void bind_role(N& native, uint64_t serial, uint32_t frame, uintptr_t target = targets[0]) {
    assert(native.bind_role(generation, serial, 0, frame, target, scene));
}

Run run(Scenario scenario, bool observe) {
    D delivery;
    N native{delivery};
    N::RenderTrace trace{};
    std::optional<N::Command> command;

    if (scenario == Scenario::ambiguous_role_key) {
        const auto first = make_owner(delivery, native, 50, 1000, 0x110);
        const auto second = make_owner(delivery, native, 51, 1001, 0x120);
        bind_role(native, first.source.serial, role_frame);
        bind_role(native, second.source.serial, role_frame);
        command = native.render(generation, role_frame, targets[0], scene,
                                observe ? &trace : nullptr);
    } else {
        const bool register_engine = scenario != Scenario::missing_engine_claim;
        const bool register_source = scenario != Scenario::engine_only_drain;
        const uintptr_t mismatched_family = scenario == Scenario::mismatched_engine_claim
            ? uintptr_t{0x1F0} : uintptr_t{0};
        const auto owner = make_owner(delivery, native, 40, canonical_frame, 0x100,
                                      register_engine, register_source, mismatched_family);
        if (scenario != Scenario::missing_role_key) bind_role(native, owner.source.serial, role_frame);
        if (scenario == Scenario::duplicate_rt_role) {
            const auto first = native.render(generation, role_frame, targets[0], scene);
            assert(first);
        }
        command = native.render(generation, role_frame, targets[0], scene,
                                observe ? &trace : nullptr);
    }

    const auto delivery_state = delivery.diagnostics_snapshot(generation);
    const auto native_state = native.diagnostics_snapshot(generation);
    State state{};
    state.found = bool(command);
    if (command) {
        state.serial = command->source.serial;
        state.view = command->view;
    }
    state.source_slots = delivery_state.source_slots;
    state.incomplete_sources = delivery_state.incomplete_source_slots;
    state.pending_engine = delivery_state.pending_engine_tickets;
    state.engine_overflow = delivery_state.engine_tracking_overflowed;
    state.native_slots = native_state.occupied_slots;
    state.active_tails = native_state.active_tails;
    state.oldest_serial = native_state.oldest_retained_serial;
    state.rendered = native_state.oldest_retained_rendered;
    state.hooked = native_state.oldest_retained_hooked;
    state.executed = native_state.oldest_retained_executed;
    state.written = native_state.oldest_retained_written;
    state.publish = native_state.oldest_retained_publish;
    state.overwritten = native_state.oldest_retained_overwritten;
    return {state, trace};
}

void verify(Scenario scenario, unsigned reason, unsigned expected_role = 255) {
    const auto without_observer = run(scenario, false);
    const auto with_observer = run(scenario, true);
    assert(with_observer.state == without_observer.state);
    assert(with_observer.trace.reason == reason);
    assert(with_observer.trace.role == expected_role);
}

void test_missing_role_key_and_duplicate_rt_role() {
    const auto missing = run(Scenario::missing_role_key, true);
    assert(!missing.state.found);
    assert(missing.trace.reason == 1 && missing.trace.role == 255);
    verify(Scenario::missing_role_key, 1);

    const auto duplicate = run(Scenario::duplicate_rt_role, true);
    assert(!duplicate.state.found);
    assert(duplicate.trace.reason == 3 && duplicate.trace.role == 0);
    assert(duplicate.trace.serial == 40 && duplicate.trace.canonical_frame == canonical_frame);
    verify(Scenario::duplicate_rt_role, 3, 0);
}

void test_ambiguous_role_key() {
    const auto ambiguous = run(Scenario::ambiguous_role_key, true);
    assert(!ambiguous.state.found);
    assert(ambiguous.trace.reason == 2 && ambiguous.trace.role == 255);
    assert(ambiguous.trace.serial == 0 && ambiguous.trace.canonical_frame == 0);
    verify(Scenario::ambiguous_role_key, 2);
}

void test_canonical_engine_claim_missing_or_mismatched() {
    const auto missing = run(Scenario::missing_engine_claim, true);
    assert(!missing.state.found);
    assert(missing.trace.reason == 4 && missing.trace.role == 0);
    assert(!missing.trace.engine_claim && missing.trace.source_claim);
    assert(missing.trace.serial == 40 && missing.trace.canonical_frame == canonical_frame);
    verify(Scenario::missing_engine_claim, 4, 0);

    const auto mismatched = run(Scenario::mismatched_engine_claim, true);
    assert(!mismatched.state.found);
    assert(mismatched.trace.reason == 5 && mismatched.trace.role == 0);
    assert(mismatched.trace.engine_claim && mismatched.trace.source_claim);
    assert(mismatched.trace.serial == 40 && mismatched.trace.canonical_frame == canonical_frame);
    verify(Scenario::mismatched_engine_claim, 5, 0);
}

void test_engine_only_drain_does_not_publish_source() {
    const auto drain_only = run(Scenario::engine_only_drain, true);
    assert(drain_only.state.found && drain_only.state.serial == 40 && drain_only.state.view == 0);
    assert(drain_only.trace.reason == 0 && drain_only.trace.role == 0);
    assert(drain_only.trace.engine_claim && !drain_only.trace.source_claim);
    assert(!drain_only.trace.publish);
    assert(drain_only.trace.serial == 40 && drain_only.trace.canonical_frame == canonical_frame);
    verify(Scenario::engine_only_drain, 0, 0);
}

} // namespace

int main() {
    test_missing_role_key_and_duplicate_rt_role();
    test_ambiguous_role_key();
    test_canonical_engine_claim_missing_or_mismatched();
    test_engine_only_drain_does_not_publish_source();
}
