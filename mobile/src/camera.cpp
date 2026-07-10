#include "camera.hpp"
#include <opencv2/imgproc.hpp>

CameraStream::CameraStream(int source, int width, int height)
    : width_(width), height_(height), use_url_(false)
{
#ifdef __ANDROID__
    cap_.open(source, cv::CAP_ANDROID);
#else
    cap_.open(source);
#endif
    if (cap_.isOpened()) {
        cap_.set(cv::CAP_PROP_FRAME_WIDTH, width);
        cap_.set(cv::CAP_PROP_FRAME_HEIGHT, height);
        cap_.set(cv::CAP_PROP_BUFFERSIZE, 1);
    }
}

CameraStream::CameraStream(const std::string& url, int width, int height)
    : width_(width), height_(height), url_(url), use_url_(true)
{
#ifdef __ANDROID__
    cap_.open(url, cv::CAP_ANDROID);
#else
    cap_.open(url);
#endif
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
    double fps = cap_.get(cv::CAP_PROP_FPS);
    if (fps <= 0) fps = 30.0;
    int delay_ms = (int)(1000.0 / fps);

    while (running_) {
        cv::Mat frame;
        bool ret = cap_.read(frame);
        if (ret) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                latest_frame_ = frame.clone();
                got_frame_ = true;
            }
            if (use_url_) {
                std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
            }
        } else {
            if (use_url_) {
                // Loop the video back to the beginning
                cap_.set(cv::CAP_PROP_POS_FRAMES, 0);
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }
        }
    }
}
