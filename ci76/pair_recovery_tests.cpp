#include "NgxPairRecovery.hpp"

#include <cassert>
#include <cstdint>

using namespace uevr::duoview::ngx::recovery;

static Observation sample(std::uint64_t epoch, std::uint64_t serial_base,
                          std::uint64_t evaluation_base,
                          SourceSignature source = {11, 2030, 1614, 22, 812, 646}) {
    return {true, source, epoch,
            {serial_base, serial_base + 1},
            {evaluation_base, evaluation_base + 1}};
}

static void finish_recovery(PairRecovery& gate, std::uint64_t epoch,
                            std::uint64_t serial, std::uint64_t evaluation,
                            SourceSignature source = {11, 2030, 1614, 22, 812, 646}) {
    const auto already = gate.fresh_pair_count();
    assert(already < RequiredFreshPairs);
    const auto needed = static_cast<std::uint64_t>(RequiredFreshPairs - already);
    for (std::uint64_t i = 0; i < needed; ++i) {
        const auto result = gate.observe(sample(epoch + i, serial + 2 * i,
                                                evaluation + 2 * i, source));
        assert(result.consecutive_fresh_pairs == already + i + 1);
        if (result.consecutive_fresh_pairs == RequiredFreshPairs) {
            assert(result.allow);
            assert(result.reason == Reason::ready);
        } else {
            assert(!result.allow);
        }
    }
    assert(gate.allowed());
    assert(gate.reason() == Reason::ready);
}

static void requires_eight_distinct_consecutive_pairs() {
    PairRecovery gate;
    finish_recovery(gate, 10, 100, 500);
}

static void missing_pair_drops_immediately_without_carry() {
    PairRecovery gate;
    finish_recovery(gate, 10, 100, 500);

    auto missing = sample(18, 116, 516);
    missing.pair_present = false;
    const auto dropped = gate.observe(missing);
    assert(!dropped.allow);
    assert(dropped.reason == Reason::missing_pair);
    assert(dropped.consecutive_fresh_pairs == 0);

    const auto first = gate.observe(sample(19, 118, 518));
    assert(!first.allow);
    assert(first.consecutive_fresh_pairs == 1);
    finish_recovery(gate, 20, 120, 520);
}

static void duplicate_epoch_does_not_advance_or_reuse_depth() {
    PairRecovery gate;
    auto first = gate.observe(sample(7, 70, 700));
    assert(first.consecutive_fresh_pairs == 1);

    const auto duplicate_epoch = gate.observe(sample(7, 72, 702));
    assert(!duplicate_epoch.allow);
    assert(duplicate_epoch.reason == Reason::duplicate_epoch);
    assert(duplicate_epoch.consecutive_fresh_pairs == 1);

    const auto next = gate.observe(sample(8, 74, 704));
    assert(!next.allow);
    assert(next.consecutive_fresh_pairs == 2);
}

static void repeated_pair_resets_recovery() {
    PairRecovery gate;
    assert(gate.observe(sample(1, 10, 100)).consecutive_fresh_pairs == 1);
    assert(gate.observe(sample(2, 12, 102)).consecutive_fresh_pairs == 2);

    const auto repeated = gate.observe(sample(3, 12, 102));
    assert(!repeated.allow);
    assert(repeated.reason == Reason::repeated_pair);
    assert(repeated.consecutive_fresh_pairs == 0);

    const auto after = gate.observe(sample(4, 16, 106));
    assert(!after.allow);
    assert(after.consecutive_fresh_pairs == 1);
}

static void reusing_one_eyes_depth_does_not_count_as_a_fresh_pair() {
    PairRecovery gate;
    assert(gate.observe(sample(1, 10, 100)).consecutive_fresh_pairs == 1);
    assert(gate.observe(sample(2, 12, 102)).consecutive_fresh_pairs == 2);

    // Exact stereo tuple differs, but the left depth serial is from history.
    auto repeated_left = sample(3, 10, 104);
    const auto decision = gate.observe(repeated_left);
    assert(!decision.allow);
    assert(decision.reason == Reason::repeated_pair);
    assert(decision.consecutive_fresh_pairs == 0);
    assert(!gate.allowed());
}

static void duplicate_epoch_cannot_report_gate_ready() {
    PairRecovery gate;
    finish_recovery(gate, 1, 10, 100);
    const auto repeated_present = gate.observe(sample(8, 40, 130));
    assert(!repeated_present.allow);
    assert(repeated_present.reason == Reason::duplicate_epoch);
    assert(!gate.allowed());
    assert(gate.fresh_pair_count() == RequiredFreshPairs);
}

static void feature_pin_or_output_resize_resets_identity() {
    PairRecovery gate;
    for (std::uint64_t i = 0; i < 7; ++i)
        gate.observe(sample(20 + i, 200 + 2 * i, 800 + 2 * i));
    assert(gate.fresh_pair_count() == 7);

    auto changed = SourceSignature{33, 2030, 1614, 22, 812, 646}; // LEFT pin changed
    const auto pin_change = gate.observe(sample(27, 214, 814, changed));
    assert(!pin_change.allow);
    assert(pin_change.reason == Reason::source_changed);
    assert(pin_change.consecutive_fresh_pairs == 1);

    changed[4] = 2028; changed[5] = 1612; // RIGHT output resized
    const auto resize = gate.observe(sample(28, 216, 816, changed));
    assert(!resize.allow);
    assert(resize.reason == Reason::source_changed);
    assert(resize.consecutive_fresh_pairs == 1);
    finish_recovery(gate, 29, 218, 818, changed);
}

static void epoch_gap_restarts_at_one() {
    PairRecovery gate;
    for (std::uint64_t i = 0; i < 5; ++i)
        gate.observe(sample(100 + i, 300 + 2 * i, 900 + 2 * i));
    assert(gate.fresh_pair_count() == 5);

    const auto gap = gate.observe(sample(107, 312, 912));
    assert(!gap.allow);
    assert(gap.reason == Reason::epoch_gap);
    assert(gap.consecutive_fresh_pairs == 1);
    finish_recovery(gate, 108, 314, 914);
}

static void reject_clears_all_recovery_progress() {
    PairRecovery gate;
    for (std::uint64_t i = 0; i < 6; ++i)
        gate.observe(sample(200 + i, 400 + 2 * i, 1000 + 2 * i));
    const auto rejected = gate.reject();
    assert(!rejected.allow);
    assert(rejected.consecutive_fresh_pairs == 0);
    assert(gate.observe(sample(206, 412, 1012)).consecutive_fresh_pairs == 1);
}

int main() {
    requires_eight_distinct_consecutive_pairs();
    missing_pair_drops_immediately_without_carry();
    duplicate_epoch_does_not_advance_or_reuse_depth();
    repeated_pair_resets_recovery();
    reusing_one_eyes_depth_does_not_count_as_a_fresh_pair();
    duplicate_epoch_cannot_report_gate_ready();
    feature_pin_or_output_resize_resets_identity();
    epoch_gap_restarts_at_one();
    reject_clears_all_recovery_progress();
}
