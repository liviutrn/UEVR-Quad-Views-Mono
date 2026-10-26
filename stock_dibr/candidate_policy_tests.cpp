#include "CandidatePolicy.hpp"

#include <cstdint>
#include <cstdio>

namespace {
unsigned failures{};

void expect(bool condition, const char* description) {
    if (condition) return;
    std::fprintf(stderr, "FAIL: %s\n", description);
    ++failures;
}
}

int main() {
    using stock_dibr::CandidatePolicy;

    CandidatePolicy<2> policy;
    const auto first = policy.observe(0x100, 1920, 1080, 40, 7);
    const auto second = policy.observe(0x200, 960, 540, 41, 8);
    expect(first != 0 && second != 0 && first != second,
        "observed sources receive distinct non-auto IDs");
    expect(policy.id_for_identity(0x100) == first && policy.id_for_identity(0x999) == 0,
        "identity lookup returns a known ID or zero");
    expect(policy.observe(0x100, 1916, 1080, 40, 9) == first,
        "same live source keeps its ID while metadata and epoch update");
    expect(policy.id_for_identity(0x100) == first,
        "identity lookup keeps the refreshed source ID");

    auto infos = policy.candidates();
    expect(infos.size() == 2 && infos[0].last_seen_epoch == 9 &&
        infos[0].width == 1916 && infos[0].format == 40,
        "candidate metadata is copied and refreshed");
    expect(!infos[0].available && !infos[1].available,
        "metadata does not claim availability without a fresh slot");

    expect(!policy.select(999), "unknown explicit candidate is rejected");
    expect(policy.selected() == 0, "rejected selection leaves automatic mode");
    expect(policy.select(second) && policy.selected() == second,
        "known candidate can be selected");
    expect(policy.observe(0x100, 1916, 1080, 40, 10) == first,
        "nonselected sources remain discoverable while another ID is selected");
    expect(policy.accepts_slot(second) && !policy.accepts_slot(first),
        "selected candidate filters out other fresh sources");
    expect(!policy.accepts_slot(0),
        "missing selected candidate cannot silently use an unknown or automatic slot");
    expect(policy.select(0) && policy.selected() == 0,
        "ID zero selects automatic mode");
    expect(policy.accepts_slot(first) && policy.accepts_slot(second),
        "automatic mode accepts the baseline candidate set");
    expect(policy.observe(0x200, 960, 540, 41, 10) == second,
        "second candidate is current before testing unsafe full-capacity behavior");

    expect(policy.observe(0x300, 800, 600, 45, 10) == 0,
        "full registry does not evict a current-epoch candidate");
    expect(policy.capacity_exhausted(), "capacity exhaustion is reported");
    expect(policy.knows(first) && policy.knows(second) && !policy.knows(0),
        "capacity exhaustion preserves existing IDs");

    policy.reset();
    expect(policy.candidates().empty() && policy.selected() == 0,
        "reset invalidates all metadata and selection");
    expect(!policy.capacity_exhausted(), "reset clears the capacity warning");
    const auto after_reset = policy.observe(0x100, 1920, 1080, 40, 1);
    expect(after_reset != 0 && after_reset != first && after_reset != second,
        "IDs are not reused across reset generations");
    expect(!policy.select(first), "pre-reset candidate ID stays invalid after reset");

    CandidatePolicy<2> eviction;
    const auto old = eviction.observe(0xA, 1920, 1080, 40, 1);
    const auto recent = eviction.observe(0xB, 1920, 1080, 40, 2);
    expect(eviction.observe(0xB, 1920, 1080, 40, 4) == recent,
        "repeated identity refreshes its last-seen epoch");
    const auto replacement = eviction.observe(0xC, 1280, 720, 40, 5);
    expect(replacement > recent && replacement != old,
        "least-recent older identity is replaced with a fresh monotonic ID");
    expect(eviction.id_for_identity(0xA) == 0 && eviction.id_for_identity(0xB) == recent &&
        eviction.id_for_identity(0xC) == replacement,
        "eviction forgets only the replaced identity mapping");
    expect(!eviction.knows(old), "evicted candidate ID becomes unknown");
    expect(eviction.select(recent), "older candidate can be explicitly pinned");
    const auto next = eviction.observe(0xD, 800, 600, 45, 6);
    expect(next > replacement && eviction.id_for_identity(0xB) == recent &&
        eviction.id_for_identity(0xC) == 0 && eviction.id_for_identity(0xD) == next,
        "selected identity is retained while the oldest other entry is evicted");
    expect(eviction.accepts_slot(recent) && !eviction.accepts_slot(next),
        "manual selection rejects every unrelated candidate slot");
    expect(eviction.observe(0xE, 640, 480, 45, 6) == 0,
        "full registry fails closed when no unselected older identity exists");
    expect(eviction.capacity_exhausted(), "unsafe eviction is reported");

    eviction.reset();
    expect(eviction.selected() == 0 && !eviction.knows(recent),
        "reset invalidates the old manual ID and returns to automatic mode");
    const auto after_selected_reset = eviction.observe(0xA, 1920, 1080, 40, 1);
    expect(after_selected_reset > next && after_selected_reset != recent &&
        eviction.selected() == 0 && eviction.accepts_slot(after_selected_reset),
        "automatic selection accepts the fresh ID after reset without ID reuse");

    std::printf("Stock DIBR candidate policy: %u failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
