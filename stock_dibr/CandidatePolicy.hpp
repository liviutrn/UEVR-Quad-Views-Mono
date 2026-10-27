#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace stock_dibr {

// A producer route is evidence about execution, never a semantic camera ID.
// Queue tokens must be backed by retained COM identities in the capture owner.
struct ProducerRoute {
    uint64_t queue{};
    uint32_t format_family{}, layout{}, list_index{}, ordinal{};
    int32_t x{}, y{}, width{}, height{};
    // Ordinal/shape alone cannot identify a newly allocated producer. Require
    // a repeated executed descriptor binding, or an optional exact-name hash.
    // A marker is execution evidence, never a claim of semantic camera identity.
    uint64_t dsv_handle{}, resource_name_hash{};
    bool corroborated(const ProducerRoute& b) const {
        // A contradictory/vanished explicit name cannot be overridden by a
        // recycled descriptor address. Unnamed routes require the DSV marker.
        if(resource_name_hash || b.resource_name_hash)
            return resource_name_hash && resource_name_hash == b.resource_name_hash;
        return dsv_handle && dsv_handle == b.dsv_handle;
    }
    bool valid() const { return queue && format_family && width > 0 && height > 0; }
    bool compatible(const ProducerRoute& b) const {
        const auto near = [](int32_t a, int32_t c) { return int64_t(a) - c <= 2 && int64_t(c) - a <= 2; };
        return valid() && b.valid() && queue == b.queue && format_family == b.format_family &&
            layout == b.layout && list_index == b.list_index && ordinal == b.ordinal &&
            near(x,b.x) && near(y,b.y) &&
            // Dynamic resolution changes extent while retaining viewport shape.
            // Match R5's bounded pixel alignment tolerance in aspect space.
            (int64_t(width)*b.height-int64_t(b.width)*height <=
                int64_t(8)*(height>b.height?height:b.height)) &&
            (int64_t(b.width)*height-int64_t(width)*b.height <=
                int64_t(8)*(height>b.height?height:b.height));
    }
};

struct CandidateInfo {
    uint64_t id{}, width{};
    uint32_t height{}, format{};
    uint64_t last_seen_epoch{};
    bool available{};
    uint32_t members{};
    bool ambiguous{}, selected_auto{};
    uint64_t physical_id{}, resource_name_hash{};
    // Resource marker evidence only: 0 unproven, 1 DSV, 2 exact name.
    // Shared names/handles may still describe different passes.
    uint32_t route_confidence{};
};

