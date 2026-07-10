#include "llm_client.hpp"
#include <iostream>
#include <curl/curl.h>

static size_t WriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    ((std::string*)userp)->append((char*)contents, size * nmemb);
    return size * nmemb;
}

LLMClient::LLMClient() {
    curl_global_init(CURL_GLOBAL_DEFAULT);
}

LLMClient::~LLMClient() {
    curl_global_cleanup();
}

void LLMClient::request_scene_description(const std::string& base64_image) {
    CURL* curl = curl_easy_init();
    if (curl) {
        struct curl_slist* headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");

        // Manually construct JSON to avoid needing another dependency
        std::string json_data = "{"
            "\"messages\": [{"
                "\"role\": \"user\","
                "\"content\": ["
                    "{\"type\": \"text\", \"text\": \"What is in front of me?\" },"
                    "{\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/jpeg;base64," + base64_image + "\"}}"
                "]"
            "}],"
            "\"temperature\": 0.4,"
            "\"max_tokens\": 60"
        "}";

        std::string readBuffer;

        curl_easy_setopt(curl, CURLOPT_URL, api_url_.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_data.c_str());
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &readBuffer);
        
        // Timeout so it doesn't block UI forever
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);

        CURLcode res = curl_easy_perform(curl);
        if (res != CURLE_OK) {
            std::cerr << "[LLM] curl_easy_perform() failed: " << curl_easy_strerror(res) << std::endl;
        } else {
            std::cout << "[LLM Response]: " << readBuffer << std::endl;
            // In a full implementation, you'd parse this JSON to extract the "content" and pass it to TTS.
        }

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
    }
}
