#include "decision_engine.hpp"
#include "tracker.hpp"
#include <algorithm>
#include <cmath>

static const std::unordered_map<std::string, std::string> HINDI_LABELS = {
    {"person", "insaan"}, {"chair", "kursi"}, {"dining table", "mez"},
    {"table", "mez"}, {"car", "gaadi"}, {"bicycle", "cycle"},
    {"door", "darwaza"}, {"stairs", "seedhiyan"}, {"bench", "bench"},
    {"potted plant", "gamlaa"}, {"backpack", "bag"}, {"handbag", "bag"},
    {"suitcase", "suitcase"}, {"bottle", "bottle"}, {"cup", "cup"},
    {"laptop", "laptop"}, {"cell phone", "phone"}, {"book", "kitaab"},
    {"umbrella", "chhatri"}, {"dog", "kutta"}, {"cat", "billi"},
    {"bus", "bus"}, {"truck", "truck"}, {"motorcycle", "motorcycle"},
    {"fire hydrant", "hydrant"}, {"stop sign", "stop sign"},
    {"couch", "sofa"}, {"bed", "bistar"}, {"toilet", "toilet"},
    {"tv", "TV"}, {"wall", "diwaar"},
};

static const std::unordered_map<std::string, std::string> EN_DIRS = {
    {"LEFT", "on your left"}, {"CENTER", "ahead"}, {"RIGHT", "on your right"},
};

static const std::unordered_map<std::string, std::string> HI_DIRS = {
    {"LEFT", "baayi taraf"}, {"CENTER", "aage"}, {"RIGHT", "daayi taraf"},
};

DecisionEngine::DecisionEngine(const Config& config)
    : urgent_threshold_(config.urgent_threshold)
    , warning_threshold_(config.warning_threshold)
    , info_threshold_(config.info_threshold)
    , max_alerts_(config.max_alerts)
    , consecutive_frames_(config.consecutive_frames_required)
    , distance_variance_threshold_(config.distance_variance_threshold)
    , path_clear_interval_(config.path_clear_interval_seconds)
{
    dynamic_labels_ = {"person", "car", "bicycle", "dog", "bus", "truck", "motorcycle"};
}

void DecisionEngine::set_tracker(ObjectTracker* tracker) {
    tracker_ = tracker;
}

std::vector<Alert> DecisionEngine::evaluate(const std::vector<TrackedObject>& objects) {
    std::vector<Alert*> candidates;

    for (const auto& obj : objects) {
        if (!obj.should_announce) continue;
        if (obj.tracked_frames < consecutive_frames_) continue;

        if (tracker_) {
            float var = tracker_->get_distance_variance(obj.track_id);
            if (var > distance_variance_threshold_) continue;
        }

        Alert* alert = create_alert(obj);
        if (alert) candidates.push_back(alert);
    }

    Alert* path_alert = check_path_clear(objects);
    if (path_alert) candidates.push_back(path_alert);

    // Sort by priority (higher = more urgent)
    std::sort(candidates.begin(), candidates.end(),
              [](const Alert* a, const Alert* b) {
                  return a->priority_score > b->priority_score;
              });

    std::vector<Alert> result;
    for (int i = 0; i < std::min(max_alerts_, (int)candidates.size()); ++i) {
        result.push_back(*candidates[i]);
        delete candidates[i];
    }
    for (int i = max_alerts_; i < (int)candidates.size(); ++i)
        delete candidates[i];

    return result;
}

