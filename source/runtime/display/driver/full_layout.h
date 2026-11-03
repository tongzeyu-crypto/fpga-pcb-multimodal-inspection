#ifndef HDMI_FULL_LAYOUT_H
#define HDMI_FULL_LAYOUT_H
static constexpr int FULL_LEFT = 160;
static constexpr int FULL_RIGHT = 1048;
static constexpr int FULL_WIDTH = FULL_RIGHT - FULL_LEFT;
static constexpr int FULL_PROJECTION_X = 640 - (FULL_LEFT + FULL_RIGHT) / 2;
#endif
