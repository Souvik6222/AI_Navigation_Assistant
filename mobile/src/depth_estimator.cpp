#include "depth_estimator.hpp"
#include <opencv2/dnn.hpp>
#ifdef __ANDROID__
#include <nnapi_provider_factory.h>
#endif
#include <opencv2/imgproc.hpp>
#include <numeric>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <thread>

static constexpr int REFERENCE_WINDOW = 30;

DepthEstimator::DepthEstimator(const Config& config)
    : smoothing_frames_(config.temporal_smoothing_frames)
    , scale_(config.depth_scale)
    , offset_(config.depth_offset)
    , min_dist_(config.min_distance)
    , max_dist_(config.max_distance)
{
    env_ = Ort::Env(OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING, "depth");
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(config.num_threads);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);

#ifdef __ANDROID__
    // NNAPI DISABLED: concurrent NNAPI sessions crash on Android 11 (libneuralnetworks CHECK).
    // Use 6 CPU threads — MiDaS-small-256 benefits from intra-op parallelism on A55+A76 cores.
    opts.SetIntraOpNumThreads(6);
    opts.SetInterOpNumThreads(1);
#endif

    session_ = Ort::Session(env_, config.midas_model_path.c_str(), opts);

    // Store AllocatedStringPtr to prevent dangling pointers
    Ort::AllocatorWithDefaultOptions alloc;
    auto input_name = session_.GetInputNameAllocated(0, alloc);
    input_names_.push_back(input_name.get());
    input_names_ptrs_.push_back(std::move(input_name));

    auto output_name = session_.GetOutputNameAllocated(0, alloc);
    output_names_.push_back(output_name.get());
    output_names_ptrs_.push_back(std::move(output_name));

    memory_info_ = Ort::MemoryInfo::CreateCpu(OrtAllocatorType::OrtArenaAllocator,
                                               OrtMemType::OrtMemTypeDefault);
}

cv::Mat DepthEstimator::estimate(const cv::Mat& frame) {
    // Convert BGR to RGB
    cv::Mat rgb;
    cv::cvtColor(frame, rgb, cv::COLOR_BGR2RGB);

    // Resize to 256x256 (MiDaS small input size)
    cv::Mat resized;
    cv::resize(rgb, resized, cv::Size(256, 256));

    // Normalize to [0,1] and CHW
    cv::Mat blob = cv::dnn::blobFromImage(resized, 1.0f / 255.0f);

    std::vector<int64_t> input_shape = {1, 3, 256, 256};
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory_info_, blob.ptr<float>(), blob.total(),
        input_shape.data(), input_shape.size()
    );

    auto outputs = session_.Run(
        Ort::RunOptions{nullptr},
        input_names_.data(), &input_tensor, 1,
        output_names_.data(), output_names_.size()
    );

    auto* raw_data = outputs[0].GetTensorMutableData<float>();
    auto output_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    int out_h = 256;
    int out_w = 256;
    if (output_shape.size() >= 4) {
        out_h = (int)output_shape[2];
        out_w = (int)output_shape[3];
    } else if (output_shape.size() == 3) {
        out_h = (int)output_shape[1];
        out_w = (int)output_shape[2];
    }

    cv::Mat raw_depth(out_h, out_w, CV_32F, raw_data);

    // Resize back to frame size
    cv::Mat resized_depth;
    cv::resize(raw_depth, resized_depth, frame.size());

    // Normalise
    cv::Mat depth_map = normalise_depth(resized_depth);

    // Temporal smoothing
    depth_buffer_.push_back(depth_map.clone());
    if ((int)depth_buffer_.size() > smoothing_frames_)
        depth_buffer_.pop_front();

    if (depth_buffer_.size() > 1) {
        cv::Mat smoothed = cv::Mat::zeros(frame.size(), CV_32F);
        for (const auto& d : depth_buffer_)
            smoothed += d;
        smoothed /= (float)depth_buffer_.size();
        return smoothed;
    }

    return depth_map;
}

