#include "DuoViewFineDepthHistory.hpp"

#include <cmath>
#include <stdexcept>

using namespace uevr::duoview::stereo;

void close(float actual, float expected) {
    if (std::abs(actual-expected)>1.e-5f) throw std::runtime_error("Fine depth reprojection mismatch");
}

int main() {
    FineDepthCamera previous{{1.5f,.1f,1.2f,-.15f},{0,0,0,1},{0,0,0},100};
    auto current=previous;
    auto identity=fine_depth_reprojection(current,previous);
    for (unsigned row=0;row<3;++row) {
        for (unsigned col=0;col<3;++col) close(identity.rows[row][col],row==col ? 1.f : 0.f);
        close(identity.rows[row][3],0);
    }
    if (identity.previous_projection!=previous.projection) return 1;

    current.position={.03f,-.02f,-.1f};
    const auto translated=fine_depth_reprojection(current,previous);
    close(translated.rows[0][3],3);
    close(translated.rows[1][3],-2);
    close(translated.rows[2][3],10);

    current.position={};
    const float yaw=.2f;
    current.orientation={0,std::sin(yaw/2),0,std::cos(yaw/2)};
    const auto rotated=fine_depth_reprojection(current,previous);
    close(rotated.rows[0][2],-std::sin(yaw));  // -Z OpenXR forward converted to +Z
    close(rotated.rows[2][2],std::cos(yaw));
    close(rotated.rows[2][0],std::sin(yaw));

    previous.orientation=current.orientation;
    const auto same_pose=fine_depth_reprojection(current,previous);
    for (unsigned row=0;row<3;++row)
        for (unsigned col=0;col<3;++col) close(same_pose.rows[row][col],row==col ? 1.f : 0.f);
}
