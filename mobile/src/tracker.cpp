#include "tracker.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_set>
#include <opencv2/core.hpp>

ObjectTracker::ObjectTracker(const Config& config)
    : cooldown_seconds_(config.alert_cooldown_seconds)
    , min_tracked_frames_(config.min_tracked_frames)
    , max_lost_frames_(config.max_lost_frames)
    , distance_change_threshold_(config.distance_change_threshold)
{
}

std::vector<TrackedObject> ObjectTracker::update(
    const std::vector<Detection>& detections, int frame_width)
{
    frame_count_++;
    double current_time = (double)cv::getTickCount() / cv::getTickFrequency();

    // Collect active track IDs
    std::vector<int> active_ids;
    for (auto& [tid, state] : track_state_) {
        if (state.lost_frames < max_lost_frames_)
            active_ids.push_back(tid);
    }

    // Hungarian assignment
    std::unordered_map<int, int> det_to_track; // det index -> track_id
    std::unordered_set<int> matched_ids;

    if (!detections.empty() && !active_ids.empty()) {
        int n_det = (int)detections.size();
        int n_trk = (int)active_ids.size();

        // Cost matrix (IoU distance)
        std::vector<std::vector<float>> cost(n_det, std::vector<float>(n_trk, 1.0f));

        for (int di = 0; di < n_det; ++di) {
            for (int ti = 0; ti < n_trk; ++ti) {
                auto& state = track_state_[active_ids[ti]];
                BBox pred = predict_bbox(state);
                cost[di][ti] = 1.0f - compute_iou(detections[di].bbox, pred);
            }
        }

        // Greedy matching (simpler than full Hungarian for embedded)
        std::vector<bool> det_used(n_det, false);
        std::vector<bool> trk_used(n_trk, false);

        for (int iter = 0; iter < std::min(n_det, n_trk); ++iter) {
            float best_cost = std::numeric_limits<float>::max();
            int best_di = -1, best_ti = -1;

            for (int di = 0; di < n_det; ++di) {
                if (det_used[di]) continue;
                for (int ti = 0; ti < n_trk; ++ti) {
                    if (trk_used[ti]) continue;
                    if (cost[di][ti] < best_cost) {
                        best_cost = cost[di][ti];
                        best_di = di;
                        best_ti = ti;
                    }
                }
            }

            if (best_di < 0 || best_ti < 0) break;
            float iou = 1.0f - best_cost;
            if (iou < iou_threshold_) break;

            int track_id = active_ids[best_ti];
            det_to_track[best_di] = track_id;
            matched_ids.insert(track_id);
            det_used[best_di] = true;
            trk_used[best_ti] = true;

            // Update state
            auto& state = track_state_[track_id];
            const auto& det = detections[best_di];
            float dt = (float)(current_time - state.last_update_time);

            if (dt > 0.001f) {
                auto [ox1, oy1, ox2, oy2] = state.bbox;
                float ocx = (ox1 + ox2) / 2.0f;
                float ocy = (oy1 + oy2) / 2.0f;
                float inst_vel_x = (det.center_x - ocx) / dt;
                float inst_vel_y = (det.center_y - ocy) / dt;
                
                // Exponential Moving Average (EMA) for smoother velocity
                const float alpha = 0.3f;
                if (state.tracked_frames == 0) {
                    state.vel_x = inst_vel_x;
                    state.vel_y = inst_vel_y;
                } else {
                    state.vel_x = alpha * inst_vel_x + (1.0f - alpha) * state.vel_x;
                    state.vel_y = alpha * inst_vel_y + (1.0f - alpha) * state.vel_y;
                }
            }

            state.tracked_frames++;
            state.lost_frames = 0;
            state.bbox = det.bbox;
            state.label = det.label;
            state.last_update_time = current_time;
        }
    }

    // New tracks for unmatched detections
    for (int di = 0; di < (int)detections.size(); ++di) {
        if (det_to_track.count(di)) continue;

        int tid = next_id_++;
        track_state_[tid] = TrackState();
        auto& state = track_state_[tid];
        state.tracked_frames = 1;
        state.bbox = detections[di].bbox;
        state.label = detections[di].label;
        state.last_update_time = current_time;
        det_to_track[di] = tid;
        matched_ids.insert(tid);
    }

    // Build output
    std::vector<TrackedObject> tracked;
    for (int di = 0; di < (int)detections.size(); ++di) {
        auto it = det_to_track.find(di);
        if (it == det_to_track.end()) continue;

        int tid = it->second;
        auto& state = track_state_[tid];

        float distance = detections[di].distance_m;
        if (distance > 0) {
            distance_history_[tid].push_back(distance);
            time_history_[tid].push_back(current_time);
            if ((int)distance_history_[tid].size() > 10) {
                distance_history_[tid].pop_front();
                time_history_[tid].pop_front();
            }
        }

        bool announce = should_announce(tid, detections[di].direction,
                                        distance, current_time);
        if (announce) {
            state.last_announced_time = current_time;
            state.last_zone = detections[di].direction;
            state.last_distance = distance;
        }

        TrackedObject obj;
        static_cast<Detection&>(obj) = detections[di];
        obj.track_id = tid;
        obj.tracked_frames = state.tracked_frames;
        obj.should_announce = announce;
        tracked.push_back(std::move(obj));
    }

    // Increment lost frames
    for (auto it = track_state_.begin(); it != track_state_.end();) {
        if (!matched_ids.count(it->first)) {
            it->second.lost_frames++;
            if (it->second.lost_frames > max_lost_frames_) {
                distance_history_.erase(it->first);
                time_history_.erase(it->first);
                it = track_state_.erase(it);
                continue;
            }
        }
        ++it;
    }

    return tracked;
}

