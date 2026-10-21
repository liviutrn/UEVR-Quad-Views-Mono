#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <memory>

// Independent reference model: a completion writes exactly one of four physical
// targets. A selectable packet must describe every target's current contents.
// Rejection is safe; a fresh, complete uncontested quartet must recover.
namespace {
struct Packet { uint64_t serial{}; };
using Delivery = uevr::quadview::Delivery<Packet, 16>;
using Native = uevr::quadview::NativeDelivery<Delivery>;
constexpr std::array<uintptr_t,4> targets{0x501,0x502,0x503,0x504};

std::array<Native::Command,4> prepare(Delivery& delivery, Native& native, uint64_t serial,
    const std::array<uintptr_t,4>& physical_targets=targets, uint64_t target_set=44) {
    const auto frame=static_cast<uint32_t>(100+serial);
    Delivery::Source source{std::make_shared<const Packet>(Packet{serial}),1,serial,frame,serial,
        0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
    Delivery::EngineTicket engine{1,serial,frame,source.family,source.target,source.scene};
    assert(delivery.register_engine_family(engine));
    assert(delivery.register_bound(source));
    assert(native.bind(source,engine,target_set,physical_targets));
    std::array<Native::Command,4> commands{};
    for (size_t view=0;view<4;++view) {
        const auto found=native.render(1,frame,physical_targets[view],source.scene);
        assert(found); commands[view]=*found;
        assert(native.hook(commands[view],0x1000+serial*16+view));
    }
    return commands;
}

void check(Delivery& delivery, const std::array<uint64_t,4>& contents) {
    if (const auto selected=delivery.select(1,77)) {
        assert(selected->packet && selected->packet->serial==selected->serial);
        for (const auto serial:contents) assert(serial==selected->serial);
    }
}
}

int main() {
    std::array<unsigned,8> order{0,1,2,3,4,5,6,7};
    uint64_t permutations{};
    do {
        Delivery delivery;
        Native native{delivery};
        const auto older=prepare(delivery,native,1);
        const auto newer=prepare(delivery,native,2);
        std::array<uint64_t,4> contents{};
        check(delivery,contents);
        for (const auto step:order) {
            const uint64_t serial=step<4 ? 1 : 2;
            const auto view=static_cast<size_t>(step%4);
            contents[view]=serial;
            const auto& command=serial==1 ? older[view] : newer[view];
            assert(native.executed(command,0x1000+serial*16+view,77));
            check(delivery,contents);
        }
        assert(delivery.pending_engine_commands(1)==0);
        assert(delivery.engine_commands_retired(1));
        // Both draws were queued before either executed. An older writer must
        // not permanently poison a future writer that later restores all four
        // resources. This is ordinary pipeline overlap, not an exceptional case.
        if (std::all_of(contents.begin(),contents.end(),[](uint64_t serial) { return serial==2; })) {
            const auto coherent_newer=delivery.select(1,77);
            assert(coherent_newer && coherent_newer->serial==2);
        }
        const auto fresh=prepare(delivery,native,3);
        for (size_t view=0;view<4;++view) {
            contents[view]=3;
            assert(native.executed(fresh[view],0x1000+3*16+view,77));
            check(delivery,contents);
        }
        const auto recovered=delivery.select(1,77);
        assert(recovered && recovered->serial==3);
        assert(delivery.pending_engine_commands(1)==0);
        assert(delivery.engine_commands_retired(1));
        ++permutations;
    } while (std::next_permutation(order.begin(),order.end()));
    assert(permutations==40320);
    {
        // Target replacement in one active VR generation must reclaim bounded
        // bookkeeping after the previous resource owners have drained.
        Delivery delivery;
        Native native{delivery};
        for (uint64_t serial=1;serial<=40;++serial) {
            std::array<uintptr_t,4> replaced{};
            for (size_t view=0;view<4;++view) replaced[view]=0x10000+serial*64+view;
            const auto commands=prepare(delivery,native,serial,replaced,500+serial);
            for (size_t view=0;view<4;++view)
                assert(native.executed(commands[view],0x1000+serial*16+view,77));
            const auto selected=delivery.select(1,77);
            assert(selected && selected->serial==serial);
            assert(delivery.pending_engine_commands(1)==0);
        }
    }
    std::cout << "Physical content provenance: " << permutations
              << " two-quartet write permutations preserve packet/content agreement and fresh-frame recovery; 40 target replacements recover without reset.\n";
}
