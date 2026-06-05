#include <opencv2/opencv.hpp>
#include <print>
#include "MJPEGCapture.hpp"

int main(int argc, char **argv) {
    if (argc < 2) {
        std::println("Usage: {} <at least 2 mjpeg stream urls>", argv[0]);
        return -1;
    }
    std::vector<std::unique_ptr<MJPEGCapture>> captures;
    captures.reserve(argc - 1);
    for (int i = 1; i < argc; ++i) {
        captures.push_back(std::make_unique<MJPEGCapture>(argv[i]));
    }


    for (size_t i = 0; i < captures.size(); ++i)
        cv::namedWindow(std::string("cam") + std::to_string(i), cv::WINDOW_AUTOSIZE);

    std::vector<cv::Mat> mats(captures.size());
    for (;;) {
        for (size_t idx = 0; idx < captures.size(); ++idx) {
            auto &capture = captures[idx];
            auto &mat = mats[idx];
            if (capture->read(mat) && !mat.empty()) cv::imshow(std::string("cam") + std::to_string(idx), mat);
        }

        int key = cv::waitKey(30);
        if (key == 27 || key == 'q') break;
    }

    cv::destroyAllWindows();

    return 0;
}
