#include "direction.hpp"

std::string get_direction(float center_x, int frame_width,
                          float left_boundary, float right_boundary)
{
    if (frame_width <= 0) return "CENTER";

    float rel_x = center_x / (float)frame_width;
    if (rel_x < left_boundary)  return "LEFT";
    if (rel_x > right_boundary) return "RIGHT";
    return "CENTER";
}
