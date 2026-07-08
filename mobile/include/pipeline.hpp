#pragma once
#include "types.hpp"
#include "detector.hpp"
#include "depth_estimator.hpp"
#include "tracker.hpp"
#include "decision_engine.hpp"
#include "llm_client.hpp"
#include <memory>
#include <atomic>
#include <functional>
#include <cstdint>
#include <mutex>

#ifndef __ANDROID__
#include "camera.hpp"
#endif

class Pipeline {
public:
    explicit Pipeline(const Config& config);
    ~Pipeline();

    bool init();
    int run();
    void stop();
    void toggle_language();

    // Alert callback: called for each alert with (message, is_urgent)
    // On Android, this routes to JNI → Android TTS
    // On desktop, alerts are also printed to stdout
    using AlertCallback = std::function<void(const std::string&, bool)>;
    using VisualCallback = std::function<void(const std::vector<float>&)>;
    using DevLogCallback = std::function<void(const std::string&)>;

    void set_alert_callback(AlertCallback cb);
    void set_visual_callback(VisualCallback cb);
    void set_dev_log_callback(DevLogCallback cb);

#ifdef __ANDROID__
    // Android-only: called from JNI with each raw NV21 camera frame.
    // CameraX drives this; the Pipeline does NOT own a camera on Android.
    void push_frame(const uint8_t* data, int width, int height, int rotation = 0);
#endif

private:
    void process_frame(cv::Mat& frame, int frame_index);
    void handle_key(int key);
    void print_fps();

    Config config_;

    std::unique_ptr<ObjectDetector> detector_;
    std::unique_ptr<DepthEstimator> depth_estimator_;
    std::unique_ptr<ObjectTracker> tracker_;
    std::unique_ptr<DecisionEngine> decision_engine_;
    std::unique_ptr<LLMClient> llm_client_;

#ifndef __ANDROID__
    std::unique_ptr<CameraStream> camera_;
#endif

    std::vector<Detection> detections_;
    std::vector<TrackedObject> cached_tracked_objects_;
    cv::Mat cached_annotated_frame_;
    std::string language_ = "en";

    // FPS tracking
    int fps_counter_ = 0;
    double fps_start_time_ = 0.0;
    float current_fps_ = 0.0f;
    int frame_index_ = 0;   // for Android push_frame counter

    std::atomic<bool> running_{false};
    std::mutex frame_mutex_;  // guards push_frame() — NNAPI is not concurrent-safe

    // Callbacks
    AlertCallback alert_callback_;
    VisualCallback visual_callback_;
    DevLogCallback dev_log_callback_;
};
