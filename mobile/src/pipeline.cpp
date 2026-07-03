#include "pipeline.hpp"
#include "direction.hpp"
#include "frame_utils.hpp"
#include <opencv2/highgui.hpp>
#include <iostream>
#include <chrono>

Pipeline::Pipeline(const Config& config)
    : config_(config)
{
}

Pipeline::~Pipeline() = default;

bool Pipeline::init() {
    detector_ = std::make_unique<ObjectDetector>(config_);
    depth_estimator_ = std::make_unique<DepthEstimator>(config_);
    tracker_ = std::make_unique<ObjectTracker>(config_);
    decision_engine_ = std::make_unique<DecisionEngine>(config_);
    decision_engine_->set_tracker(tracker_.get());

    if (config_.cam_index >= 0) {
        camera_ = std::make_unique<CameraStream>(
            config_.cam_index, config_.frame_width, config_.frame_height
        );
    } else {
        camera_ = std::make_unique<CameraStream>(
            std::to_string(config_.cam_index), config_.frame_width, config_.frame_height
        );
    }

    if (!camera_->is_opened()) {
        std::cerr << "ERROR: Failed to open camera " << config_.cam_index << std::endl;
        return false;
    }

    camera_->start();
    fps_start_time_ = (double)cv::getTickCount() / cv::getTickFrequency();
    return true;
}

int Pipeline::run() {
    if (!init()) return 1;

    running_ = true;
    int frame_index = 0;
    cv::Mat frame;

    while (running_) {
        if (!camera_->read(frame)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
        }

        // Rotate if needed
        if (config_.frame_rotation != 0) {
            switch (config_.frame_rotation) {
                case 90:  cv::rotate(frame, frame, cv::ROTATE_90_CLOCKWISE); break;
                case -90: cv::rotate(frame, frame, cv::ROTATE_90_COUNTERCLOCKWISE); break;
                case 180: cv::rotate(frame, frame, cv::ROTATE_180); break;
            }
        }

        frame = resize_frame(frame, config_.frame_width, config_.frame_height);
        frame_index++;

        process_frame(frame, frame_index);

        // FPS calculation
        fps_counter_++;
        double now = (double)cv::getTickCount() / cv::getTickFrequency();
        if (now - fps_start_time_ >= 1.0) {
            current_fps_ = (float)(fps_counter_ / (now - fps_start_time_));
            fps_counter_ = 0;
            fps_start_time_ = now;
        }

        // Handle keyboard on desktop
        if (config_.show_window) {
            int key = cv::waitKey(1) & 0xFF;
            handle_key(key);
        }
    }

    camera_->stop();
    cv::destroyAllWindows();
    return 0;
}

void Pipeline::process_frame(cv::Mat& frame, int frame_index) {
    int fw = config_.frame_width;

    // Frame skip: only process AI on every Nth frame
    if (frame_index % config_.process_every_n_frames == 0) {
        detections_ = detector_->detect(frame);

        if (!detections_.empty()) {
            cv::Mat depth_map = depth_estimator_->estimate(frame);
            for (auto& det : detections_) {
                det.direction = get_direction(
                    det.center_x, fw,
                    config_.left_boundary, config_.right_boundary
                );
                det.distance_m = depth_estimator_->get_distance(depth_map, det.bbox);
            }
        }

        cached_tracked_objects_ = tracker_->update(detections_, fw);

        auto alerts = decision_engine_->evaluate(cached_tracked_objects_);

        for (auto& obj : cached_tracked_objects_) {
            if (obj.alert_level == "silent") {
                float d = obj.distance_m;
                if (d < config_.urgent_threshold)
                    obj.alert_level = "urgent";
                else if (d < config_.warning_threshold)
                    obj.alert_level = "warning";
                else if (d < config_.info_threshold)
                    obj.alert_level = "info";
            }
        }

        cached_annotated_frame_ = annotate_frame(frame, cached_tracked_objects_);

        // Print alerts to stdout (TTS handled by platform layer)
        for (const auto& alert : alerts) {
            std::cout << "[" << alert.level << "] "
                      << alert.message_en << std::endl;
        }

    } else {
        cached_annotated_frame_ = cached_tracked_objects_.empty()
            ? frame.clone()
            : annotate_frame(frame, cached_tracked_objects_);
    }

    // Status bar
    cv::Mat display = draw_status_bar(
        cached_annotated_frame_, language_,
        current_fps_, (int)cached_tracked_objects_.size()
    );

    if (config_.show_window) {
        cv::imshow("AI Navigation Assistant", display);
    }
}

void Pipeline::handle_key(int key) {
    if (key == 'q' || key == 27) {
        std::cout << "Quit command received" << std::endl;
        running_ = false;
    } else if (key == 'h') {
        language_ = (language_ == "en") ? "hi" : "en";
        std::cout << "Language toggled to: " << language_ << std::endl;
    }
}
