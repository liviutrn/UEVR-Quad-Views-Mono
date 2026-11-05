#include "QuadViewStatusPanel.hpp"
#include "imgui_internal.h"
#include <cmath>
#include <stdexcept>
#include <string>
using namespace uevr::quadview;
void check(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
int main() {
    ImGui::CreateContext();
    auto& io=ImGui::GetIO();
    io.DisplaySize=ImVec2(1024,768); io.DeltaTime=1.f/60.f; io.IniFilename=nullptr;
    unsigned char* pixels; int width,height;
    io.Fonts->GetTexDataAsRGBA32(&pixels,&width,&height);
    ImVec2 control_min{},control_max{},hit{};
    float slider=0.f;
    for (unsigned frame=0;frame<60;++frame) {
        io.MousePos=frame ? hit : ImVec2(-100,-100);
        io.MouseDown[0]=frame>0 && (frame%2)==1;
        ImGui::NewFrame();
        ImGui::SetNextWindowPos(ImVec2(0,0));
        ImGui::SetNextWindowSize(ImVec2(480,600));
        ImGui::Begin("Production status panel test",nullptr,ImGuiWindowFlags_NoSavedSettings);
        draw_status_panel(static_cast<DisplayState>(frame%6),frame%2,[&] {
            if (frame%2) {
                const std::string long_status(900,'W');
                ImGui::TextWrapped("Unavailable: %s",long_status.c_str());
                ImGui::TextWrapped("Latest pipeline detail: %s",long_status.c_str());
                ImGui::Text("Video memory: %u MB / %u MB",frame*200,10000u);
                ImGui::TextWrapped("Source textures: varying dimensions and a lengthy description of all four resources");
            } else ImGui::TextUnformatted("Ready");
        });
        ImGui::SliderFloat("Focus width / eye FOV",&slider,0.f,1.f);
        const auto bounds=ImGui::GetCurrentContext()->LastItemData.Rect;
        if (!frame) {
            control_min=bounds.Min; control_max=bounds.Max;
            hit=ImVec2(bounds.Min.x+60.f,(bounds.Min.y+bounds.Max.y)*.5f);
        } else {
            check(bounds.Min.x==control_min.x && bounds.Min.y==control_min.y &&
                bounds.Max.x==control_max.x && bounds.Max.y==control_max.y,"Slider bounds moved with diagnostics");
            check(ImGui::IsItemHovered(),"Stable slider hit point became obscured");
            if (io.MouseDown[0]) check(ImGui::IsItemActive(),"Click missed the slider");
        }
        ImGui::End();
        ImGui::Render();
    }
    check(slider>0.f,"Slider never received a real mouse interaction");
    ImGui::DestroyContext();
}
