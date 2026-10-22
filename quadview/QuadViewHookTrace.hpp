#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace uevr::quadview {
// Scalar observation only. No source leases, command pointers to dereference,
// retirement decisions, GPU operations or runtime synchronization live here.
struct HookTraceRecord {
    const char* event{"UNKNOWN"};
    const char* reason{"none"};
    const char* detail{"none"};
    uint64_t generation{}, serial{}, owner_generation{}, owner_serial{}, drain{};
    uint32_t frame{}, recorded_frame{};
    uint32_t canonical_frame{};
    unsigned rendered{},hooked{},executed{},written{};
    unsigned role{255};
    int mode{-1}, index{-1}, expected_index{-1}, result{-1};
    uintptr_t family{}, target{}, scene{}, list{}, root{}, tail{}, vtable{}, original_vtable{};
    size_t vtables{}, engines{}, natives{}, drains{};
    size_t pending{};
    bool recorded{}, ours_known{}, ours{}, engine{}, native{}, source{}, duo{};
    uint64_t elapsed_us{};
};
void emit_hook_trace(size_t site,const HookTraceRecord& record);
int hook_trace_mode();

class HookTraceGate {
public:
    struct Decision { bool emit{}; uint64_t count{}; };
    static constexpr size_t site_count=192;
    // Three initial draw serials include both startup atlas draws and the
    // first quartet. Each site is independently bounded, then summarized.
    Decision visit(size_t site,uint64_t generation,uint64_t serial,uint64_t now_ms) {
        if(site>=site_count) return {};
        std::scoped_lock lock{mutex_};
        Epoch* epoch{};
        for(auto& e:epochs_) if(e.used && e.generation==generation) {epoch=&e;break;}
        if(!epoch) {epoch=&epochs_[next_++%epochs_.size()];*epoch={};epoch->used=true;epoch->generation=generation;}
        if(!epoch->first_serial && serial) epoch->first_serial=serial;
        auto& s=epoch->sites[site];
        ++s.count;
        const bool initial=serial && epoch->first_serial && serial>=epoch->first_serial &&
            serial-epoch->first_serial<3 && s.detailed<64;
        if(initial) ++s.detailed;
        const bool emit=initial || !s.emitted || (now_ms>=s.last_ms && now_ms-s.last_ms>=1000);
        if(emit) {s.emitted=true;s.last_ms=now_ms;}
        return {emit,s.count};
    }
private:
    struct Site {uint64_t count{},last_ms{};unsigned detailed{};bool emitted{};};
    struct Epoch {bool used{};uint64_t generation{},first_serial{};std::array<Site,site_count> sites{};};
    std::mutex mutex_{};
    std::array<Epoch,8> epochs_{};
    size_t next_{};
};
}
