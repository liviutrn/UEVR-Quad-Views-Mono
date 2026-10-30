#pragma once
// Counts recognized depth-write->read barrier events, including those excluded
// by the copy budget. NOT a semantic UE render stage or frame identifier.
#include <cstdint>
#include <cstddef>
#include <unordered_map>
#include <limits>
namespace duoview::depthpin {
class ObservedPassCounter {
    std::unordered_map<std::uintptr_t,std::uint32_t> ranks_;
public:
    static constexpr std::size_t MaxSources=4096;
    std::uint32_t observe(std::uintptr_t source) {
        if(!source)return 0;
        if(auto it=ranks_.find(source);it!=ranks_.end()) {
            if(it->second==(std::numeric_limits<std::uint32_t>::max)())return 0;
            return ++it->second;
        }
        if(ranks_.size()>=MaxSources)return 0;
        return ranks_.emplace(source,1u).first->second;
    }
    void clear(){ranks_.clear();}
    std::size_t source_count() const {return ranks_.size();}
};
}
