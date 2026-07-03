#pragma once
#include "types.hpp"
#include "detector.hpp"
#include "depth_estimator.hpp"
#include "tracker.hpp"
#include "decision_engine.hpp"
#include "camera.hpp"
#include <memory>

class Pipeline {
public:
    explicit Pipeline(const Config& config);
    ~Pipeline();

    bool init();
    int run();

private:
    void process_frame(cv::Mat& frame, int frame_index);
    void handle_key(int key);
    void print_fps();

    Config config_;

    std::unique_ptr<ObjectDetector> detector_;
    std::unique_ptr<DepthEstimator> depth_estimator_;
    std::unique_ptr<ObjectTracker> tracker_;
    std::unique_ptr<DecisionEngine> decision_engine_;
    std::unique_ptr<CameraStream> camera_;

    std::vector<Detection> detections_;
    std::vector<TrackedObject> cached_tracked_objects_;
    cv::Mat cached_annotated_frame_;
    std::string language_ = "en";

    // FPS tracking
    int fps_counter_ = 0;
    double fps_start_time_ = 0.0;
    float current_fps_ = 0.0f;

    bool running_ = false;
};