void DepthEstimator::update_reference_range(const cv::Mat& raw_depth) {
    std::vector<float> flat;
    flat.assign(raw_depth.begin<float>(), raw_depth.end<float>());
    std::sort(flat.begin(), flat.end());

    auto p5_idx = (size_t)(flat.size() * 0.05);
    auto p95_idx = (size_t)(flat.size() * 0.95);
    float p5 = flat[std::min(p5_idx, flat.size() - 1)];
    float p95 = flat[std::min(p95_idx, flat.size() - 1)];

    if (p95 - p5 < 1e-3f) {
        float mid = (p5 + p95) / 2.0f;
        p5 = mid - 0.5f;
        p95 = mid + 0.5f;
    }

    ref_history_.push_back({p5, p95});
    if ((int)ref_history_.size() > REFERENCE_WINDOW)
        ref_history_.pop_front();

    // Median
    std::vector<float> all_p5, all_p95;
    for (const auto& [lo, hi] : ref_history_) {
        all_p5.push_back(lo);
        all_p95.push_back(hi);
    }
    std::sort(all_p5.begin(), all_p5.end());
    std::sort(all_p95.begin(), all_p95.end());
    size_t mid = all_p5.size() / 2;
    global_ref_min_ = all_p5[mid];
    global_ref_max_ = all_p95[mid];
    ref_initialized_ = true;
}

cv::Mat DepthEstimator::normalise_depth(const cv::Mat& raw_depth) {
    update_reference_range(raw_depth);

    cv::Mat normalised;
    if (!ref_initialized_ || global_ref_max_ - global_ref_min_ < 1e-6f) {
        double dmin, dmax;
        cv::minMaxLoc(raw_depth, &dmin, &dmax);
        if (dmax - dmin > 0)
            cv::subtract(raw_depth, cv::Scalar(dmin), normalised);
        else
            return cv::Mat::zeros(raw_depth.size(), CV_32F);
        normalised /= (float)(dmax - dmin);
        return normalised;
    }

    cv::subtract(raw_depth, cv::Scalar(global_ref_min_), normalised);
    normalised /= (global_ref_max_ - global_ref_min_);
    cv::max(normalised, 0.0f, normalised);
    cv::min(normalised, 1.0f, normalised);
    return normalised;
}

float DepthEstimator::calibrate(float depth_value) const {
    if (depth_value <= 0.001f) return max_dist_;
    float dist = scale_ / (depth_value + offset_);
    return std::clamp(dist, min_dist_, max_dist_);
}

float DepthEstimator::calibrate_region(const cv::Mat& depth_map, const BBox& bbox) const {
    auto [x1, y1, x2, y2] = bbox;
    int ix1 = std::max(0, std::min((int)x1, depth_map.cols - 1));
    int ix2 = std::max(0, std::min((int)x2, depth_map.cols - 1));
    int iy1 = std::max(0, std::min((int)y1, depth_map.rows - 1));
    int iy2 = std::max(0, std::min((int)y2, depth_map.rows - 1));

    if (ix2 <= ix1 || iy2 <= iy1) return max_dist_;

    int cx = (ix1 + ix2) / 2;
    int cy = (iy1 + iy2) / 2;
    int bw = ix2 - ix1;
    int bh = iy2 - iy1;
    int mx = std::max(1, (int)(bw * 0.1f));
    int my = std::max(1, (int)(bh * 0.1f));

    cv::Rect region(
        std::max(0, cx - mx), std::max(0, cy - my),
        std::min(cx + mx, depth_map.cols - 1) - std::max(0, cx - mx),
        std::min(cy + my, depth_map.rows - 1) - std::max(0, cy - my)
    );

    if (region.width <= 0 || region.height <= 0) {
        return calibrate(depth_map.at<float>(cy, cx));
    }

    cv::Mat roi = depth_map(region);
    cv::Scalar mean, stddev;
    cv::meanStdDev(roi, mean, stddev);
    return calibrate((float)mean[0]);
}

float DepthEstimator::get_distance(const cv::Mat& depth_map, const BBox& bbox) {
    return calibrate_region(depth_map, bbox);
}
