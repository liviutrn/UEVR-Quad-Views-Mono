#include "DuoViewNgxRhiTicket.hpp"
#include <cassert>
#include <thread>

using namespace uevr::duoview;
using namespace uevr::duoview::ngx;

int main() {
    assert(current_rhi_producer_key == FrameKey{});
    {
        ScopedRhiProducerKey first{FrameKey{7,41}};
        assert((current_rhi_producer_key == FrameKey{7,41}));
        {
            ScopedRhiProducerKey second{FrameKey{7,42}};
            assert((current_rhi_producer_key == FrameKey{7,42}));
        }
        assert((current_rhi_producer_key == FrameKey{7,41}));
        std::thread other([] {
            assert(current_rhi_producer_key == FrameKey{});
            ScopedRhiProducerKey isolated{FrameKey{8,55}};
            assert((current_rhi_producer_key == FrameKey{8,55}));
        });
        other.join();
        assert((current_rhi_producer_key == FrameKey{7,41}));
    }
    assert(current_rhi_producer_key == FrameKey{});
}
