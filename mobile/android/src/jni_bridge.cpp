#include <jni.h>
#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <android/log.h>
#include <sched.h>
#include <string>
#include <thread>
#include <atomic>
#include <iostream>
#include <mutex>

#include "pipeline.hpp"
#include "types.hpp"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  "NavAssistant", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "NavAssistant", __VA_ARGS__)

// Global state
static std::unique_ptr<Pipeline> g_pipeline;
static std::thread g_pipeline_thread;
static std::atomic<bool> g_running{false};
static JavaVM* g_jvm = nullptr;
static jobject g_speak_cb_ref = nullptr;
static jobject g_urgent_cb_ref = nullptr;
static jmethodID g_speak_mid = nullptr;
static jmethodID g_speak_urgent_mid = nullptr;
static std::mutex g_jni_mutex;

static jobject g_thiz_ref = nullptr;
static jmethodID g_on_detections_mid = nullptr;
static jmethodID g_on_dev_log_mid = nullptr;
static jmethodID g_on_scene_triggered_mid = nullptr;

// JNI callback for TTS — thread-safe, called from the pipeline thread
static void speak_callback(const std::string& text, bool urgent) {
    std::lock_guard<std::mutex> lock(g_jni_mutex);
    if (!g_jvm) return;

    JNIEnv* env = nullptr;
    bool did_attach = false;
    int status = g_jvm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);

    if (status == JNI_EDETACHED) {
        if (g_jvm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
        did_attach = true;
    } else if (status != JNI_OK) {
        return;
    }

    jstring jtext = env->NewStringUTF(text.c_str());

    if (urgent && g_urgent_cb_ref && g_speak_urgent_mid) {
        env->CallVoidMethod(g_urgent_cb_ref, g_speak_urgent_mid, jtext);
    } else if (g_speak_cb_ref && g_speak_mid) {
        env->CallVoidMethod(g_speak_cb_ref, g_speak_mid, jtext);
    }

    env->DeleteLocalRef(jtext);

    // Check for and clear any pending Java exceptions
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
    }

    if (did_attach) {
        g_jvm->DetachCurrentThread();
    }
}

static void visual_callback(const std::vector<float>& boxes) {
    std::lock_guard<std::mutex> lock(g_jni_mutex);
    if (!g_jvm || !g_thiz_ref || !g_on_detections_mid) return;

    JNIEnv* env = nullptr;
    bool did_attach = false;
    int status = g_jvm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);

    if (status == JNI_EDETACHED) {
        if (g_jvm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
        did_attach = true;
    } else if (status != JNI_OK) {
        return;
    }

    jfloatArray jboxes = env->NewFloatArray(boxes.size());
    if (jboxes != nullptr) {
        env->SetFloatArrayRegion(jboxes, 0, boxes.size(), boxes.data());
        env->CallVoidMethod(g_thiz_ref, g_on_detections_mid, jboxes);
        env->DeleteLocalRef(jboxes);
    }

    if (env->ExceptionCheck()) {
        env->ExceptionClear();
    }

    if (did_attach) g_jvm->DetachCurrentThread();
}

static void dev_log_callback(const std::string& msg) {
    std::lock_guard<std::mutex> lock(g_jni_mutex);
    if (!g_jvm || !g_thiz_ref || !g_on_dev_log_mid) return;

    JNIEnv* env = nullptr;
    bool did_attach = false;
    int status = g_jvm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);

    if (status == JNI_EDETACHED) {
        if (g_jvm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
        did_attach = true;
    } else if (status != JNI_OK) {
        return;
    }

    jstring jmsg = env->NewStringUTF(msg.c_str());
    env->CallVoidMethod(g_thiz_ref, g_on_dev_log_mid, jmsg);
    env->DeleteLocalRef(jmsg);

    if (env->ExceptionCheck()) {
        env->ExceptionClear();
    }

    if (did_attach) g_jvm->DetachCurrentThread();
}

static void scene_triggered_callback(const std::string& base64Image) {
    std::lock_guard<std::mutex> lock(g_jni_mutex);
    if (!g_jvm || !g_thiz_ref || !g_on_scene_triggered_mid) return;

    JNIEnv* env = nullptr;
    bool did_attach = false;
    int status = g_jvm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);

    if (status == JNI_EDETACHED) {
        if (g_jvm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
        did_attach = true;
    } else if (status != JNI_OK) {
        return;
    }

    jstring jmsg = env->NewStringUTF(base64Image.c_str());
    env->CallVoidMethod(g_thiz_ref, g_on_scene_triggered_mid, jmsg);
    env->DeleteLocalRef(jmsg);

    if (env->ExceptionCheck()) {
        env->ExceptionClear();
    }

    if (did_attach) g_jvm->DetachCurrentThread();
}

