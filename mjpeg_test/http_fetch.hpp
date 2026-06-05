#pragma once
#include <string>
#include <vector>
#include <curl/curl.h>

static size_t curlWriteCb(void *ptr, size_t size, size_t nmemb, void *userdata) {
    auto *buf = static_cast<std::vector<unsigned char>*>(userdata);
    size_t total = size * nmemb;
    const unsigned char *cptr = static_cast<const unsigned char*>(ptr);
    buf->insert(buf->end(), cptr, cptr + total);
    return total;
}

inline bool httpGetToBuffer(const std::string &url, std::vector<unsigned char> &outBuf, long timeoutMs = 2000) {
    CURL *curl = curl_easy_init();
    if(!curl) return false;
    outBuf.clear();
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curlWriteCb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &outBuf);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, timeoutMs);
    // optional: low overhead
    curl_easy_setopt(curl, CURLOPT_TCP_KEEPALIVE, 1L);
    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    return res == CURLE_OK && !outBuf.empty();
}