template<size_t Capacity>
class CandidatePolicy final {
public:
    static constexpr size_t MemberCapacity = Capacity * 4;
private:
    struct Entry { CandidateInfo info{}; ProducerRoute route{}; uint64_t current_identity{}; double area{}; bool route_unstable{}; uint64_t sequence{}; };
    struct Member { uint64_t identity{}, family{}, physical{}, seen{}; };
    std::array<Entry, Capacity> entries_{};
    std::array<Member, MemberCapacity> members_{};
    size_t count_{};
    uint64_t next_id_{1}, next_physical_{1}, selected_id_{}, auto_id_{}, finalized_epoch_{};
    uint64_t absent_streak_{}, switches_{}, stable_epochs_{};
    const char* switch_reason_{"initial"};
    bool capacity_exhausted_{}, auto_fallback_{};
    uint64_t observation_sequence_{};
    size_t find_id(uint64_t id) const {
        for (size_t i=0;i<count_;++i) if(entries_[i].info.id==id) return i;
        return Capacity;
    }
    size_t find_identity(uint64_t identity) const {
        for(size_t i=0;i<MemberCapacity;++i) if(members_[i].identity==identity) return i;
        return MemberCapacity;
    }
    void erase_family(uint64_t id) { for(auto& m:members_) if(m.family==id) m={}; }
    static uint64_t advance(uint64_t& value) {
        const auto result=value;
        value=value==(std::numeric_limits<uint64_t>::max)()?0:value+1;
        return result;
    }
public:
    uint64_t observe(uint64_t identity,uint64_t width,uint32_t height,uint32_t format,uint64_t epoch,
        const ProducerRoute& route = {}, uint64_t sequence = 0) {
        if(!identity||!width||!height||!format||!epoch) return 0;
        bool route_collision{};
        auto mi=find_identity(identity);
        auto index=mi==MemberCapacity?Capacity:find_id(members_[mi].family);
        if(index==Capacity) {
            // Only a validated route with a corroborating producer marker can
            // associate a newly allocated resource.
            // Co-occurrence is checked again below even for existing members.
            if(route.valid()) for(size_t i=0;i<count_;++i) {
                if(entries_[i].route.compatible(route) && entries_[i].route.corroborated(route) && !entries_[i].info.ambiguous && !entries_[i].route_unstable) {
                    if(index!=Capacity) { entries_[index].info.ambiguous=true; entries_[i].info.ambiguous=true; route_collision=true; index=Capacity; break; }
                    index=i;
                }
            }
            if(index!=Capacity && entries_[index].info.last_seen_epoch==epoch && entries_[index].current_identity!=identity) {
                // The same route described two sources this epoch. Never let a
                // manual pin silently follow either of these sources.
                entries_[index].info.ambiguous=true;
                route_collision=true;
                index=Capacity;
            }
            if(index==Capacity) {
                if(!next_id_) {capacity_exhausted_=true;return 0;}
                if(count_<Capacity) index=count_++;
                else {
                    for(size_t i=0;i<count_;++i) {
                        const auto& info=entries_[i].info;
                        if(info.id==selected_id_||info.id==auto_id_||info.last_seen_epoch>=epoch) continue;
                        if(index==Capacity||info.last_seen_epoch<entries_[index].info.last_seen_epoch) index=i;
                    }
                    if(index==Capacity){capacity_exhausted_=true;return 0;}
                    erase_family(entries_[index].info.id);
                }
                entries_[index]={}; entries_[index].info.id=advance(next_id_); entries_[index].route=route; entries_[index].info.ambiguous=route_collision;
            }
            mi=MemberCapacity;
            for(size_t i=0;i<MemberCapacity;++i) if(!members_[i].identity){mi=i;break;}
            if(mi==MemberCapacity) {
                // Bounded LRU physical retention; current-epoch members remain
                // retained so pointer reuse cannot impersonate a live member.
                for(size_t i=0;i<MemberCapacity;++i) if(members_[i].seen<epoch &&
                    (mi==MemberCapacity||members_[i].seen<members_[mi].seen)) mi=i;
            }
            if(mi==MemberCapacity||!next_physical_){capacity_exhausted_=true;return 0;}
            members_[mi]={identity,entries_[index].info.id,advance(next_physical_),epoch};
        }
        auto& e=entries_[index];
        // Physical COM identity can be pooled/reused. An incompatible executed
        // route invalidates a manual family even when that identity is known.
        if(route.valid() && e.route.valid() && (!e.route.compatible(route) ||
            ((e.route.dsv_handle || e.route.resource_name_hash) && !e.route.corroborated(route)))) {
            e.route_unstable=true; e.info.ambiguous=true;
        }
        if(e.info.last_seen_epoch==epoch&&e.current_identity&&e.current_identity!=identity) e.info.ambiguous=true;
        e.current_identity=identity;
        e.sequence=sequence?sequence:++observation_sequence_;
        e.area=route.valid()?double(route.width)*route.height:double(width)*height;
        e.info.width=width;e.info.height=height;e.info.format=format;e.info.last_seen_epoch=epoch;
        e.info.resource_name_hash=route.resource_name_hash;
        e.info.route_confidence=route.resource_name_hash?2:(route.dsv_handle?1:0);
        e.info.physical_id=members_[mi].physical; members_[mi].seen=epoch;
        return e.info.id;
    }
    bool select(uint64_t id){if(id&&find_id(id)==Capacity)return false;selected_id_=id;return true;}
    uint64_t selected() const{return selected_id_;}
    uint64_t automatic() const{return auto_id_;}
    bool knows(uint64_t id) const{return id&&find_id(id)!=Capacity;}
    uint64_t id_for_identity(uint64_t identity) const {const auto i=find_identity(identity);return i==MemberCapacity?0:members_[i].family;}
    uint64_t physical_id_for_identity(uint64_t identity) const {const auto i=find_identity(identity);return i==MemberCapacity?0:members_[i].physical;}
    // Unknown resources must reach execution to establish a rotating member's
    // route. Known unrelated members can be filtered before allocating copies.
    bool permits_record(uint64_t identity) const { const auto id=id_for_identity(identity);return !selected_id_||!id||id==selected_id_; }
    // Finalize once per acquire epoch, after every submitted slot was observed.
    // This chooses metadata only; callers must still enforce fresh-slot fences.
    void choose_auto(uint64_t epoch) {
        if(!epoch||epoch==finalized_epoch_)return;
        const bool consecutive=finalized_epoch_+1==epoch;
        finalized_epoch_=epoch;
        size_t best=Capacity;
        for(size_t i=0;i<count_;++i) {const auto& a=entries_[i].info;
            if(a.last_seen_epoch!=epoch||a.ambiguous)continue;
            if(best==Capacity||entries_[i].area>entries_[best].area||
                (entries_[i].area==entries_[best].area&&entries_[i].sequence>entries_[best].sequence))best=i;
        }
        const auto current=find_id(auto_id_);
        const bool fresh=current!=Capacity&&entries_[current].info.last_seen_epoch==epoch&&!entries_[current].info.ambiguous;
        absent_streak_=fresh?0:(consecutive?absent_streak_+1:1);
        uint64_t next=auto_id_; const char* reason=nullptr;
        if(!auto_id_&&best!=Capacity){next=entries_[best].info.id;reason="initial";}
        else if(!fresh&&absent_streak_>=3&&best!=Capacity){next=entries_[best].info.id;reason="selected absent 3 epochs";}
        // Size is not evidence of a better camera. A fresh persistent choice
        // changes only when it becomes absent/invalid, or the user selects it.
        if(next!=auto_id_){auto_id_=next;++switches_;switch_reason_=reason;stable_epochs_=0;}
        else stable_epochs_=fresh?(consecutive?stable_epochs_+1:1):0;
        const auto chosen=find_id(auto_id_);
        auto_fallback_=chosen==Capacity||entries_[chosen].info.last_seen_epoch!=epoch||entries_[chosen].info.ambiguous;
        if(auto_fallback_) switch_reason_="fresh physical fallback: family absent or ambiguous";
    }
    bool accepts_slot(uint64_t id) const {
        const auto i=find_id(id);if(i==Capacity)return false;
        if(selected_id_)return id==selected_id_&&!entries_[i].info.ambiguous;
        return auto_fallback_||(!entries_[i].info.ambiguous&&(!auto_id_||id==auto_id_));
    }
    bool capacity_exhausted() const{return capacity_exhausted_;}
    uint64_t switch_count()const{return switches_;}
    uint64_t stable_epochs()const{return stable_epochs_;}
    const char* switch_reason()const{return switch_reason_;}
    std::vector<CandidateInfo> candidates()const {
        std::vector<CandidateInfo> result;result.reserve(count_);
        for(size_t i=0;i<count_;++i){auto info=entries_[i].info;
            for(const auto& m:members_)if(m.identity&&m.family==info.id)++info.members;
            info.selected_auto=info.id==auto_id_;result.push_back(info);}
        return result;
    }
    void reset(){entries_={};members_={};count_=0;selected_id_=auto_id_=finalized_epoch_=0;
        absent_streak_=switches_=stable_epochs_=0;switch_reason_="reset";capacity_exhausted_=false;auto_fallback_=false;observation_sequence_=0;}
};
} // namespace stock_dibr
