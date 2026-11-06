#include "QuadViewStatusPanel.hpp"
#include "imgui_internal.h"
#include <cstdio>
#include <stdexcept>
void run(bool b17) {
 ImGui::CreateContext(); auto& io=ImGui::GetIO();io.DisplaySize={1024,768};io.DeltaTime=1.f/60;io.IniFilename=nullptr;io.ConfigInputTrickleEventQueue=false;
 unsigned char* data;int w,h;io.Fonts->GetTexDataAsRGBA32(&data,&w,&h);
 ImVec2 hover{70,90};ImGuiWindow *parent{},*child{};
 for(int f=0;f<9;f++) {
  io.AddMousePosEvent(hover.x,hover.y);if(f==5)io.AddMouseWheelEvent(0,-1);
  ImGui::NewFrame();ImGui::SetNextWindowPos({0,0});ImGui::SetNextWindowSize({600,600});
  ImGui::Begin("UEVR",nullptr,ImGuiWindowFlags_NoSavedSettings);
  ImGui::BeginChild("UEVRRightPane",{500,480},false,ImGuiWindowFlags_AlwaysUseWindowPadding);parent=ImGui::GetCurrentWindow();
  auto details=[&]{child=ImGui::GetCurrentWindow();if(f<5)hover={child->InnerRect.Min.x+20,child->InnerRect.Min.y+15};for(int i=0;i<40;i++)ImGui::Text("Diagnostic row %d",i);};
  if(b17)uevr::quadview::draw_status_panel(uevr::quadview::DisplayState::active,true,details);
  else {ImGui::Text("TriView status: active");if(ImGui::BeginChild("##QuadViewStatusDetails",{0,ImGui::GetTextLineHeightWithSpacing()*7},true))details();ImGui::EndChild();}
  for(int i=0;i<80;i++)ImGui::Text("Control row %d",i);
  ImGui::EndChild();ImGui::End();ImGui::Render();
 }
 printf("%s parent_scroll=%.0f child_scroll=%.0f child_scrollbar=%d\n",b17?"B17":"B15",parent->Scroll.y,child->Scroll.y,child->ScrollbarY);
 bool ok=b17?(parent->Scroll.y>0 && child->Scroll.y==0):(parent->Scroll.y==0 && child->Scroll.y>0);
 ImGui::DestroyContext();if(!ok)throw std::runtime_error("Wheel target regression");
}
int main(){run(false);run(true);}
