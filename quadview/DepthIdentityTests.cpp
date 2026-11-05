#include "QuadViewDepthIdentity.hpp"
#include <stdexcept>
#include <thread>
using namespace uevr::quadview::ngx;
void check(bool ok) { if(!ok) throw std::runtime_error("Depth identity/lifetime contract"); }
int main() {
    DepthOwner owner; owner.generation=2;owner.serial=7;owner.target_set=3;owner.engine_frame=4;
    owner.role=0;owner.output_width=400;owner.output_height=300;owner.unambiguous=true;owner.ngx_input_state_known=true;
    check(owner.valid());
    { DepthOwnerScope scope(owner);check(*DepthOwnerScope::current()==owner);
      auto ambiguous=owner;ambiguous.unambiguous=false;
      {DepthOwnerScope inner(ambiguous);check(!DepthOwnerScope::current());}
      check(*DepthOwnerScope::current()==owner);
      std::thread other([] {check(!DepthOwnerScope::current());});other.join(); }
    check(!DepthOwnerScope::current());
    auto stale=owner;stale.serial++;check(!(owner==stale));stale=owner;stale.target_set++;check(!(owner==stale));
    check(!depth_slot_reusable(true,false,100,0,1)); // even after arbitrary time
    check(!depth_slot_reusable(false,true,9,10,1));
    check(!depth_slot_reusable(false,true,~uint64_t{},10,1));
    check(!depth_slot_reusable(false,true,10,10,2)); // compositor lease
    check(depth_slot_reusable(false,true,10,10,1));
}
