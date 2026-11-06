#include "TriViewAdmission.hpp"
#include <cassert>
#include <stdexcept>
using namespace uevr::quadview;
int main() {
    int32_t views=4;
    { BootstrapViewCount warmup(views); assert(views==1); }
    assert(views==4);
    try { BootstrapViewCount warmup(views); assert(views==1); throw std::runtime_error("allocation rejected"); }
    catch (const std::runtime_error&) {}
    assert(views==4);
    views=2; { BootstrapViewCount original_bootstrap(views); assert(views==2); }
    assert(views==2);
    assert(!native_triview_publishable(true,false,0));
    assert(!native_triview_publishable(true,false,1));
    assert(!native_triview_publishable(false,true,1));
    assert(!native_triview_publishable(true,true,0));
    assert(native_triview_publishable(true,true,19));
}
