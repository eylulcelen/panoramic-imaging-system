#include "MJPEGCapture.hpp"

MJPEGCapture::MJPEGCapture(const std::string &url) : url_(url) {
    curl_global_init(CURL_GLOBAL_DEFAULT);
    curl_handle_ = curl_easy_init();
    if (!curl_handle_) return;
    /* https://curl.se/libcurl/c/easy_setopt_options.html */
    curl_easy_setopt(curl_handle_, CURLOPT_URL, url_.c_str());
    curl_easy_setopt(curl_handle_, CURLOPT_WRITEFUNCTION, curlWriteCallback);
    curl_easy_setopt(curl_handle_, CURLOPT_WRITEDATA, this);
    curl_easy_setopt(curl_handle_, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(curl_handle_, CURLOPT_FOLLOWLOCATION, 1L);

    /* Continuous MJPEG stream would block the destructor when joining the
     * worker so set progress */
    curl_easy_setopt(curl_handle_, CURLOPT_XFERINFOFUNCTION, curlXferInfo);
    curl_easy_setopt(curl_handle_, CURLOPT_XFERINFODATA, this);
    curl_easy_setopt(curl_handle_, CURLOPT_NOPROGRESS, 0L);

    /* Continuous MJPEG stream would block the constructor when
     * curl_easy_perform is ran, putting this on a worker thread */
    worker_ = std::thread(&MJPEGCapture::run, this);
}

MJPEGCapture::~MJPEGCapture() {
    stop_ = true;
    if (worker_.joinable()) worker_.join();
    if (curl_handle_) curl_easy_cleanup(curl_handle_);
    curl_global_cleanup();
}

size_t MJPEGCapture::curlWriteCallback(char *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t total = size * nmemb;
    MJPEGCapture *self = static_cast<MJPEGCapture*>(userdata);
    std::lock_guard<std::mutex> lock(self->mtx_);
    if (!self) return total;
    self->buffer_.insert(self->buffer_.end(), (unsigned char*)ptr, (unsigned char*)ptr + total);
    return total;
}

void MJPEGCapture::run() {
    while (!stop_) {
        CURLcode res = curl_easy_perform(curl_handle_);
        if (res != CURLE_OK) {
            // sleep briefly and retry
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            continue;
        }
    }
}

int MJPEGCapture::curlXferInfo(void *clientp,
                      curl_off_t dltotal,
                      curl_off_t dlnow,
                      curl_off_t ultotal,
                      curl_off_t ulnow) {
    MJPEGCapture *self = static_cast<MJPEGCapture*>(clientp);
    if (!self) return 0;
    return self->stop_.load() ? 1 /*non-zero abort*/ : 0;
}

bool MJPEGCapture::read(cv::Mat &frame) {
    std::lock_guard<std::mutex> lock(mtx_);
    std::vector<unsigned char> local_buf;
    {
        if (buffer_.empty()) {
            if (!has_frame_) return false;
            latest_frame_.copyTo(frame);
            return true;
        }
        local_buf.swap(buffer_); // take the accumulated bytes
    }

    // Find JPEG start/end in local_buf
    size_t start = std::string::npos, end = std::string::npos;
    for (size_t i = 0; i + 1 < local_buf.size(); ++i) {
        if (local_buf[i] == 0xFF && local_buf[i+1] == 0xD8) { start = i; break; }
    }
    if (start == std::string::npos) {
        // no start yet, keep buffer for next time
        buffer_.insert(buffer_.end(), local_buf.begin(), local_buf.end());
        if (!has_frame_) return false;
        latest_frame_.copyTo(frame);
        return true;
    }
    for (size_t i = start + 2; i + 1 < local_buf.size(); ++i) {
        if (local_buf[i] == 0xFF && local_buf[i+1] == 0xD9) { end = i+1; break; }
    }
    if (end == std::string::npos) {
        // incomplete JPEG, keep data
        buffer_.insert(buffer_.end(), local_buf.begin(), local_buf.end());
        if (!has_frame_) return false;
        latest_frame_.copyTo(frame);
        return true;
    }

    std::vector<unsigned char> jpegbuf(local_buf.begin()+start, local_buf.begin()+end+1);
    cv::Mat img = cv::imdecode(jpegbuf, cv::IMREAD_COLOR);
    if (!img.empty()) {
        img.copyTo(latest_frame_);
        has_frame_ = true;
        latest_frame_.copyTo(frame);
    } else {
        if (has_frame_) latest_frame_.copyTo(frame);
        else return false;
    }

    // push remaining bytes back into buffer_
    {
        if (end+1 < local_buf.size())
            buffer_.insert(buffer_.end(), local_buf.begin()+end+1, local_buf.end());
    }
    return true;
}
