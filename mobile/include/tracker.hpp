#pragma once
#include "types.hpp"
#include <unordered_map>
#include <vector>
#include <deque>

struct TrackState {
    int tracked_frames = 0;
    int lost_frames = 0;
    double last_announced_time = 0.0;
    std::string last_zone;
    float last_distance = -1.0f;
    BBox bbox{};
    std::string label;
    float vel_x = 0.0f;
    float vel_y = 0.0f;
    double last_update_time = 0.0;
};

class ObjectTracker {
public:
    explicit ObjectTracker(const Config& config);

    std::vector<TrackedObject> update(
        const std::vector<Detection>& detections, int frame_width
    );

    float get_distance_variance(int track_id) const;
    float get_velocity(int track_id) const;
    std::string get_motion_state(int track_id) const;
    void reset();

private:
    BBox predict_bbox(const TrackState& state) const;
    bool should_announce(int track_id, const std::string& direction,
                         float distance, double current_time);
    static float compute_iou(const BBox& a, const BBox& b);

    float cooldown_seconds_;
    int min_tracked_frames_;
    int max_lost_frames_;
    float distance_change_threshold_;
    float iou_threshold_ = 0.2f;
    int frame_count_ = 0;
    int next_id_ = 1;

    std::unordered_map<int, TrackState> track_state_;
    std::unordered_map<int, std::deque<float>> distance_history_;
    std::unordered_map<int, std::deque<double>> time_history_;
};
