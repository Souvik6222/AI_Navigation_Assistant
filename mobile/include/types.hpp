#pragma once
#include <string>
#include <vector>
#include <tuple>
#include <cstdint>

using BBox = std::tuple<float, float, float, float>; // x1, y1, x2, y2

struct Detection {
    std::string label;
    float confidence = 0.0f;
    BBox bbox{};
    float center_x = 0.0f;
    float center_y = 0.0f;
    float area = 0.0f;
    int class_id = -1;
    float distance_m = -1.0f;
    std::string direction = "CENTER";
};

struct TrackedObject : Detection {
    int track_id = -1;
    int tracked_frames = 0;
    bool should_announce = false;
    std::string alert_level = "silent";
};

struct Alert {
    std::string level;
    std::string message_en;
    std::string message_hi;
    int track_id = -1;
    float priority_score = 0.0f;
};

struct Config {
    // Performance
    int process_every_n_frames = 3;

    // Camera
    int cam_index = 0;
    int frame_width = 320;
    int frame_height = 240;
    int frame_rotation = 0;

    // Detection
    std::string yolo_model_path = "models/yolov8n.onnx";
    float confidence_threshold = 0.55f;
    float min_bbox_area_ratio = 0.01f;

    // Depth
    std::string midas_model_path = "models/midas_v21_small_256.onnx";
    int temporal_smoothing_frames = 3;
    float depth_scale = 2.0f;
    float depth_offset = 0.2f;
    float min_distance = 0.3f;
    float max_distance = 6.0f;

    // Tracking
    float alert_cooldown_seconds = 7.0f;
    int min_tracked_frames = 3;
    int max_lost_frames = 150;
    float distance_change_threshold = 0.50f;

    // Direction
    float left_boundary = 0.33f;
    float right_boundary = 0.66f;

    // Decision
    float urgent_threshold = 2.0f;
    float warning_threshold = 4.0f;
    float info_threshold = 6.0f;
    int max_alerts = 2;
    int consecutive_frames_required = 3;
    float distance_variance_threshold = 0.20f;
    float path_clear_interval_seconds = 15.0f;

    // Display
    bool show_window = true;
};

enum class AlertLevel { SILENT, INFO, WARNING, URGENT, PATH_CLEAR };
