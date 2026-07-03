#pragma once
#include "types.hpp"
#include <opencv2/core.hpp>
#include <onnxruntime_cxx_api.h>
#include <memory>
#include <vector>
#include <string>

class ObjectDetector {
public:
    explicit ObjectDetector(const Config& config);
    ~ObjectDetector() = default;

    std::vector<Detection> detect(const cv::Mat& frame);

private:
    std::vector<Detection> postprocess(
        const cv::Mat& frame,
        const std::vector<Ort::Value>& outputs,
        float frame_area, float min_area
    );

    float confidence_threshold_;
    float min_bbox_area_ratio_;
    float iou_threshold_ = 0.5f;

    Ort::Env env_{nullptr};
    Ort::Session session_{nullptr};
    Ort::MemoryInfo memory_info_{nullptr};
    std::vector<const char*> input_names_;
    std::vector<const char*> output_names_;
    int input_h_ = 640;
    int input_w_ = 640;
};
