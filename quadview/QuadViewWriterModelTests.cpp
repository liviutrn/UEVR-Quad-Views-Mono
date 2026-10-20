#include "QuadViewDelivery.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <numeric>
#include <optional>
#include <random>
#include <stdexcept>

int main() {
    using D=uevr::quadview::Delivery<int>;
    std::mt19937 rng(20261021);
    size_t completions=0;
    for (int trial=0;trial<20000;++trial) {
        D d;
        std::array<D::EngineTicket,8> tickets{};
        std::array<D::Source,8> sources{};
        std::array<bool,8> has_source{};
        std::array<int,8> order{};
        std::array<std::optional<D::Source>,2> expected{};
        std::iota(order.begin(),order.end(),0);
        std::shuffle(order.begin(),order.end(),rng);
        for(int i=0;i<8;++i) {
            const uintptr_t target=0x100+(rng()%2);
            tickets[i]={1,uint64_t(i+1),uint32_t(i+1),uintptr_t(0x200+i),target,0x300};
            if(!d.register_engine_family(tickets[i])) throw std::runtime_error("engine admission");
            has_source[i]=(rng()%3)!=0;
            if(has_source[i]) {
                sources[i]={std::make_shared<const int>(i),1,uint64_t(i+1),uint32_t(i+1),uint64_t(i+100),
                    uintptr_t(0x200+i),target,0x300,{1,2,3,4},true};
                if(!d.register_bound(sources[i])) throw std::runtime_error("source admission");
            }
        }
        for(const int i:order) {
            const auto& e=tickets[i];
            auto rt=d.render_engine_family(1,e.engine_frame,e.target,e.scene);
            std::optional<D::Source> source;
            if(has_source[i]) source=d.render(1,e.engine_frame,e.family+0x1000,e.target,e.scene);
            if(!rt || (has_source[i]&&!source)) throw std::runtime_error("render match");
            const uintptr_t command=0x400+i;
            if(!d.tail_hooked_engine_family(*rt,source.value_or(D::Source{}),command) ||
               !d.executed_engine_family(*rt,source.value_or(D::Source{}),command,7))
                throw std::runtime_error("completion");
            expected[e.target-0x100]=source;
            std::optional<D::Source> newest;
            for(const auto& candidate:expected)
                if(candidate&&(!newest||candidate->serial>newest->serial)) newest=candidate;
            const auto got=d.select(1,7);
            if(bool(got)!=bool(newest)||(got&&!got->same_owner(*newest)))
                throw std::runtime_error("selection disagrees with independent target-writer model");
            ++completions;
        }
        if(!d.engine_commands_retired(1)) throw std::runtime_error("drain after all tails");
    }
    std::cout<<completions<<" randomized multi-target, source/no-source, out-of-order completions passed\n";
}
