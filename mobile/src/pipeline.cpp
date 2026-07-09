#include "pipeline.hpp"
#include "direction.hpp"
#include "frame_utils.hpp"
#include <iostream>
#include <chrono>
#include <thread>
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>

#ifndef __ANDROID__
#include <opencv2/highgui.hpp>
#endif

Pipeline::Pipeline(const Config& config)
    : config_(config)
{
}

Pipeline::~Pipeline() {
    stop();
}

bool Pipeline::init() {
    detector_ = std::make_unique<ObjectDetector>(config_);
    depth_estimator_ = std::make_unique<DepthEstimator>(config_);
    tracker_ = std::make_unique<ObjectTracker>(config_);
    decision_engine_ = std::make_unique<DecisionEngine>(config_);
    decision_engine_->set_tracker(tracker_.get());
    llm_client_ = std::make_unique<LLMClient>();

#ifndef __ANDROID__
    // Desktop: own the camera here
    bool is_int = true;
    for (char c : config_.cam_source) {
        if (!std::isdigit(c)) { is_int = false; break; }
    }

    if (is_int) {
        camera_ = std::make_unique<CameraStream>(
            std::stoi(config_.cam_source), config_.frame_width, config_.frame_height
        );
    } else {
        camera_ = std::make_unique<CameraStream>(
            config_.cam_source, config_.frame_width, config_.frame_height
        );
    }

    if (!camera_->is_opened()) {
        std::cerr << "ERROR: Failed to open camera " << config_.cam_source << std::endl;
        return false;
    }

    camera_->start();
#endif

    fps_start_time_ = (double)cv::getTickCount() / cv::getTickFrequency();
    last_scene_trigger_time_ = fps_start_time_;
    running_.store(true);
    return true;
}

void Pipeline::stop() {
    running_.store(false);
}

void Pipeline::toggle_language() {
    language_ = (language_ == "en") ? "hi" : "en";
    std::cout << "Language toggled to: " << language_ << std::endl;
}

void Pipeline::set_alert_callback(AlertCallback cb) {
    alert_callback_ = std::move(cb);
}

void Pipeline::set_visual_callback(VisualCallback cb) {
    visual_callback_ = std::move(cb);
}

void Pipeline::set_dev_log_callback(DevLogCallback cb) {
    dev_log_callback_ = std::move(cb);
}

void Pipeline::set_scene_triggered_callback(SceneTriggeredCallback cb) {
    scene_triggered_callback_ = std::move(cb);
}

