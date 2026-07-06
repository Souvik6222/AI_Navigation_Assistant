#pragma once
#include "types.hpp"
#include <opencv2/core.hpp>
#include <onnxruntime_cxx_api.h>
#include <memory>
#include <deque>

class DepthEstimator {
public:
    explicit DepthEstimator(const Config& config);
    ~DepthEstimator() = default;

    cv::Mat estimate(const cv::Mat& frame);
    float get_distance(const cv::Mat& depth_map, const BBox& bbox);

private:
    void update_reference_range(const cv::Mat& raw_depth);
    cv::Mat normalise_depth(const cv::Mat& raw_depth);
    float calibrate(float depth_value) const;
    float calibrate_region(const cv::Mat& depth_map, const BBox& bbox) const;

    int smoothing_frames_;
    float scale_, offset_, min_dist_, max_dist_;

    Ort::Env env_{nullptr};
    Ort::Session session_{nullptr};
    Ort::MemoryInfo memory_info_{nullptr};

    // Own the allocated strings so the const char* pointers remain valid
    std::vector<Ort::AllocatedStringPtr> input_names_ptrs_;
    std::vector<Ort::AllocatedStringPtr> output_names_ptrs_;
    std::vector<const char*> input_names_;
    std::vector<const char*> output_names_;

    std::deque<cv::Mat> depth_buffer_;
    std::deque<std::pair<float, float>> ref_history_;
    float global_ref_min_ = 0.0f;
    float global_ref_max_ = 1.0f;
    bool ref_initialized_ = false;
};
