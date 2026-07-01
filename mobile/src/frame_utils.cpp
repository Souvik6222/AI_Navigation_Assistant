#include "frame_utils.hpp"
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>
#include <sstream>
#include <iomanip>

cv::Mat resize_frame(const cv::Mat& frame, int width, int height) {
    cv::Mat out;
    cv::resize(frame, out, cv::Size(width, height), 0, 0, cv::INTER_LINEAR);
    return out;
}

cv::Mat annotate_frame(const cv::Mat& frame, const std::vector<TrackedObject>& objects) {
    cv::Mat annotated = frame.clone();
    int h = annotated.rows, w = annotated.cols;

    // Zone divider lines
    int z1 = (int)(w * 0.33f);
    int z2 = (int)(w * 0.66f);
    cv::line(annotated, {z1, 0}, {z1, h}, {80, 80, 80}, 1, cv::LINE_AA);
    cv::line(annotated, {z2, 0}, {z2, h}, {80, 80, 80}, 1, cv::LINE_AA);

    int font = cv::FONT_HERSHEY_SIMPLEX;
    cv::putText(annotated, "LEFT",   {10, 20},    font, 0.5, {120, 120, 120}, 1, cv::LINE_AA);
    cv::putText(annotated, "CENTER", {z1 + 10, 20}, font, 0.5, {120, 120, 120}, 1, cv::LINE_AA);
    cv::putText(annotated, "RIGHT",  {z2 + 10, 20}, font, 0.5, {120, 120, 120}, 1, cv::LINE_AA);

    for (const auto& obj : objects) {
        auto [x1, y1, x2, y2] = obj.bbox;
        int ix1 = (int)x1, iy1 = (int)y1, ix2 = (int)x2, iy2 = (int)y2;

        std::string level = obj.alert_level;
        cv::Scalar color;
        int thick = 2;
        if (level == "urgent")   { color = {0, 0, 255}; thick = 3; }
        else if (level == "warning") color = {0, 165, 255};
        else if (level == "info")    color = {0, 255, 0};
        else                         color = {180, 180, 180};

        cv::rectangle(annotated, {ix1, iy1}, {ix2, iy2}, color, thick);

        std::ostringstream top, bot;
        top << "ID:" << obj.track_id << " " << obj.label
            << " " << std::fixed << std::setprecision(0) << (obj.confidence * 100) << "%";
        if (obj.distance_m >= 0)
            bot << std::fixed << std::setprecision(1) << obj.distance_m << "m ";
        else
            bot << "? ";
        bot << obj.direction;

        // Background for text
        int baseline;
        cv::Size tw1 = cv::getTextSize(top.str(), font, 0.45, 1, &baseline);
        cv::Size tw2 = cv::getTextSize(bot.str(), font, 0.45, 1, &baseline);
        int max_tw = std::max(tw1.width, tw2.width);
        int txt_y = std::max(iy1 - 8, 30);

        cv::rectangle(annotated,
            {ix1, txt_y - tw1.height - tw2.height - 12},
            {ix1 + max_tw + 6, txt_y + 4},
            color, -1);

        cv::putText(annotated, top.str(), {ix1 + 3, txt_y - tw2.height - 6},
                    font, 0.45, {255, 255, 255}, 1, cv::LINE_AA);
        cv::putText(annotated, bot.str(), {ix1 + 3, txt_y},
                    font, 0.45, {255, 255, 255}, 1, cv::LINE_AA);

        if (level == "urgent") {
            cv::Mat overlay = annotated.clone();
            cv::rectangle(overlay, {ix1, iy1}, {ix2, iy2}, {0, 0, 255}, -1);
            cv::addWeighted(overlay, 0.15, annotated, 0.85, 0, annotated);
        }
    }

    return annotated;
}

cv::Mat draw_status_bar(const cv::Mat& frame, const std::string& language,
                         float fps, int num_objects)
{
    cv::Mat out = frame.clone();
    int h = out.rows, w = out.cols;
    int bar_h = 30;

    cv::rectangle(out, {0, h - bar_h}, {w, h}, {30, 30, 30}, -1);

    std::ostringstream ss;
    ss << "Lang: " << (language == "hi" ? "HI" : "EN")
       << " | FPS: " << std::fixed << std::setprecision(0) << fps
       << " | Objects: " << num_objects
       << " | [H] Lang | [D] Describe | [Q] Quit";

    int font = cv::FONT_HERSHEY_SIMPLEX;
    cv::putText(out, ss.str(), {10, h - 10}, font, 0.4, {200, 200, 200}, 1, cv::LINE_AA);
    return out;
}

std::string frame_to_base64(const cv::Mat& frame) {
    std::vector<uchar> buf;
    cv::imencode(".jpg", frame, buf, {cv::IMWRITE_JPEG_QUALITY, 85});
    auto* data = buf.data();
    int size = (int)buf.size();

    static const char* table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string b64;
    b64.reserve((size + 2) / 3 * 4);

    for (int i = 0; i < size; i += 3) {
        int b = (data[i] << 16) |
                (i + 1 < size ? data[i+1] << 8 : 0) |
                (i + 2 < size ? data[i+2] : 0);
        b64 += table[(b >> 18) & 0x3F];
        b64 += table[(b >> 12) & 0x3F];
        b64 += (i + 1 < size) ? table[(b >> 6) & 0x3F] : '=';
        b64 += (i + 2 < size) ? table[b & 0x3F] : '=';
    }
    return b64;
}
