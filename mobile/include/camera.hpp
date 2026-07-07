#pragma once
#include <opencv2/core.hpp>
#include <opencv2/videoio.hpp>
#include <mutex>
#include <thread>
#include <atomic>

class CameraStream {
public:
    CameraStream(int source, int width = 640, int height = 480);
    explicit CameraStream(const std::string& url, int width = 640, int height = 480);
    ~CameraStream();

    bool is_opened() const;
    void start();
    bool read(cv::Mat& frame);
    void stop();

private:
    void reader_loop();

    cv::VideoCapture cap_;
    int width_, height_;
    std::string url_;
    bool use_url_ = false;

    std::mutex mutex_;
    cv::Mat latest_frame_;
    bool got_frame_ = false;
    std::atomic<bool> running_{false};
    std::thread reader_thread_;
};