Alert* DecisionEngine::check_path_clear(const std::vector<TrackedObject>& objects) {
    double now = (double)cv::getTickCount() / cv::getTickFrequency();
    if (now - last_path_clear_time_ < path_clear_interval_) return nullptr;

    bool center_blocked = false;
    std::unordered_set<std::string> sides;

    for (const auto& obj : objects) {
        float d = obj.distance_m;
        if (d < 0 || d > info_threshold_) continue;
        if (obj.direction == "CENTER") { center_blocked = true; break; }
        if (obj.direction == "LEFT" || obj.direction == "RIGHT")
            sides.insert(obj.direction);
    }

    if (center_blocked) return nullptr;
    last_path_clear_time_ = now;

    auto* alert = new Alert();
    alert->level = "path_clear";
    alert->priority_score = 0.5f;

    if (!sides.empty()) {
        std::string sides_str;
        for (auto it = sides.begin(); it != sides.end(); ++it) {
            if (it != sides.begin()) sides_str += " and ";
            std::string s = *it;
            std::transform(s.begin(), s.end(), s.begin(), ::tolower);
            sides_str += s;
        }
        alert->message_en = "Path clear ahead, objects on your " + sides_str + ".";
        alert->message_hi = "Aage rasta saaf hai, " + sides_str + " mein cheezein hain.";
    } else {
        alert->message_en = "Path is clear ahead.";
        alert->message_hi = "Aage rasta saaf hai.";
    }

    return alert;
}

Alert* DecisionEngine::create_alert(const TrackedObject& obj) {
    float distance = obj.distance_m;
    if (distance < 0) distance = 999.0f;

    const auto& direction = obj.direction;
    const auto& label = obj.label;

    float priority = 10.0f / std::max(distance, 0.1f);
    if (direction == "CENTER") priority += 2.0f;
    if (dynamic_labels_.count(label)) priority += 0.5f;

    std::string motion = "STATIONARY";
    float velocity = 0.0f;
    if (tracker_) {
        motion = tracker_->get_motion_state(obj.track_id);
        velocity = tracker_->get_velocity(obj.track_id);
    }
    bool approaching = (motion == "APPROACHING");
    if (approaching) priority += 3.0f;

    auto* alert = new Alert();
    alert->track_id = obj.track_id;

    std::string en_dir = EN_DIRS.count(direction) ? EN_DIRS.at(direction) : "ahead";
    std::string hi_label = HINDI_LABELS.count(label) ? HINDI_LABELS.at(label) : label;
    std::string hi_dir = HI_DIRS.count(direction) ? HI_DIRS.at(direction) : "aage";
    std::string app_en = approaching ? ", approaching" : "";
    std::string app_hi = approaching ? ", aa raha hai" : "";

    auto cap = [](std::string s) -> std::string {
        if (s.empty()) return s;
        s[0] = (char)std::toupper(s[0]);
        return s;
    };

    if (distance < urgent_threshold_) {
        alert->level = "urgent";
        alert->message_en = cap(label) + " very close " + en_dir + app_en + ".";
        alert->message_hi = hi_label + " bahut paas " + hi_dir + app_hi + ".";
        priority += 20.0f;
    } else if (distance < warning_threshold_) {
        if (approaching && velocity < -0.3f) {
            alert->level = "urgent";
            alert->message_en = cap(label) + " approaching fast " + en_dir + "!";
            alert->message_hi = hi_label + " tez aa raha hai " + hi_dir + "!";
            priority += 15.0f;
        } else {
            alert->level = "warning";
            alert->message_en = cap(label) + " close " + en_dir + app_en + ".";
            alert->message_hi = hi_label + " paas " + hi_dir + app_hi + ".";
            priority += 5.0f;
        }
    } else if (distance < info_threshold_) {
        if (approaching) {
            alert->level = "warning";
            alert->message_en = cap(label) + " approaching " + en_dir + ".";
            alert->message_hi = hi_label + " aa raha hai " + hi_dir + ".";
            priority += 5.0f;
        } else {
            alert->level = "info";
            alert->message_en = cap(label) + " nearby " + en_dir + ".";
            alert->message_hi = hi_label + " nazdeek " + hi_dir + ".";
        }
    } else {
        delete alert;
        return nullptr;
    }

    alert->priority_score = priority;
    return alert;
}
