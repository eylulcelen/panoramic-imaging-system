#include <opencv2/opencv.hpp>
#include "opencv2/stitching.hpp"
#include "opencv2/opencv_modules.hpp"
#include "opencv2/stitching/detail/blenders.hpp"
#include "opencv2/stitching/detail/camera.hpp"
#include "opencv2/stitching/detail/exposure_compensate.hpp"
#include "opencv2/stitching/detail/matchers.hpp"
#include "opencv2/stitching/detail/motion_estimators.hpp"
#include "opencv2/stitching/detail/seam_finders.hpp"
#include "opencv2/stitching/detail/warpers.hpp"
#include "opencv2/stitching/warpers.hpp"

#include "ICapture.hpp"

#include <thread>
#include <memory>

#if 1
#define LOG(msg) std::cout << msg
#define LOGLN(msg) std::cout << msg << std::endl
#else
#define LOG(msg)
#define LOGLN(msg)
#endif

struct VideoStitcher {
    int num_captures;
    std::vector<int> indices;
    std::vector<std::string> capture_names;
    std::vector<std::unique_ptr<ICapture>> captures;
    cv::Ptr<cv::Stitcher> stitcher = cv::Stitcher::create(cv::Stitcher::PANORAMA);

    double work_scale = 1, seam_scale = 1, compose_scale = 1;
    bool is_work_scale_set = false, is_seam_scale_set = false, is_compose_scale_set = false;

    double seam_work_aspect = 1;

    // Default cmd args
    double work_megapix = 0.6;
    double seam_megapix = 0.1;
    float match_conf = 0.3f;
    int range_width = -1;
    bool try_cuda = true;
    float conf_thresh = 1.f;
    bool do_wave_correct = true;
    cv::detail::WaveCorrectKind wave_correct = cv::detail::WAVE_CORRECT_HORIZ;

    int expos_comp_type = cv::detail::ExposureCompensator::GAIN_BLOCKS;
    int expos_comp_nr_feeds = 1;
    int expos_comp_nr_filtering = 2;
    int expos_comp_block_size = 32;

    std::string seam_find_type = "gc_color";

    double compose_megapix = -1;
    int blend_type = cv::detail::Blender::FEATHER;
    float blend_strength = 5.f;

    float warped_image_scale;
    cv::Ptr<cv::detail::RotationWarper> warper;
    cv::Ptr<cv::WarperCreator> warper_creator;
    std::vector<cv::detail::CameraParams> cameras;

    std::vector<cv::Size>full_img_sizes;
    std::vector<cv::Point> corners;

    std::vector<cv::UMat>masks_warped;
    std::vector<cv::Size>sizes;

    cv::Ptr<cv::detail::ExposureCompensator> compensator;
    VideoStitcher(std::vector<std::string> file_names);
    cv::Ptr<cv::detail::Blender> blender;

    std::vector<cv::Mat> K_store;                       // CV_32F per camera
    std::vector<cv::Mat> warped_imgs_buf;               // per-camera preallocated warped image (CV_8U or CV_32F)
    std::vector<cv::Mat> warped_imgs_buf_s;             // per-camera converted buffer for blender (CV_16S or CV_32F)
    std::vector<cv::Mat> mask_warped_buf;               // per-camera mask
    std::vector<cv::Mat> dilated_mask_resized_buf;      // per-camera seam mask resized to mask_warped size
    cv::Mat structuring_element;                        // for dilation
    int thread_count = std::thread::hardware_concurrency()? std::thread::hardware_concurrency() : 4;

    std::atomic<bool> ready_{false};
    int setup();
    int getNextFrame(cv::Mat &out);
};
