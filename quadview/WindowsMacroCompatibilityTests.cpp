// Reproduce Windows SDK's function-like max macro after standard headers have
// already loaded. Several production translation units include these headers
// without NOMINMAX; standalone console tests otherwise miss this interaction.
#include "QuadViewDelivery.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <optional>
#include <type_traits>
#define max(a,b) WINDOWS_MAX_MACRO_MUST_NOT_EXPAND_IN_PRODUCTION_HEADERS
#include "QuadViewNativeDelivery.hpp"
#undef max
#include <cassert>
#include <iostream>
#include <memory>
struct MacroPacket {};
int main() {
    using D=uevr::quadview::Delivery<MacroPacket,32>;
    D delivery;
    uevr::quadview::EngineDrainBatch<D> batch{};
    D::EngineTicket first{1,9,10,0x100,0x200,0x300};
    D::EngineTicket older{1,8,11,0x100,0x200,0x300};
    assert(delivery.register_engine_family(first));
    assert(delivery.register_engine_family(older));
    auto a=delivery.render_engine_family(1,10,0x200,0x300);
    auto b=delivery.render_engine_family(1,11,0x200,0x300);
    assert(a && b);
    assert(batch.attach(delivery,*a,0x700));
    assert(batch.attach(delivery,*b,0x700));
    assert(batch.newest_serial==9);
    assert(batch.execute(delivery,0x700,77,1));
    assert(delivery.engine_commands_retired(1));
    std::cout<<"Production recovery headers tolerate Windows max macro; serial ordering preserved.\n";
}
