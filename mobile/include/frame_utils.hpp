#pragma once
#include "types.hpp"
#include <opencv2/core.hpp>
#include <vector>
#include <string>

cv::Mat resize_frame(const cv::Mat& frame, int width, int height);
cv::Mat annotate_frame(const cv::Mat& frame, const std::vector<TrackedObject>& objects);
cv::Mat draw_status_bar(const cv::Mat& frame, const std::string& language,
                        float fps, int num_objects);
std::string frame_to_base64(const cv::Mat& frame);
