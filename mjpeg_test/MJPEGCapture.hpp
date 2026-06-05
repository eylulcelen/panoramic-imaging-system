#pragma once
#include "ICapture.hpp"
#include <atomic>
#include <thread>
#include <mutex>
#include <vector>
#include <string>
#include <curl/curl.h>
#include <opencv2/opencv.hpp>

class MJPEGCapture : public ICapture {
public:
    explicit MJPEGCapture(const std::string &url);
    ~MJPEGCapture();
    bool read(cv::Mat &frame) override;
private:
    void run();
    static size_t curlWriteCallback(char *ptr, size_t size, size_t nmemb, void *userdata);
    static int curlXferInfo(void *clientp,
                      curl_off_t dltotal,
                      curl_off_t dlnow,
                      curl_off_t ultotal,
                      curl_off_t ulnow);

    std::string url_;
    std::thread worker_;
    std::atomic<bool> stop_{false};

    std::mutex mtx_;
    cv::Mat latest_frame_;
    bool has_frame_ = false;

    // buffer for partial data
    std::vector<unsigned char> buffer_;
    CURL *curl_handle_ = nullptr;
};
