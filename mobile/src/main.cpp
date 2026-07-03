#include "pipeline.hpp"
#include <iostream>
#include <cstring>
#include <fstream>
#include <yaml-cpp/yaml.h>

static Config load_config(const std::string& path) {
    Config cfg;

    try {
        YAML::Node root = YAML::LoadFile(path);

        if (root["performance"]["process_every_n_frames"])
            cfg.process_every_n_frames = root["performance"]["process_every_n_frames"].as<int>();

        if (root["camera"]["device_index"])
            cfg.cam_index = root["camera"]["device_index"].as<int>();
        if (root["camera"]["frame_width"])
            cfg.frame_width = root["camera"]["frame_width"].as<int>();
        if (root["camera"]["frame_height"])
            cfg.frame_height = root["camera"]["frame_height"].as<int>();
        if (root["camera"]["rotation"])
            cfg.frame_rotation = root["camera"]["rotation"].as<int>();

        if (root["detection"]["model_path"])
            cfg.yolo_model_path = root["detection"]["model_path"].as<std::string>();
        if (root["detection"]["confidence_threshold"])
            cfg.confidence_threshold = root["detection"]["confidence_threshold"].as<float>();

        if (root["depth"]["temporal_smoothing_frames"])
            cfg.temporal_smoothing_frames = root["depth"]["temporal_smoothing_frames"].as<int>();
        if (root["depth"]["calibration"]["scale"])
            cfg.depth_scale = root["depth"]["calibration"]["scale"].as<float>();
        if (root["depth"]["calibration"]["offset"])
            cfg.depth_offset = root["depth"]["calibration"]["offset"].as<float>();
        if (root["depth"]["calibration"]["min_distance"])
            cfg.min_distance = root["depth"]["calibration"]["min_distance"].as<float>();
        if (root["depth"]["calibration"]["max_distance"])
            cfg.max_distance = root["depth"]["calibration"]["max_distance"].as<float>();

        if (root["tracking"]["alert_cooldown_seconds"])
            cfg.alert_cooldown_seconds = root["tracking"]["alert_cooldown_seconds"].as<float>();
        if (root["tracking"]["min_tracked_frames"])
            cfg.min_tracked_frames = root["tracking"]["min_tracked_frames"].as<int>();
        if (root["tracking"]["max_lost_frames"])
            cfg.max_lost_frames = root["tracking"]["max_lost_frames"].as<int>();

        if (root["direction"]["left_boundary"])
            cfg.left_boundary = root["direction"]["left_boundary"].as<float>();
        if (root["direction"]["right_boundary"])
            cfg.right_boundary = root["direction"]["right_boundary"].as<float>();

        if (root["decision"]["thresholds"]["urgent"])
            cfg.urgent_threshold = root["decision"]["thresholds"]["urgent"].as<float>();
        if (root["decision"]["thresholds"]["warning"])
            cfg.warning_threshold = root["decision"]["thresholds"]["warning"].as<float>();
        if (root["decision"]["thresholds"]["info"])
            cfg.info_threshold = root["decision"]["thresholds"]["info"].as<float>();

        if (root["display"]["show_window"])
            cfg.show_window = root["display"]["show_window"].as<bool>();

    } catch (const std::exception& e) {
        std::cerr << "Config load warning: " << e.what() << " (using defaults)" << std::endl;
    }

    return cfg;
}

int main(int argc, char** argv) {
    std::string config_path = "config.yaml";
    bool headless = false;

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--config") == 0 && i + 1 < argc)
            config_path = argv[++i];
        else if (strcmp(argv[i], "--no-display") == 0)
            headless = true;
        else if (strcmp(argv[i], "--help") == 0) {
            std::cout << "AI Navigation Assistant (Mobile C++ Port)\n"
                      << "Usage: " << argv[0] << " [options]\n"
                      << "  --config <path>   Config file path (default: config.yaml)\n"
                      << "  --no-display      Disable display window (headless mode)\n"
                      << "  --help            Show this help\n";
            return 0;
        }
    }

    Config config = load_config(config_path);
    if (headless) config.show_window = false;

    std::cout << "AI Navigation Assistant — Mobile C++ Port\n";
    std::cout << "========================================\n";

    Pipeline pipeline(config);
    return pipeline.run();
}
