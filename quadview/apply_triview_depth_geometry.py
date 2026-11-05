#!/usr/bin/env python3
"""Freeze physical eye translations and context depth projection before composition."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
p=root/'src/mods/VR.cpp'
s=p.read_text()
anchor='            // Tri-view B6: use compact per-role targets for this draw only when a\n'
assert s.count(anchor)==1
code="""            // B10: exact eye origins in the rendered left-optical context basis.
            if (candidate->shared_context && pose && pose->stage_views.size()==2 && draw_config.base_projection_valid) {
                const auto& q=pose->stage_views[0].pose.orientation;
                const double x=q.x,y=q.y,z=q.z,w=q.w;
                const double norm=x*x+y*y+z*z+w*w;
                const double units=get_world_to_meters();
                if (std::isfinite(norm) && std::abs(norm-1.)<1.e-3 && std::isfinite(units) && units>0.) {
                    const double r[3][3]{{1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)},
                        {2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)},
                        {2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)}};
                    const auto& l=pose->stage_views[0].pose.position;
                    const auto& rr=pose->stage_views[1].pose.position;
                    const double center[3]{(l.x+rr.x)*.5,(l.y+rr.y)*.5,(l.z+rr.z)*.5};
                    std::array<std::array<double,3>,2> origins{};
                    for (size_t eye=0;eye<2;++eye) {
                        const auto& t=pose->stage_views[eye].pose.position;
                        const double delta[3]{t.x-center[0],t.y-center[1],t.z-center[2]};
                        for(size_t axis=0;axis<3;++axis) for(size_t j=0;j<3;++j)
                            origins[eye][axis]+=r[j][axis]*delta[j]*units*(axis==2 ? -1. : 1.);
                    }
                    std::array<double,16> context{};
                    for(size_t i=0;i<16;++i) context[i]=draw_config.projections[0][i];
                    context[0]=candidate->context_projection[0];context[8]=candidate->context_projection[1];
                    context[5]=candidate->context_projection[2];context[9]=candidate->context_projection[3];
                    (void)uevr::quadview::configure_depth_geometry(*candidate,context,origins,double(m_quadview_depth_strength->value()));
                }
            }
"""
p.write_text(s.replace(anchor,code+anchor))
print('Frozen physical per-eye context reprojection geometry')
