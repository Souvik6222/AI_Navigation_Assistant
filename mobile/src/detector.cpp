#include "detector.hpp"
#include <opencv2/dnn.hpp>
#include <algorithm>
#include <cmath>
#include <cassert>

static const std::vector<std::string> COCO_NAMES = {
    "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
    "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
    "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
    "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
    "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
    "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
    "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
    "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse",
    "remote","keyboard","cell phone","microwave","oven","toaster","sink","refrigerator",
    "book","clock","vase","scissors","teddy bear","hair drier","toothbrush"
};

ObjectDetector::ObjectDetector(const Config& config)
    : confidence_threshold_(config.confidence_threshold)
    , min_bbox_area_ratio_(config.min_bbox_area_ratio)
{
    env_ = Ort::Env(OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING, "detector");
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(1);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

    session_ = Ort::Session(env_, config.yolo_model_path.c_str(), opts);

    Ort::AllocatorWithDefaultOptions alloc;
    input_names_.push_back(session_.GetInputNameAllocated(0, alloc).get());
    output_names_.push_back(session_.GetOutputNameAllocated(0, alloc).get());

    auto input_shape = session_.GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
    if (input_shape.size() >= 4) {
        input_h_ = (int)input_shape[2];
        input_w_ = (int)input_shape[3];
    }

    memory_info_ = Ort::MemoryInfo::CreateCpu(OrtAllocatorType::OrtArenaAllocator,
                                               OrtMemType::OrtMemTypeDefault);
}

std::vector<Detection> ObjectDetector::detect(const cv::Mat& frame) {
    int frame_h = frame.rows, frame_w = frame.cols;
    float frame_area = (float)(frame_h * frame_w);
    float min_area = frame_area * min_bbox_area_ratio_;

    // Preprocess: resize, letterbox, normalize
    cv::Mat blob = cv::dnn::blobFromImage(frame, 1.0f / 255.0f,
                                           cv::Size(input_w_, input_h_),
                                           cv::Scalar(), true, false);

    std::vector<int64_t> input_shape = {1, 3, input_h_, input_w_};
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory_info_, blob.ptr<float>(), blob.total(),
        input_shape.data(), input_shape.size()
    );

    std::vector<Ort::Value> outputs = session_.Run(
        Ort::RunOptions{nullptr},
        input_names_.data(), &input_tensor, 1,
        output_names_.data(), output_names_.size()
    );

    return postprocess(frame, outputs, frame_area, min_area);
}

std::vector<Detection> ObjectDetector::postprocess(
    const cv::Mat& frame,
    const std::vector<Ort::Value>& outputs,
    float frame_area, float min_area)
{
    std::vector<Detection> detections;

    if (outputs.empty()) return detections;

    auto* output = outputs[0].GetTensorMutableData<float>();
    auto output_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    int num_dets = (int)output_shape[1];
    int num_features = (int)output_shape[2];

    float scale_x = (float)frame.cols / input_w_;
    float scale_y = (float)frame.rows / input_h_;

    std::vector<cv::Rect> boxes;
    std::vector<float> scores;
    std::vector<int> class_ids;

    for (int i = 0; i < num_dets; ++i) {
        float* ptr = output + i * num_features;
        float cx = ptr[0];
        float cy = ptr[1];
        float w = ptr[2];
        float h = ptr[3];

        float x1 = (cx - w / 2) * scale_x;
        float y1 = (cy - h / 2) * scale_y;
        float x2 = (cx + w / 2) * scale_x;
        float y2 = (cy + h / 2) * scale_y;

        float max_score = 0.0f;
        int best_cls = -1;
        for (int c = 4; c < num_features; ++c) {
            if (ptr[c] > max_score) {
                max_score = ptr[c];
                best_cls = c - 4;
            }
        }

        if (max_score < confidence_threshold_) continue;
        boxes.emplace_back((int)x1, (int)y1, (int)(x2 - x1), (int)(y2 - y1));
        scores.push_back(max_score);
        class_ids.push_back(best_cls);
    }

    // NMS
    std::vector<int> indices;
    cv::dnn::NMSBoxes(boxes, scores, confidence_threshold_, iou_threshold_, indices);

    for (int idx : indices) {
        const auto& box = boxes[idx];
        float x1 = (float)box.x;
        float y1 = (float)box.y;
        float x2 = (float)(box.x + box.width);
        float y2 = (float)(box.y + box.height);

        float bbox_area = (x2 - x1) * (y2 - y1);
        if (bbox_area < min_area) continue;

        int cls = class_ids[idx];
        std::string label = (cls >= 0 && cls < (int)COCO_NAMES.size())
                            ? COCO_NAMES[cls] : "unknown";

        Detection det;
        det.label = label;
        det.confidence = scores[idx];
        det.bbox = {x1, y1, x2, y2};
        det.center_x = (x1 + x2) / 2.0f;
        det.center_y = (y1 + y2) / 2.0f;
        det.area = bbox_area;
        det.class_id = cls;
        detections.push_back(std::move(det));
    }

    return detections;
}
