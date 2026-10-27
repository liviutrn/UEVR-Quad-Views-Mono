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

    // Stable route membership is independent of physical allocation identity.
    const stock_dibr::ProducerRoute main_route{1, 40, 1, 0, 0, 0, 0, 1920, 1080, 123, 0};
    auto secondary_route = main_route; secondary_route.ordinal = 1;
    CandidatePolicy<4> rotation;
    const auto family = rotation.observe(0x10,1920,1080,40,1,main_route);
    expect(rotation.select(family), "manual pins the producer family");
    expect(rotation.permits_record(0x20), "unknown rotating allocation reaches execute proof");
    expect(rotation.observe(0x20,1920,1080,40,2,main_route)==family,
        "validated absent-member route joins rotating physical resource");
    expect(rotation.physical_id_for_identity(0x10)!=rotation.physical_id_for_identity(0x20),
        "physical identities remain distinct within family");
    expect(rotation.observe(0x10,1920,1080,40,3,secondary_route)==family,
        "known physical member preserves family when execution order changes");
    expect(rotation.candidates()[0].members==2 && !rotation.accepts_slot(family),
        "known pooled member retains membership but incompatible route fails manual");
    const auto secondary = rotation.observe(0x30,1920,1080,40,3,main_route);
    expect(secondary!=family && !rotation.accepts_slot(family),
        "changed known route blocks speculative membership and fails manual");
    CandidatePolicy<3> collision;
    const auto collided=collision.observe(1,1920,1080,40,1,main_route);
    collision.select(collided);
    collision.observe(2,1920,1080,40,2,main_route);
    collision.observe(1,1920,1080,40,2,main_route);
    expect(!collision.accepts_slot(collided),
        "late same-epoch co-occurrence marks merged route ambiguous and fails manual");
    expect(!rotation.permits_record(0x30), "known unrelated sources can be filtered at recording");

    CandidatePolicy<4> distinct;
    const auto left=distinct.observe(1,1920,1080,40,1,main_route);
    const auto mirror=distinct.observe(2,1920,1080,40,1,secondary_route);
    expect(left!=mirror&&!distinct.candidates()[0].ambiguous,
        "same-shape distinct co-occurring routes are distinct families");
    CandidatePolicy<4> automatic;
    const auto first_auto=automatic.observe(1,1920,1080,40,1,{},1);
    const auto latest_auto=automatic.observe(2,1920,1080,40,1,{},2);
    automatic.choose_auto(1);
    expect(automatic.automatic()==latest_auto,"initial equal-area winner preserves R6 latest serial");
    for(uint64_t e=2;e<=5;++e) {
        automatic.observe(2,1920,1080,40,e,{},e*2);
        automatic.observe(1,1920,1080,40,e,{},e*2+1);
        automatic.choose_auto(e);
        expect(automatic.automatic()==latest_auto,"fresh persistent choice survives reversed latest tie");
    }
    for(uint64_t e=6;e<=10;++e) {
        automatic.observe(1,2000,1080,40,e);
        automatic.observe(2,1920,1080,40,e);automatic.choose_auto(e);
    }
    expect(automatic.automatic()==latest_auto,"slightly larger candidate does not evict");
    for(uint64_t e=11;e<=159;++e) {
        automatic.observe(1,2560,1440,40,e);
        automatic.observe(2,1920,1080,40,e);automatic.choose_auto(e);
    }
    expect(automatic.automatic()==latest_auto,"huge challenger does not evict a fresh persistent choice");
    automatic.observe(1,2560,1440,40,160);
    automatic.observe(2,1920,1080,40,160);automatic.choose_auto(160);
    expect(automatic.automatic()==latest_auto,"150 sustained larger epochs do not evict fresh choice");
    expect(automatic.switch_count()==1,"only initial automatic choice is counted while it remains fresh");
    for(uint64_t e=161;e<=162;++e) {
        automatic.observe(1,2560,1440,40,e);automatic.choose_auto(e);
        expect(automatic.automatic()==latest_auto&&automatic.accepts_slot(first_auto),
            "absent family grace permits fresh physical R6 fallback without stale images");
    }
    automatic.observe(1,2560,1440,40,163);automatic.choose_auto(163);
    expect(automatic.automatic()==first_auto,"three absent epochs commit a fresh replacement");
    expect(automatic.select(latest_auto)&&!automatic.accepts_slot(first_auto),"missing manual family never falls back");
    automatic.reset();
    const auto reset_family=automatic.observe(1,1920,1080,40,1,main_route);
    expect(reset_family>latest_auto&&automatic.selected()==0,"family IDs never reused after reset");

    auto uncorroborated=main_route;uncorroborated.dsv_handle=0;
    CandidatePolicy<4> separate;
    const auto unrelated_a=separate.observe(10,1920,1080,40,1,uncorroborated);
    const auto unrelated_b=separate.observe(11,1920,1080,40,2,uncorroborated);
    expect(unrelated_a!=unrelated_b,"alternate epochs same ordinal without stable marker never merge");
    separate.select(unrelated_a);
    auto reused_route=uncorroborated;reused_route.ordinal=1;
    separate.observe(10,1920,1080,40,3,reused_route);
    expect(!separate.accepts_slot(unrelated_a),"pooled same physical identity with incompatible route fails manual");
    separate.select(0);separate.choose_auto(3);
    expect(separate.accepts_slot(unrelated_a),"ambiguous manual family remains fresh R6 fallback in Auto");

    auto named_a=main_route; named_a.resource_name_hash=0x123456;
    auto named_b=named_a;named_b.dsv_handle=456;
    CandidatePolicy<4> named_rotation;
    const auto named_family=named_rotation.observe(40,1920,1080,40,1,named_a);
    named_rotation.select(named_family);
    expect(named_rotation.observe(41,1920,1080,40,2,named_b)==named_family,
        "exact nonzero resource name and executed route corroborate rotating different DSV handles");
    expect(named_rotation.observe(40,1920,1080,40,3,named_a)==named_family&&named_rotation.accepts_slot(named_family),
        "named rotating pool returns to prior physical member without manual drop");
    expect(named_rotation.candidates()[0].resource_name_hash==named_a.resource_name_hash&&
        named_rotation.candidates()[0].route_confidence==2,
        "copied metadata exposes exact-name producer evidence");
    auto different_name=named_a;different_name.resource_name_hash=0x123457;
    const auto other_named=named_rotation.observe(42,1920,1080,40,4,different_name);
    expect(other_named!=named_family,"different exact names never merge through recycled DSV handle");
    named_rotation.observe(40,1920,1080,40,5,different_name);
    expect(!named_rotation.accepts_slot(named_family),"same physical renamed producer fails manual despite same DSV");

    CandidatePolicy<4> dynamic_resolution;
    auto full_resolution=main_route;full_resolution.resource_name_hash=0x9876;
    const auto dynamic_family=dynamic_resolution.observe(50,1920,1080,40,1,full_resolution);
    dynamic_resolution.select(dynamic_family);
    auto reduced=full_resolution;reduced.width=1280;reduced.height=720;
    expect(dynamic_resolution.observe(50,1280,720,40,2,reduced)==dynamic_family&&
        dynamic_resolution.accepts_slot(dynamic_family),
        "known named physical member retains manual family during matching-aspect dynamic resolution");
    reduced.dsv_handle=789;
    expect(dynamic_resolution.observe(51,1280,720,40,3,reduced)==dynamic_family&&
        dynamic_resolution.accepts_slot(dynamic_family),
        "new named rotating physical member joins across matching-aspect dynamic resolution");
    auto off_aspect=reduced;off_aspect.width=1024;
    expect(dynamic_resolution.observe(52,1024,720,40,4,off_aspect)!=dynamic_family,
        "same-name off-aspect resource cannot join producer family");

    CandidatePolicy<1> bounded_rotation;
    const auto bounded_family=bounded_rotation.observe(100,1920,1080,40,1,main_route);
    bounded_rotation.select(bounded_family);
    for(uint64_t e=2;e<=12;++e)
        expect(bounded_rotation.observe(100+e,1920,1080,40,e,main_route)==bounded_family,
            "bounded physical member LRU keeps pinned rotating family");
    expect(bounded_rotation.candidates()[0].members<=CandidatePolicy<1>::MemberCapacity,
        "physical identity registry is bounded");
    expect(!bounded_rotation.id_for_identity(100),"physical LRU forgets evicted identity tokens");
    expect(bounded_rotation.observe(999,1920,1080,40,12,secondary_route)==0,
        "family quota retains selected family and rejects competing current source");

    std::printf("Stock DIBR candidate policy: %u failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
