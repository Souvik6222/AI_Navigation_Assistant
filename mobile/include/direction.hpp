#pragma once
#include <string>

std::string get_direction(float center_x, int frame_width,
                          float left_boundary = 0.33f,
                          float right_boundary = 0.66f);
