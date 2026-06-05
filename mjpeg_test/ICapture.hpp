#pragma once
#include <opencv2/opencv.hpp>
#include <string>

struct ICapture {
    virtual ~ICapture() = default;
    virtual bool read(cv::Mat &frame) = 0;
};