extern "C" {

JNIEXPORT void JNICALL
Java_com_navigation_assistant_MainActivity_00024NativePipeline_start(
    JNIEnv* env, jobject thiz,
    jobject asset_manager,
    jstring data_path,
    jobject speak_cb,
    jobject urgent_cb)
{
    if (g_running.load()) return;

    // Cache JVM reference
    env->GetJavaVM(&g_jvm);

    // Create global refs for the callback objects so they survive across JNI calls
    g_thiz_ref = env->NewGlobalRef(thiz);
    g_speak_cb_ref = env->NewGlobalRef(speak_cb);
    g_urgent_cb_ref = env->NewGlobalRef(urgent_cb);

    // Resolve the "speak" method on each callback interface
    jclass speak_cls = env->GetObjectClass(speak_cb);
    g_speak_mid = env->GetMethodID(speak_cls, "speak", "(Ljava/lang/String;)V");

    jclass urgent_cls = env->GetObjectClass(urgent_cb);
    g_speak_urgent_mid = env->GetMethodID(urgent_cls, "speak", "(Ljava/lang/String;)V");

    jclass thiz_cls = env->GetObjectClass(thiz);
    g_on_detections_mid = env->GetMethodID(thiz_cls, "onDetections", "([F)V");
    g_on_dev_log_mid = env->GetMethodID(thiz_cls, "onDevLog", "(Ljava/lang/String;)V");
    g_on_scene_triggered_mid = env->GetMethodID(thiz_cls, "onSceneTriggered", "(Ljava/lang/String;)V");

    // Build config with model paths pointing to extracted internal-storage files
    Config cfg;
    cfg.show_window = false;

    const char* native_data_path = env->GetStringUTFChars(data_path, nullptr);
    std::string base_path = native_data_path;
    env->ReleaseStringUTFChars(data_path, native_data_path);

    cfg.yolo_model_path  = base_path + "/yolov8n_int8.onnx";
    cfg.midas_model_path = base_path + "/midas_v21_small_256.onnx";

    // Force 640x640 so the square crop doesn't get distorted into a rectangle
    // before it reaches YOLO's 640x640 input.
    cfg.frame_width  = 640;
    cfg.frame_height = 640;

    // Only detect classes relevant to indoor navigation.
    // Keeps horse, airplane, cow, etc. from generating false alerts.
    cfg.whitelist = {
        "person", "bicycle", "car", "motorcycle", "bus", "truck",
        "chair", "couch", "bed", "dining table", "toilet", "tv", "laptop",
        "cell phone", "bottle", "cup", "backpack", "handbag", "suitcase",
        "umbrella", "book", "potted plant", "dog", "cat",
        "stop sign", "fire hydrant", "bench"
    };

    // yolov8n_int8: best speed/accuracy tradeoff on mobile hardware
    // 0.45 threshold avoids false positives (jackets, blankets etc.)
    cfg.confidence_threshold  = 0.45f;
    cfg.nms_iou_threshold     = 0.40f;

    LOGI("Starting pipeline with models at: %s", base_path.c_str());

    g_pipeline = std::make_unique<Pipeline>(cfg);
    g_pipeline->set_alert_callback(speak_callback);
    g_pipeline->set_visual_callback(visual_callback);
    g_pipeline->set_dev_log_callback(dev_log_callback);
    g_pipeline->set_scene_triggered_callback(scene_triggered_callback);
    g_running.store(true);

    g_pipeline_thread = std::thread([]() {
        // Pin this thread (and ORT's spawned intra-op threads) to cores 4-7:
        // cores 4-5 = faster A55 Silver, cores 6-7 = A76 Gold + Prime.
        // This keeps inference off the OS/camera/audio cores (0-3).
        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);
        for (int c = 4; c <= 7; c++) CPU_SET(c, &cpuset);
        sched_setaffinity(0, sizeof(cpuset), &cpuset);

        LOGI("Pipeline thread started (pinned to cores 4-7), loading models...");
        if (!g_pipeline->init()) {
            LOGE("Pipeline::init() failed");
            g_running.store(false);
            return;
        }
        LOGI("Models loaded. Pipeline ready for CameraX frames.");
        g_pipeline->run();
        g_running.store(false);
        LOGI("Pipeline thread exiting.");
    });
}

// Called from Java's CameraX image analysis callback for every camera frame.
// data: NV21 byte array (Y plane then interleaved VU plane)
// width/height: frame dimensions from CameraX
JNIEXPORT void JNICALL
Java_com_navigation_assistant_MainActivity_00024NativePipeline_processFrame(
    JNIEnv* env, jobject /*thiz*/,
    jbyteArray data,
    jint width,
    jint height,
    jint rotation)
{
    if (!g_pipeline || !g_running.load()) return;

    jsize len = env->GetArrayLength(data);
    jbyte* bytes = env->GetByteArrayElements(data, nullptr);
    if (!bytes) return;

    g_pipeline->push_frame(reinterpret_cast<const uint8_t*>(bytes), width, height, rotation);

    env->ReleaseByteArrayElements(data, bytes, JNI_ABORT);
}

JNIEXPORT void JNICALL
Java_com_navigation_assistant_MainActivity_00024NativePipeline_stop(
    JNIEnv* env, jobject /*thiz*/)
{
    // Signal the pipeline to stop
    if (g_pipeline) {
        g_pipeline->stop();
    }

    // Wait for the thread to finish (with timeout to avoid ANR)
    if (g_pipeline_thread.joinable()) {
        g_pipeline_thread.join();
    }

    g_pipeline.reset();
    g_running.store(false);

    // Clean up global JNI refs
    std::lock_guard<std::mutex> lock(g_jni_mutex);
    if (g_thiz_ref) {
        env->DeleteGlobalRef(g_thiz_ref);
        g_thiz_ref = nullptr;
    }
    if (g_speak_cb_ref) {
        env->DeleteGlobalRef(g_speak_cb_ref);
        g_speak_cb_ref = nullptr;
    }
    if (g_urgent_cb_ref) {
        env->DeleteGlobalRef(g_urgent_cb_ref);
        g_urgent_cb_ref = nullptr;
    }
    g_speak_mid = nullptr;
    g_speak_urgent_mid = nullptr;
}

JNIEXPORT void JNICALL
Java_com_navigation_assistant_MainActivity_00024NativePipeline_toggleLanguage(
    JNIEnv* /*env*/, jobject /*thiz*/)
{
    if (g_pipeline) {
        g_pipeline->toggle_language();
    }
}

} // extern "C"
