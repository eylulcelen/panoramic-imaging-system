/* https://docs.opencv.org/4.x/d9/dd8/samples_2cpp_2stitching_detailed_8cpp-example.html */
#include "video_stitcher.hpp"
#include "MJPEGCapture.hpp"
#include <vector>

VideoStitcher::VideoStitcher(std::vector<std::string> file_names) {
    capture_names = file_names;
    if (this->setup()) throw new std::exception;
}

int VideoStitcher::setup() {
    num_captures = static_cast<int>(capture_names.size());
    if (num_captures < 2)
    {
        LOGLN("Need more images");
        return -1;
    }
    for (auto &capture_name : capture_names) {
        if (capture_name.rfind("http://",0) == 0 || capture_name.rfind("https://",0) == 0) {
            captures.emplace_back(std::make_unique<MJPEGCapture>(capture_name));
        } else {
            return -2;
        }
    }


    std::vector<cv::Mat> images(captures.size());
    full_img_sizes = std::vector<cv::Size>(captures.size());
    cv::Ptr<cv::Feature2D> finder = cv::SIFT::create();
    std::vector<cv::detail::ImageFeatures>features(captures.size());

    cv::Mat full_img, img;

    for (int i = 0; i < captures.size(); ++i) {
        /* Busy wait until the first image */
        while(!captures[i]->read(full_img));

        if (full_img.empty())
        {
            LOGLN("Can't open capture " << capture_names[i]);
            return -1;
        }
        full_img_sizes[i] = full_img.size();

        if (work_megapix < 0)
        {
            img = full_img;
            work_scale = 1;
            is_work_scale_set = true;
        }
        else
        {
            if (!is_work_scale_set)
            {
                work_scale = std::min(1.0, std::sqrt(work_megapix * 1e6 / full_img.size().area()));
                is_work_scale_set = true;
            }
            resize(full_img, img, cv::Size(), work_scale, work_scale, cv::INTER_LINEAR_EXACT);
        }
        if (!is_seam_scale_set)
        {
            seam_scale = std::min(1.0, sqrt(seam_megapix * 1e6 / full_img.size().area()));
            seam_work_aspect = seam_scale / work_scale;
            is_seam_scale_set = true;
        }

        LOGLN("Finding features...");
        cv::detail::computeImageFeatures(finder, img, features[i]);
        features[i].img_idx = i;
        LOGLN("Features in image #" << i+1 << ": " << features[i].keypoints.size());
        resize(full_img, img, cv::Size(), seam_scale, seam_scale, cv::INTER_LINEAR_EXACT);
        images[i] = img.clone();
    }
    full_img.release();
    img.release();

    std::vector<cv::detail::MatchesInfo> pairwise_matches;
    cv::Ptr<cv::detail::FeaturesMatcher> matcher;

    if (range_width==-1) {
        matcher = cv::makePtr<cv::detail::BestOf2NearestMatcher>(try_cuda, match_conf);
    }
    else {
        matcher = cv::makePtr<cv::detail::BestOf2NearestRangeMatcher>( range_width, try_cuda, match_conf);
    }

    (*matcher)(features, pairwise_matches);
    matcher->collectGarbage();


    //LOGLN("Saving matches graph...");
    //std::ofstream f("matches.graph");
    //f << cv::detail::matchesGraphAsString(capture_names, pairwise_matches, conf_thresh);

    // Leave only images we are sure are from the same panorama
    indices = cv::detail::leaveBiggestComponent(
            features, pairwise_matches, conf_thresh);
    std::vector<cv::Mat> img_subset;
    std::vector<cv::String> img_names_subset;
    std::vector<cv::Size> full_img_sizes_subset;
    for (size_t i = 0; i < indices.size(); ++i)
    {
        img_names_subset.push_back(capture_names[indices[i]]);
        img_subset.push_back(images[indices[i]]);
        full_img_sizes_subset.push_back(full_img_sizes[indices[i]]);
    }

    images = img_subset;
    capture_names = img_names_subset;
    full_img_sizes = full_img_sizes_subset;

    // Check if we still have enough images
    num_captures = static_cast<int>(capture_names.size());
    if (num_captures < 2)
    {
        LOGLN("Need more images");
        return -1;
    }

    cv::Ptr<cv::detail::Estimator> estimator = cv::makePtr<cv::detail::HomographyBasedEstimator>();

    if (!(*estimator)(features, pairwise_matches, cameras))
    {
        LOGLN("Homography estimation failed.");
        return -1;
    }

    for (size_t i = 0; i < cameras.size(); ++i)
    {
        cv::Mat R;
        cameras[i].R.convertTo(R, CV_32F);
        cameras[i].R = R;
        LOGLN("Initial camera intrinsics #" << indices[i] + 1 << ":\nK:\n"
                << cameras[i].K() << "\nR:\n"
                << cameras[i].R);
    }

    cv::Ptr<cv::detail::BundleAdjusterBase> adjuster = cv::makePtr<cv::detail::BundleAdjusterRay>();

    const char *ba_refine_mask = "xxxxx";
    adjuster->setConfThresh(conf_thresh);
    cv::Mat_<uchar> refine_mask = cv::Mat::zeros(3, 3, CV_8U);
    if (ba_refine_mask[0] == 'x') refine_mask(0,0) = 1;
    if (ba_refine_mask[1] == 'x') refine_mask(0,1) = 1;
    if (ba_refine_mask[2] == 'x') refine_mask(0,2) = 1;
    if (ba_refine_mask[3] == 'x') refine_mask(1,1) = 1;
    if (ba_refine_mask[4] == 'x') refine_mask(1,2) = 1;
    adjuster->setRefinementMask(refine_mask);
    if (!(*adjuster)(features, pairwise_matches, cameras))
    {
        LOGLN("Camera parameters adjusting failed.");
        return -1;
    }

    // Find median focal length

    std::vector<double> focals;
    for (size_t i = 0; i < cameras.size(); ++i)
    {
        LOGLN("Camera #" << indices[i]+1 << ":\nK:\n" << cameras[i].K() << "\nR:\n" << cameras[i].R);
        focals.push_back(cameras[i].focal);
    }

    std::sort(focals.begin(), focals.end());
    if (focals.size() % 2 == 1)
        warped_image_scale = static_cast<float>(focals[focals.size() / 2]);
    else
        warped_image_scale = static_cast<float>(focals[focals.size() / 2 - 1] + focals[focals.size() / 2]) * 0.5f;

    if (do_wave_correct)
    {
        std::vector<cv::Mat> rmats;
        for (size_t i = 0; i < cameras.size(); ++i)
            rmats.push_back(cameras[i].R.clone());
        cv::detail::waveCorrect(rmats, wave_correct);
        for (size_t i = 0; i < cameras.size(); ++i)
            cameras[i].R = rmats[i];
    }

    LOGLN("Warping images (auxiliary)... ");

    corners = std::vector<cv::Point>(num_captures);
    masks_warped = std::vector<cv::UMat>(num_captures);
    sizes = std::vector<cv::Size>(num_captures);
    std::vector<cv::UMat> images_warped(num_captures);
    std::vector<cv::UMat> masks(num_captures);

    // Prepare images masks
    for (int i = 0; i < num_captures; ++i)
    {
        masks[i].create(images[i].size(), CV_8U);
        masks[i].setTo(cv::Scalar::all(255));
    }

    warper_creator = cv::makePtr<cv::SphericalWarper>();

    warper = warper_creator->create(
            static_cast<float>(warped_image_scale * seam_work_aspect));

    for (int i = 0; i < num_captures; ++i)
    {
        cv::Mat_<float> K;
        cameras[i].K().convertTo(K, CV_32F);
        float swa = (float)seam_work_aspect;
        K(0, 0) *= swa;
        K(0, 2) *= swa;
        K(1, 1) *= swa;
        K(1, 2) *= swa;

        corners[i] = warper->warp(images[i], K, cameras[i].R, cv::INTER_LINEAR,
                cv::BORDER_REFLECT, images_warped[i]);
        sizes[i] = images_warped[i].size();

        warper->warp(masks[i], K, cameras[i].R, cv::INTER_NEAREST,
                cv::BORDER_CONSTANT, masks_warped[i]);
    }

    std::vector<cv::UMat> images_warped_f(num_captures);
    for (int i = 0; i < num_captures; ++i)
        images_warped[i].convertTo(images_warped_f[i], CV_32F);

    compensator =
        cv::detail::ExposureCompensator::createDefault(expos_comp_type);
    if (dynamic_cast<cv::detail::GainCompensator *>(compensator.get())) {
        cv::detail::GainCompensator *gcompensator =
            dynamic_cast<cv::detail::GainCompensator *>(compensator.get());
        gcompensator->setNrFeeds(expos_comp_nr_feeds);
    }

    if (dynamic_cast<cv::detail::ChannelsCompensator *>(compensator.get())) {
        cv::detail::ChannelsCompensator *ccompensator =
            dynamic_cast<cv::detail::ChannelsCompensator *>(compensator.get());
        ccompensator->setNrFeeds(expos_comp_nr_feeds);
    }

    if (dynamic_cast<cv::detail::BlocksCompensator *>(compensator.get())) {
        cv::detail::BlocksCompensator *bcompensator =
            dynamic_cast<cv::detail::BlocksCompensator *>(compensator.get());
        bcompensator->setNrFeeds(expos_comp_nr_feeds);
        bcompensator->setNrGainsFilteringIterations(expos_comp_nr_filtering);
        bcompensator->setBlockSize(expos_comp_block_size, expos_comp_block_size);
    }

    compensator->feed(corners, images_warped, masks_warped);

    LOGLN("Finding seams...");

    cv::Ptr<cv::detail::SeamFinder> seam_finder = cv::makePtr<cv::detail::GraphCutSeamFinder>(cv::detail::GraphCutSeamFinderBase::COST_COLOR);

    seam_finder->find(images_warped_f, corners, masks_warped);

    // Release unused memory
    images.clear();
    images_warped.clear();
    images_warped_f.clear();
    masks.clear();


    double compose_work_aspect = 1;
    if (!is_compose_scale_set)
    {
        if (compose_megapix > 0)
            compose_scale = std::min(
                    1.0, sqrt(compose_megapix * 1e6 / full_img.size().area()));
        is_compose_scale_set = true;

        // Compute relative scales
        //compose_seam_aspect = compose_scale / seam_scale;
        compose_work_aspect = compose_scale / work_scale;

        // Update corners and sizes
        for (int i = 0; i < num_captures; ++i)
        {
            // Update intrinsics
            cameras[i].focal *= compose_work_aspect;
            cameras[i].ppx *= compose_work_aspect;
            cameras[i].ppy *= compose_work_aspect;

            // Update corner and size
            cv::Size sz = full_img_sizes[i];
            if (std::abs(compose_scale - 1) > 1e-1)
            {
                sz.width = cvRound(full_img_sizes[i].width * compose_scale);
                sz.height = cvRound(full_img_sizes[i].height * compose_scale);
            }

            cv::Mat K;
            cameras[i].K().convertTo(K, CV_32F);
            cv::Rect roi = warper->warpRoi(sz, K, cameras[i].R);
            corners[i] = roi.tl();
            sizes[i] = roi.size();
        }
    }

    K_store.resize(num_captures);
    warped_imgs_buf.resize(num_captures);
    warped_imgs_buf_s.resize(num_captures);
    mask_warped_buf.resize(num_captures);
    dilated_mask_resized_buf.resize(num_captures);

    // Precompute K_store and allocate target buffers
    for (int i = 0; i < num_captures; ++i) {
        cv::Mat K;
        cameras[i].K().convertTo(K, CV_32F);
        K_store[i] = K;

        const cv::Size &sz = sizes[i]; // size after warp/compose
                                       // Choose types matching your pipeline; example uses CV_8UC3 source, CV_16S for blender
        warped_imgs_buf[i].create(sz, CV_8UC3);
        warped_imgs_buf_s[i].create(sz, CV_16SC3); // keep same type as blender expects; change to CV_32F if you prefer
        mask_warped_buf[i].create(sz, CV_8U);
        dilated_mask_resized_buf[i].create(sz, CV_8U);
    }

    // Precompute a structuring element once
    structuring_element = cv::getStructuringElement(cv::MORPH_RECT, cv::Size(3,3));

    // Optionally precompute resized dilated mask once if masks_warped is static. Here we'll store resized version per camera:
    for (int i = 0; i < num_captures; ++i) {
        // dilate masks_warped[i] into a temporary and resize into dilated_mask_resized_buf[i]
        cv::Mat tmp;
        cv::dilate(masks_warped[i].getMat(cv::ACCESS_READ), tmp, structuring_element);
        if (tmp.size() != dilated_mask_resized_buf[i].size())
            cv::resize(tmp, dilated_mask_resized_buf[i], dilated_mask_resized_buf[i].size(), 0, 0, cv::INTER_LINEAR);
        else
            tmp.copyTo(dilated_mask_resized_buf[i]);
    }

    blender = cv::detail::Blender::createDefault(blend_type, try_cuda);
    cv::Size dst_sz = cv::detail::resultRoi(corners, sizes).size();
    float blend_width = std::sqrt(static_cast<float>(dst_sz.area())) *
        blend_strength / 100.f;
    if (blend_width < 1.f)
        blender = cv::detail::Blender::createDefault(
                cv::detail::Blender::NO, try_cuda);
    else if (blend_type == cv::detail::Blender::MULTI_BAND) {
        cv::detail::MultiBandBlender *mb =
            dynamic_cast<cv::detail::MultiBandBlender *>(blender.get());
        mb->setNumBands(
                static_cast<int>(ceil(std::log(blend_width) / log(2.)) - 1.));
        LOGLN("Multi-band blender, number of bands: " << mb->numBands());
    } else if (blend_type == cv::detail::Blender::FEATHER) {
        cv::detail::FeatherBlender *fb =
            dynamic_cast<cv::detail::FeatherBlender *>(blender.get());
        fb->setSharpness(1.f / blend_width);
        LOGLN("Feather blender, sharpness: " << fb->sharpness());
    }

    ready_ = true;
    return 0;
}


