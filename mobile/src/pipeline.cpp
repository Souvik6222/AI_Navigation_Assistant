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
void Pipeline::push_frame(const uint8_t* data, int width, int height) {
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