int Pipeline::run() {
    if (!init()) return 1;

#ifdef __ANDROID__
    // On Android, frames are pushed externally by CameraX via push_frame().
    // This function just keeps the pipeline alive until stop() is called.
    while (running_.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return 0;
#else
    int frame_index = 0;
    cv::Mat frame;

    while (running_.load()) {
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

        // Center-crop to square for 1:1 aspect ratio (matches YOLO's 640x640 input)
        frame = center_crop_square(frame);

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
    if (config_.show_window) {
        cv::destroyAllWindows();
    }
    return 0;
#endif
}

#ifdef __ANDROID__
void Pipeline::push_frame(const uint8_t* data, int width, int height, int rotation) {
    if (!running_.load()) return;

    // NNAPI is not re-entrant: concurrent inference during camera switch
    // causes a CHECK failure in libneuraletworks. Use try_lock to skip frames
    // during the brief window while inference is running, rather than queue them.
    if (!frame_mutex_.try_lock()) return;
    std::lock_guard<std::mutex> hold(frame_mutex_, std::adopt_lock);

    // Convert NV21 (YUV420sp) byte array from CameraX → BGR cv::Mat
    // NV21 layout: Y plane (width*height bytes) followed by interleaved VU (width*height/2 bytes)
    cv::Mat nv21(height + height / 2, width, CV_8UC1, const_cast<uint8_t*>(data));
    cv::Mat bgr;
    cv::cvtColor(nv21, bgr, cv::COLOR_YUV2BGR_NV21);

    // CameraX delivers frames in sensor orientation (landscape). Rotate them 
    // to match the physical screen (portrait) BEFORE feeding them to YOLO.
    // This ensures YOLO's bounding boxes are upright, allowing direct mapping in UI.
    if (rotation != 0) {
        switch (rotation) {
            case 90:  cv::rotate(bgr, bgr, cv::ROTATE_90_CLOCKWISE); break;
            case 270: cv::rotate(bgr, bgr, cv::ROTATE_90_COUNTERCLOCKWISE); break;
            case 180: cv::rotate(bgr, bgr, cv::ROTATE_180); break;
        }
    }

    // Center-crop to square BEFORE resize to preserve 1:1 aspect ratio for YOLO
    bgr = center_crop_square(bgr);

    // Resize to configured processing resolution
    if (bgr.cols != config_.frame_width || bgr.rows != config_.frame_height) {
        cv::resize(bgr, bgr, cv::Size(config_.frame_width, config_.frame_height));
    }

    frame_index_++;

    process_frame(bgr, frame_index_);

    // FPS tracking
    fps_counter_++;
    double now = (double)cv::getTickCount() / cv::getTickFrequency();
    if (now - fps_start_time_ >= 1.0) {
        current_fps_ = (float)(fps_counter_ / (now - fps_start_time_));
        fps_counter_ = 0;
        fps_start_time_ = now;
        
        if (dev_log_callback_) {
            char buf[64];
            snprintf(buf, sizeof(buf), "FPS: %.1f | Mode: %s", current_fps_, 
                (config_.process_every_n_frames > 1 ? "Skip" : "Full"));
            dev_log_callback_(std::string(buf));
        }
    }
}
#endif

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

            // Depth-only wall check: if center zone is very close but YOLO sees nothing
            // (happens with featureless white/plain walls), announce a generic obstacle.
            // MiDaS raw values are INVERTED: high = close, low = far.
            // We look at the center 30% of the frame as a depth_map region.
            if (!depth_map.empty()) {
                int cx = depth_map.cols / 2, cy = depth_map.rows / 2;
                int rw = depth_map.cols / 6, rh = depth_map.rows / 6; // 30% strip
                cv::Rect center_roi(cx - rw, cy - rh, rw * 2, rh * 2);
                center_roi &= cv::Rect(0, 0, depth_map.cols, depth_map.rows);
                cv::Mat center_patch = depth_map(center_roi);
                double mean_depth = cv::mean(center_patch)[0];

                // mean_depth > 0.65 means center is very close (MiDaS: high = close, 0-1 float)
                double high_thresh = 0.65;
                if (mean_depth > high_thresh && detections_.empty()) {
                    // Inject a fake "wall" detection so the tracker/decision engine handle it
                    Detection wall_det;
                    wall_det.label = "wall";
                    wall_det.confidence = 1.0f;
                    wall_det.direction = "CENTER";
                    wall_det.distance_m = 1.0f; // raw depth only — treat as ~1m
                    wall_det.center_x = fw / 2.0f;
                    wall_det.center_y = config_.frame_height / 2.0f;
                    wall_det.bbox = {cx - rw, cy - rh, cx + rw, cy + rh};
                    wall_det.class_id = 999;
                    detections_.push_back(wall_det);
                }
            }
        } else {
            // Even with no detections, still run depth to check for walls
            cv::Mat depth_map = depth_estimator_->estimate(frame);
            if (!depth_map.empty()) {
                int cx = depth_map.cols / 2, cy = depth_map.rows / 2;
                int rw = depth_map.cols / 6, rh = depth_map.rows / 6;
                cv::Rect center_roi(cx - rw, cy - rh, rw * 2, rh * 2);
                center_roi &= cv::Rect(0, 0, depth_map.cols, depth_map.rows);
                cv::Mat center_patch = depth_map(center_roi);
                double mean_depth = cv::mean(center_patch)[0];

                double high_thresh = 0.65; // depth map is 0.0-1.0 float (high = close)
                if (mean_depth > high_thresh) {
                    Detection wall_det;
                    wall_det.label = "wall";
                    wall_det.confidence = 1.0f;
                    wall_det.direction = "CENTER";
                    wall_det.distance_m = 1.0f;
                    wall_det.center_x = fw / 2.0f;
                    wall_det.center_y = config_.frame_height / 2.0f;
                    wall_det.bbox = {cx - rw, cy - rh, cx + rw, cy + rh};
                    wall_det.class_id = 999;
                    detections_.push_back(wall_det);
                }
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

        if (visual_callback_) {
            std::vector<float> boxes;
            boxes.reserve(cached_tracked_objects_.size() * 6);
            for (const auto& obj : cached_tracked_objects_) {
                boxes.push_back(static_cast<float>(obj.class_id));
                boxes.push_back(std::get<0>(obj.bbox));
                boxes.push_back(std::get<1>(obj.bbox));
                boxes.push_back(std::get<2>(obj.bbox));
                boxes.push_back(std::get<3>(obj.bbox));
                boxes.push_back(obj.distance_m);
            }
            visual_callback_(boxes);
        }

        // Dispatch alerts: invoke callback (Android TTS) AND print to stdout
        for (const auto& alert : alerts) {
            bool is_urgent = (alert.level == "urgent");
            const std::string& message = (language_ == "hi")
                ? alert.message_hi : alert.message_en;

            if (alert_callback_) {
                alert_callback_(message, is_urgent);
            } else {
#if defined(__linux__) && !defined(__ANDROID__)
                std::string cmd = "espeak \"" + message + "\" > /dev/null 2>&1 &";
                std::system(cmd.c_str());
#endif
            }

            std::cout << "[" << alert.level << "] " << message << std::endl;
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

    // Auto trigger scene description every 15 seconds
    double now = (double)cv::getTickCount() / cv::getTickFrequency();
    if (scene_triggered_callback_ && (now - last_scene_trigger_time_ >= 15.0)) {
        if (!cached_annotated_frame_.empty()) {
            std::string b64 = frame_to_base64(cached_annotated_frame_);
            std::thread([this, b64]() {
                scene_triggered_callback_(b64);
            }).detach();
            last_scene_trigger_time_ = now;
        }
    }

#ifndef __ANDROID__
    if (config_.show_window) {
        cv::imshow("AI Navigation Assistant", display);
    }
#endif
}

void Pipeline::handle_key(int key) {
    if (key == 'q' || key == 27) {
        std::cout << "Quit command received" << std::endl;
        running_.store(false);
    } else if (key == 'h') {
        toggle_language();
    } else if (key == 's') {
        if (!cached_annotated_frame_.empty() && llm_client_) {
            std::cout << "Requesting scene description from LM Studio..." << std::endl;
            std::string b64 = frame_to_base64(cached_annotated_frame_);
            std::thread([this, b64]() {
                llm_client_->request_scene_description(b64);
            }).detach();
        }
    }
}