cv::Mat full_img, img;
cv::Mat img_warped, img_warped_s;
cv::Mat dilated_mask, seam_mask, mask, mask_warped;
cv::Mat result, result_mask;

int VideoStitcher::getNextFrame(cv::Mat &out) {
    if (!ready_.load()) { return 1; }
    blender->prepare(corners, sizes);

    for (int img_idx = 0; img_idx < num_captures; img_idx++) {
        // 1) Read next frame -> reuse a member full_img (local per-thread to avoid contention)
        cv::Mat frame;
        captures[img_idx]->read(frame);

        // 2) Resize to compose_scale into a preallocated temp if necessary
        cv::Mat img_to_warp;
        if (std::abs(compose_scale - 1.0) > 1e-1) {
            // reuse warped_imgs_buf's size as target is sizes[img_idx]
            cv::Size targetSz(cvRound(frame.cols * compose_scale), cvRound(frame.rows * compose_scale));
            // Use a thread-local temp for resizing to avoid races on shared buffers; then warp into shared buffer.
            static thread_local cv::Mat resize_tmp;
            resize_tmp.create(targetSz, frame.type());
            cv::resize(frame, resize_tmp, targetSz, 0, 0, cv::INTER_LINEAR);
            img_to_warp = resize_tmp;
        } else {
            img_to_warp = frame; // no copy
        }

        // 3) Warp into preallocated buffer (write directly into warped_imgs_buf[img_idx])
        // warper expects source mat; it writes to output buffer we pass
        warper->warp(img_to_warp, K_store[img_idx], cameras[img_idx].R, cv::INTER_LINEAR, cv::BORDER_REFLECT, warped_imgs_buf[img_idx]);

        // 4) Build mask_warped directly into preallocated mask_warped_buf
        // create a white mask of source size then warp
        static thread_local cv::Mat src_mask;
        src_mask.create(img_to_warp.size(), CV_8U);
        src_mask.setTo(255);
        warper->warp(src_mask, K_store[img_idx], cameras[img_idx].R, cv::INTER_NEAREST, cv::BORDER_CONSTANT, mask_warped_buf[img_idx]);

        // 5) Exposure compensation in-place on warped_imgs_buf[img_idx]
        compensator->apply(img_idx, corners[img_idx], warped_imgs_buf[img_idx], mask_warped_buf[img_idx]);

        // 6) Convert to blender type into preallocated warped_imgs_buf_s
        // Use the stored buffer to avoid allocate
        warped_imgs_buf[img_idx].convertTo(warped_imgs_buf_s[img_idx], warped_imgs_buf_s[img_idx].type());

        // 7) Compute seam mask: dilated_mask_resized_buf already precomputed; AND with mask_warped_buf
        // in-place AND into mask_warped_buf to avoid extra alloc
        cv::bitwise_and(dilated_mask_resized_buf[img_idx], mask_warped_buf[img_idx], mask_warped_buf[img_idx]);
    };

    // Sequentially feed blender (must be sequential unless your blender is thread-safe)
    for (int i = 0; i < num_captures; ++i) {
        blender->feed(warped_imgs_buf_s[i], mask_warped_buf[i], corners[i]);
    }

    // Blend result into preallocated result Mat
    blender->blend(result, result_mask);
    out = result; // copy header only (shallow copy) - if caller needs separate ownership, they can clone

    return 0;
}
