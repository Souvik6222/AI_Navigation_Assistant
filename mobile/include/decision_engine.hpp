#pragma once
#include "types.hpp"
#include <vector>
#include <string>
#include <unordered_set>

class ObjectTracker;

class DecisionEngine {
public:
    explicit DecisionEngine(const Config& config);

    void set_tracker(ObjectTracker* tracker);
    std::vector<Alert> evaluate(const std::vector<TrackedObject>& objects);

private:
    Alert* check_path_clear(const std::vector<TrackedObject>& objects);
    Alert* create_alert(const TrackedObject& obj);

    float urgent_threshold_, warning_threshold_, info_threshold_;
    int max_alerts_;
    int consecutive_frames_;
    float distance_variance_threshold_;
    std::unordered_set<std::string> dynamic_labels_;
    float path_clear_interval_;
    double last_path_clear_time_ = 0.0;

    ObjectTracker* tracker_ = nullptr;

    static std::string label_hi(const std::string& en);
    static std::string dir_en(const std::string& dir);
    static std::string dir_hi(const std::string& dir);
};
