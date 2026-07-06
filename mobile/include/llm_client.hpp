#pragma once
#include <string>

class LLMClient {
public:
#ifdef __ANDROID__
    LLMClient() {}
    ~LLMClient() {}
    void request_scene_description(const std::string& base64_image) {}
#else
    LLMClient();
    ~LLMClient();
    void request_scene_description(const std::string& base64_image);
#endif

private:
    std::string api_url_ = "http://localhost:1234/v1/chat/completions";
};