BBox ObjectTracker::predict_bbox(const TrackState& state) const {
    auto [x1, y1, x2, y2] = state.bbox;
    float dt = (float)((double)cv::getTickCount() / cv::getTickFrequency() - state.last_update_time);
    if ((std::abs(state.vel_x) < 1e-6f && std::abs(state.vel_y) < 1e-6f) || dt > 1.0f)
        return state.bbox;
    float dx = state.vel_x * dt;
    float dy = state.vel_y * dt;
    return {x1 + dx, y1 + dy, x2 + dx, y2 + dy};
}

bool ObjectTracker::should_announce(int track_id, const std::string& direction,
                                     float distance, double current_time)
{
    auto it = track_state_.find(track_id);
    if (it == track_state_.end()) return false;
    auto& state = it->second;

    if (state.tracked_frames < min_tracked_frames_) return false;
    if (state.last_announced_time == 0.0) return true;

    double elapsed = current_time - state.last_announced_time;
    if (elapsed < cooldown_seconds_) {
        if (!state.last_zone.empty() && state.last_zone != direction)
            return true;
        if (state.last_distance > 0 && distance > 0) {
            float change = std::abs(distance - state.last_distance) / state.last_distance;
            if (change > distance_change_threshold_) return true;
        }
        return false;
    }
    return true;
}

float ObjectTracker::compute_iou(const BBox& a, const BBox& b) {
    auto [ax1, ay1, ax2, ay2] = a;
    auto [bx1, by1, bx2, by2] = b;
    float x1 = std::max(ax1, bx1);
    float y1 = std::max(ay1, by1);
    float x2 = std::min(ax2, bx2);
    float y2 = std::min(ay2, by2);
    float inter = std::max(0.0f, x2 - x1) * std::max(0.0f, y2 - y1);
    float area_a = (ax2 - ax1) * (ay2 - ay1);
    float area_b = (bx2 - bx1) * (by2 - by1);
    float union_ = area_a + area_b - inter;
    return union_ <= 0 ? 0.0f : inter / union_;
}

float ObjectTracker::get_distance_variance(int track_id) const {
    auto it = distance_history_.find(track_id);
    if (it == distance_history_.end() || it->second.size() < 3) return 0.0f;
    auto& hist = it->second;
    float sum = 0, mean;
    int n = (int)hist.size();
    for (auto v : hist) sum += v;
    mean = sum / n;
    if (mean <= 0) return 0.0f;
    float var = 0;
    for (auto v : hist) var += (v - mean) * (v - mean);
    return std::sqrt(var / n) / mean;
}

float ObjectTracker::get_velocity(int track_id) const {
    auto dit = distance_history_.find(track_id);
    auto tit = time_history_.find(track_id);
    if (dit == distance_history_.end() || tit == time_history_.end()) return 0.0f;
    auto& dists = dit->second;
    auto& times = tit->second;
    if (dists.size() < 3) return 0.0f;

    int n = (int)dists.size();
    std::vector<float> d(dists.begin(), dists.end());
    std::vector<double> t(times.begin(), times.end());
    double t0 = t[0];
    for (auto& ti : t) ti -= t0;
    if (t.back() - t.front() < 0.1) return 0.0f;

    double sum_t = 0, sum_d = 0, sum_td = 0, sum_t2 = 0;
    for (int i = 0; i < n; ++i) {
        sum_t += t[i];
        sum_d += d[i];
        sum_td += t[i] * d[i];
        sum_t2 += t[i] * t[i];
    }
    double denom = n * sum_t2 - sum_t * sum_t;
    if (std::abs(denom) < 1e-10) return 0.0f;
    return (float)((n * sum_td - sum_t * sum_d) / denom);
}

std::string ObjectTracker::get_motion_state(int track_id) const {
    float vel = get_velocity(track_id);
    if (vel < -0.1f) return "APPROACHING";
    if (vel > 0.1f)  return "RECEDING";
    return "STATIONARY";
}

void ObjectTracker::reset() {
    track_state_.clear();
    distance_history_.clear();
    time_history_.clear();
    frame_count_ = 0;
    next_id_ = 1;
}
