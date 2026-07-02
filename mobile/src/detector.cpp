#include "detector.hpp"
#include <opencv2/dnn.hpp>
#ifdef __ANDROID__
#include <nnapi_provider_factory.h>
#endif
#include <algorithm>
#include <cmath>
#include <cassert>
#include <iostream>
#include <thread>

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
    , whitelist_(config.whitelist)
{
    env_ = Ort::Env(OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING, "detector");
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(config.num_threads);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

#ifdef __ANDROID__
    // NNAPI DISABLED: Android 11 NNAPI has a known bug where running two
    // concurrent NNAPI sessions (detector + depth) causes a CHECK crash in
    // libneuralnetworks.so: "mOutputIndexes.size()=0".
    //
    // CPU threading: Snapdragon 765G (bramble) has 8 cores:
    //   cores 0-5: Kryo 475 Silver (A55) @ 1.8 GHz
    //   core  6:   Kryo 475 Gold  (A76) @ 2.2 GHz
    //   core  7:   Kryo 475 Prime (A76) @ 2.4 GHz
    // Use 6 intra-op threads — heavy convolutions spread across all 6 pinned cores.
    // InterOp=1: YOLO is a single sequential graph, no benefit from inter-op parallelism.
    opts.SetIntraOpNumThreads(6);
    opts.SetInterOpNumThreads(1);
#endif

    session_ = Ort::Session(env_, config.yolo_model_path.c_str(), opts);

    // Store AllocatedStringPtr to prevent dangling pointers
    Ort::AllocatorWithDefaultOptions alloc;
    auto input_name = session_.GetInputNameAllocated(0, alloc);
    input_names_.push_back(input_name.get());
    input_names_ptrs_.push_back(std::move(input_name));

    auto output_name = session_.GetOutputNameAllocated(0, alloc);
    output_names_.push_back(output_name.get());
    output_names_ptrs_.push_back(std::move(output_name));

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
    std::vector<Ort::Value>& outputs,
    float frame_area, float min_area)
{
    std::vector<Detection> detections;

    if (outputs.empty()) return detections;

    auto* output = outputs[0].GetTensorMutableData<float>();
    auto output_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();

    // YOLOv8 output shape is [1, 84, 8400] (features x detections)
    // We need [1, 8400, 84] (detections x features) for row-major parsing
    int dim1 = (int)output_shape[1];
    int dim2 = (int)output_shape[2];
    int num_dets, num_features;
    std::vector<float> transposed;

    if (dim1 < dim2) {
        // Transposed YOLOv8 format: [1, features(84), detections(8400)]
        num_features = dim1;
        num_dets = dim2;
        transposed.resize((size_t)num_dets * num_features);
        for (int i = 0; i < num_features; ++i) {
            for (int j = 0; j < num_dets; ++j) {
                transposed[j * num_features + i] = output[i * num_dets + j];
            }
        }
        output = transposed.data();
    } else {
        // Standard format: [1, detections, features]
        num_dets = dim1;
        num_features = dim2;
    }

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

        if (!whitelist_.empty() && whitelist_.find(label) == whitelist_.end()) {
            continue;
        }

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
