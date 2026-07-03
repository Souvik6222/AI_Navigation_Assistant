#include "camera.hpp"
#include <opencv2/imgproc.hpp>

CameraStream::CameraStream(int source, int width, int height)
    : width_(width), height_(height), use_url_(false)
{
    cap_.open(source);
    if (cap_.isOpened()) {
        cap_.set(cv::CAP_PROP_FRAME_WIDTH, width);
        cap_.set(cv::CAP_PROP_FRAME_HEIGHT, height);
        cap_.set(cv::CAP_PROP_BUFFERSIZE, 1);
    }
}

CameraStream::CameraStream(const std::string& url, int width, int height)
    : width_(width), height_(height), url_(url), use_url_(true)
{
    cap_.open(url);
    if (cap_.isOpened()) {
        cap_.set(cv::CAP_PROP_FRAME_WIDTH, width);
        cap_.set(cv::CAP_PROP_FRAME_HEIGHT, height);
        cap_.set(cv::CAP_PROP_BUFFERSIZE, 1);
    }
}

CameraStream::~CameraStream() {
    stop();
}

bool CameraStream::is_opened() const {
    return cap_.isOpened();
}

void CameraStream::start() {
    if (running_) return;
    running_ = true;
    reader_thread_ = std::thread(&CameraStream::reader_loop, this);
}

bool CameraStream::read(cv::Mat& frame) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!got_frame_) return false;
    frame = latest_frame_.clone();
    return true;
}

void CameraStream::stop() {
    running_ = false;
    if (reader_thread_.joinable())
        reader_thread_.join();
    if (cap_.isOpened())
        cap_.release();
}

void CameraStream::reader_loop() {
    while (running_) {
        cv::Mat frame;
        bool ret = cap_.read(frame);
        if (ret) {
            std::lock_guard<std::mutex> lock(mutex_);
            latest_frame_ = frame.clone();
            got_frame_ = true;
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    }
}
