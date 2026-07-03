#include <jni.h>
#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <string>
#include <thread>
#include <atomic>
#include <iostream>

#include "pipeline.hpp"
#include "types.hpp"

// Global state
static std::unique_ptr<Pipeline> g_pipeline;
static std::thread g_pipeline_thread;
static std::atomic<bool> g_running{false};
static JavaVM* g_jvm = nullptr;
static jobject g_activity = nullptr;
static jmethodID g_speak_mid = nullptr;
static jmethodID g_speak_urgent_mid = nullptr;

// JNI callbacks for TTS
void speak_callback(const std::string& text, bool urgent) {
    JNIEnv* env;
    if (g_jvm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
    jstring jtext = env->NewStringUTF(text.c_str());
    if (urgent && g_speak_urgent_mid)
        env->CallVoidMethod(g_activity, g_speak_urgent_mid, jtext);
    else if (g_speak_mid)
        env->CallVoidMethod(g_activity, g_speak_mid, jtext);
    env->DeleteLocalRef(jtext);
    g_jvm->DetachCurrentThread();
}

extern "C" {

JNIEXPORT void JNICALL
Java_com_navigation_assistant_MainActivity_00024NativePipeline_start(
    JNIEnv* env, jobject /*thiz*/,
    jobject asset_manager,
    jobject surface,
    jobject speak_cb,
    jobject urgent_cb)
{
    if (g_running.load()) return;

    // Cache JVM and activity references
    env->GetJavaVM(&g_jvm);
    g_activity = env->NewGlobalRef(speak_cb);
    jclass cls = env->GetObjectClass(speak_cb);
    g_speak_mid = env->GetMethodID(cls, "speak", "(Ljava/lang/String;)V");
    g_speak_urgent_mid = env->GetMethodID(
        env->GetObjectClass(urgent_cb), "speak", "(Ljava/lang/String;)V");

    // Load config from assets
    Config cfg;
    cfg.show_window = false; // Android uses SurfaceView, not cv::imshow

    g_pipeline = std::make_unique<Pipeline>(cfg);
    g_running = true;

    g_pipeline_thread = std::thread([cfg]() {
        Pipeline p(cfg);
        if (p.init()) {
            p.run();
        }
    });
    g_pipeline_thread.detach();
}

JNIEXPORT void JNICALL
Java_com_navigation_assistant_MainActivity_00024NativePipeline_stop(
    JNIEnv* env, jobject /*thiz*/)
{
    g_running.store(false);
    g_pipeline.reset();

    if (g_activity) {
        env->DeleteGlobalRef(g_activity);
        g_activity = nullptr;
    }
}

} // extern "C"
