import math
import urllib.request
import threading
from typing import List, Optional

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# MJPEG capture helper (mirrors MJPEGCapture.hpp)
# ---------------------------------------------------------------------------

class MJPEGCapture:
    """
    Fetches frames from an MJPEG-over-HTTP stream using OpenCV's VideoCapture.
    Falls back to urllib byte-stream parsing if cv2.VideoCapture can't open
    the URL directly.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._cap = cv2.VideoCapture(url)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open MJPEG stream: {url}")

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        """Return (ok, frame).  Frame is BGR uint8."""
        return self._cap.read()

    def release(self) -> None:
        self._cap.release()


# ---------------------------------------------------------------------------
# VideoStitcher
# ---------------------------------------------------------------------------

class VideoStitcher:
    """
    Offline-calibration + per-frame stitching pipeline.

    Parameters mirror the C++ struct defaults:
        work_megapix   = 0.6
        seam_megapix   = 0.1
        match_conf     = 0.3
        conf_thresh    = 1.0
        range_width    = -1   (-1 → BestOf2Nearest, else BestOf2NearestRange)
        try_cuda       = False  (True only if CUDA build available)
        do_wave_correct = True
        expos_comp_type = cv2.detail.ExposureCompensator_GAIN_BLOCKS
        blend_type      = cv2.detail.Blender_FEATHER
        blend_strength  = 5.0
        compose_megapix = -1  (no downscale at compose time)
    """

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        urls: List[str],
        *,
        work_megapix: float = 0.6,
        seam_megapix: float = 0.1,
        match_conf: float = 0.3,
        conf_thresh: float = 1.0,
        range_width: int = -1,
        try_cuda: bool = False,
        do_wave_correct: bool = True,
        expos_comp_type: int = cv2.detail.ExposureCompensator_GAIN_BLOCKS,
        expos_comp_nr_feeds: int = 1,
        expos_comp_nr_filtering: int = 2,
        expos_comp_block_size: int = 32,
        compose_megapix: float = -1.0,
        blend_type: int = cv2.detail.Blender_FEATHER,
        blend_strength: float = 5.0,
    ) -> None:

        if len(urls) < 2:
            raise ValueError("Need at least 2 capture URLs.")

        self.capture_names: List[str] = list(urls)
        self.work_megapix = work_megapix
        self.seam_megapix = seam_megapix
        self.match_conf = match_conf
        self.conf_thresh = conf_thresh
        self.range_width = range_width
        self.try_cuda = try_cuda
        self.do_wave_correct = do_wave_correct
        self.expos_comp_type = expos_comp_type
        self.expos_comp_nr_feeds = expos_comp_nr_feeds
        self.expos_comp_nr_filtering = expos_comp_nr_filtering
        self.expos_comp_block_size = expos_comp_block_size
        self.compose_megapix = compose_megapix
        self.blend_type = blend_type
        self.blend_strength = blend_strength

        # Set during setup()
        self._ready = False

        self._setup()

    # ----------------------------------------------------------------- setup

    def _setup(self) -> None:
        """Calibration phase – runs once at construction."""

        # --- open captures ------------------------------------------------
        self._captures: List[MJPEGCapture] = []
        for url in self.capture_names:
            if url.startswith("http://") or url.startswith("https://"):
                self._captures.append(MJPEGCapture(url))
            else:
                raise ValueError(f"Only HTTP(S) URLs are supported, got: {url}")

        num = len(self._captures)

        # --- read first frames + feature detection -----------------------
        finder = cv2.SIFT_create()

        full_imgs: List[np.ndarray] = []
        full_img_sizes: List[tuple] = []
        seam_imgs: List[np.ndarray] = []
        features: List[cv2.detail.ImageFeatures] = []

        work_scale = 1.0
        seam_scale = 1.0
        seam_work_aspect = 1.0
        is_work_scale_set = False
        is_seam_scale_set = False

        for i, cap in enumerate(self._captures):
            # Busy-wait for first valid frame
            ok, full_img = False, None
            while not ok or full_img is None or full_img.size == 0:
                ok, full_img = cap.read()

            h, w = full_img.shape[:2]
            full_img_sizes.append((w, h))

            # Work scale
            if self.work_megapix < 0:
                img = full_img
                work_scale = 1.0
                is_work_scale_set = True
            else:
                if not is_work_scale_set:
                    work_scale = min(1.0, math.sqrt(self.work_megapix * 1e6 / (w * h)))
                    is_work_scale_set = True
                img = cv2.resize(full_img, None, fx=work_scale, fy=work_scale,
                                 interpolation=cv2.INTER_LINEAR_EXACT)

            # Seam scale
            if not is_seam_scale_set:
                seam_scale = min(1.0, math.sqrt(self.seam_megapix * 1e6 / (w * h)))
                seam_work_aspect = seam_scale / work_scale
                is_seam_scale_set = True

            # Feature detection on work-scale image
            feat = cv2.detail.computeImageFeatures2(finder, img)
            feat.img_idx = i
            features.append(feat)
            print(f"Features in image #{i+1}: {len(feat.keypoints)}")

            seam_img = cv2.resize(full_img, None, fx=seam_scale, fy=seam_scale,
                                  interpolation=cv2.INTER_LINEAR_EXACT)
            seam_imgs.append(seam_img)
            full_imgs.append(full_img)

        # --- feature matching --------------------------------------------
        if self.range_width == -1:
            matcher = cv2.detail.BestOf2NearestMatcher_create(
                self.try_cuda, self.match_conf)
        else:
            matcher = cv2.detail.BestOf2NearestRangeMatcher_create(
                self.range_width, self.try_cuda, self.match_conf)

        pairwise_matches = matcher.apply2(features)
        matcher.collectGarbage()

        # --- keep only the biggest connected component -------------------
        indices = cv2.detail.leaveBiggestComponent(
            features, pairwise_matches, self.conf_thresh)

        if len(indices) < 2:
            raise RuntimeError("Not enough overlapping images after component filtering.")

        seam_imgs      = [seam_imgs[i]      for i in indices]
        full_img_sizes = [full_img_sizes[i] for i in indices]
        self.capture_names = [self.capture_names[i] for i in indices]
        self._captures     = [self._captures[i]     for i in indices]
        num = len(indices)

        # --- homography estimation ---------------------------------------
        estimator = cv2.detail_HomographyBasedEstimator()
        ok, cameras = estimator.apply(features, pairwise_matches, None)
        if not ok:
            raise RuntimeError("Homography estimation failed.")

        # Convert rotation matrices to float32
        for cam in cameras:
            cam.R = cam.R.astype(np.float32)

        # --- bundle adjustment -------------------------------------------
        adjuster = cv2.detail_BundleAdjusterRay()
        adjuster.setConfThresh(self.conf_thresh)

        refine_mask = np.ones((3, 3), dtype=np.uint8)   # "xxxxx" → all 1s
        adjuster.setRefinementMask(refine_mask)

        ok, cameras = adjuster.apply(features, pairwise_matches, cameras)
        if not ok:
            raise RuntimeError("Camera parameter adjustment failed.")

        # --- median focal length -----------------------------------------
        focals = sorted(cam.focal for cam in cameras)
        n = len(focals)
        if n % 2 == 1:
            warped_image_scale = float(focals[n // 2])
        else:
            warped_image_scale = float(focals[n // 2 - 1] + focals[n // 2]) * 0.5

        # --- wave correction ---------------------------------------------
        if self.do_wave_correct:
            rmats = [cam.R.copy() for cam in cameras]
            rmats = cv2.detail.waveCorrect(rmats, cv2.detail.WAVE_CORRECT_HORIZ)
            for cam, R in zip(cameras, rmats):
                cam.R = R

        # --- auxiliary warping (seam-scale) ------------------------------
        warper = cv2.PyRotationWarper("spherical", float(warped_image_scale * seam_work_aspect))
        #warper = warper_creator.create(float(warped_image_scale * seam_work_aspect))

        corners: List[tuple] = []
        sizes: List[tuple] = []
        imgs_warped: List[np.ndarray] = []
        masks_warped: List[np.ndarray] = []

        for i, (img_s, cam) in enumerate(zip(seam_imgs, cameras)):
            K = cam.K().astype(np.float32)
            swa = float(seam_work_aspect)
            K[0, 0] *= swa; K[0, 2] *= swa
            K[1, 1] *= swa; K[1, 2] *= swa

            corner, img_w = warper.warp(img_s, K, cam.R,
                                        cv2.INTER_LINEAR, cv2.BORDER_REFLECT)
            corners.append(corner)
            sizes.append((img_w.shape[1], img_w.shape[0]))
            imgs_warped.append(img_w)

            mask = 255 * np.ones(img_s.shape[:2], dtype=np.uint8)
            _, mask_w = warper.warp(mask, K, cam.R,
                                    cv2.INTER_NEAREST, cv2.BORDER_CONSTANT)
            masks_warped.append(mask_w)

        imgs_warped_f = [iw.astype(np.float32) for iw in imgs_warped]

        # --- exposure compensation ---------------------------------------
        compensator = cv2.detail.ExposureCompensator_createDefault(
            self.expos_comp_type)

        if isinstance(compensator, cv2.detail.GainCompensator):
            compensator.setNrFeeds(self.expos_comp_nr_feeds)
        elif isinstance(compensator, cv2.detail.ChannelsCompensator):
            compensator.setNrFeeds(self.expos_comp_nr_feeds)
        elif isinstance(compensator, cv2.detail.BlocksCompensator):
            compensator.setNrFeeds(self.expos_comp_nr_feeds)
            compensator.setNrGainsFilteringIterations(self.expos_comp_nr_filtering)
            compensator.setBlockSize(self.expos_comp_block_size,
                                     self.expos_comp_block_size)

        compensator.feed(corners, imgs_warped, masks_warped)

        # --- seam finding ------------------------------------------------
        seam_finder = cv2.detail_GraphCutSeamFinder("COST_COLOR")
        seam_finder.find(imgs_warped_f, corners, masks_warped)

        # --- compose-scale update ----------------------------------------
        compose_scale = 1.0
        is_compose_scale_set = False

        # We need a representative full_img size; use the first image's size
        first_w, first_h = full_img_sizes[0]

        if not is_compose_scale_set:
            if self.compose_megapix > 0:
                compose_scale = min(1.0,
                    math.sqrt(self.compose_megapix * 1e6 / (first_w * first_h)))
            is_compose_scale_set = True

        compose_work_aspect = compose_scale / work_scale

        # Recreate warper at full compose scale
        #warper = warper_creator.create(float(warped_image_scale * compose_work_aspect))
        warper = cv2.PyRotationWarper("spherical", float(warped_image_scale * seam_work_aspect))

        compose_corners: List[tuple] = []
        compose_sizes: List[tuple] = []

        for i, cam in enumerate(cameras):
            cam.focal *= compose_work_aspect
            cam.ppx   *= compose_work_aspect
            cam.ppy   *= compose_work_aspect

            w, h = full_img_sizes[i]
            if abs(compose_scale - 1.0) > 1e-1:
                w = round(w * compose_scale)
                h = round(h * compose_scale)
            sz = (w, h)

            K = cam.K().astype(np.float32)
            roi = warper.warpRoi(sz, K, cam.R)
            compose_corners.append((roi[0], roi[1]))
            compose_sizes.append((roi[2], roi[3]))

        # --- precompute per-camera K matrices and dilated seam masks -----
        struct_elem = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        K_store: List[np.ndarray] = []
        dilated_masks: List[np.ndarray] = []

        for i, cam in enumerate(cameras):
            K = cam.K().astype(np.float32)
            K_store.append(K)

            dilated = cv2.dilate(masks_warped[i], struct_elem)
            target_sz = (compose_sizes[i][0], compose_sizes[i][1])
            if dilated.shape[::-1] != target_sz:
                dilated = cv2.resize(dilated, target_sz, interpolation=cv2.INTER_LINEAR)
            dilated_masks.append(dilated)

        # --- blender -----------------------------------------------------
        blender = cv2.detail.Blender_createDefault(self.blend_type, self.try_cuda)
        dst_area = sum(s[0] * s[1] for s in compose_sizes)
        blend_width = math.sqrt(dst_area) * self.blend_strength / 100.0

        if blend_width < 1.0:
            blender = cv2.detail.Blender_createDefault(
                cv2.detail.Blender_NO, self.try_cuda)
        elif self.blend_type == cv2.detail.Blender_MULTI_BAND:
            mb: cv2.detail.MultiBandBlender = blender
            num_bands = int(math.ceil(math.log(blend_width) / math.log(2))) - 1
            mb.setNumBands(num_bands)
        elif self.blend_type == cv2.detail.Blender_FEATHER:
            fb: cv2.detail.FeatherBlender = blender
            #fb.setSharpness(1.0 / blend_width)

        # --- store all state needed by get_next_frame --------------------
        self._num = num
        self._cameras = cameras
        self._warper = warper
        self._K_store = K_store
        self._corners = compose_corners
        self._sizes = compose_sizes
        self._masks_warped = masks_warped          # seam masks (seam scale)
        self._dilated_masks = dilated_masks        # dilated, resized to compose
        self._compensator = compensator
        self._blender = blender
        self._compose_scale = compose_scale
        self._struct_elem = struct_elem
        self._ready = True

    # --------------------------------------------------------- get_next_frame

    def get_next_frame(self) -> tuple[int, Optional[np.ndarray]]:
        """
        Capture one frame from each stream, stitch, and return the panorama.

        Returns:
            (status, frame)
            status == 0 on success, 1 if not ready, -1 on read failure.
            frame is a BGR uint8 numpy array, or None on failure.
        """
        if not self._ready:
            return 1, None

        self._blender.prepare(self._corners, self._sizes)

        warped_s_list: List[np.ndarray] = []
        mask_list: List[np.ndarray] = []

        for idx, cap in enumerate(self._captures):
            # 1) Grab frame
            ok, frame = cap.read()
            if not ok or frame is None:
                return -1, None

            # 2) Resize to compose scale if needed
            if abs(self._compose_scale - 1.0) > 1e-1:
                target = (round(frame.shape[1] * self._compose_scale),
                          round(frame.shape[0] * self._compose_scale))
                img_to_warp = cv2.resize(frame, target, interpolation=cv2.INTER_LINEAR)
            else:
                img_to_warp = frame

            K = self._K_store[idx]
            cam = self._cameras[idx]

            # 3) Warp image
            _, warped = self._warper.warp(
                img_to_warp, K, cam.R, cv2.INTER_LINEAR, cv2.BORDER_REFLECT)

            # 4) Warp mask
            src_mask = 255 * np.ones(img_to_warp.shape[:2], dtype=np.uint8)
            _, mask_warped = self._warper.warp(
                src_mask, K, cam.R, cv2.INTER_NEAREST, cv2.BORDER_CONSTANT)

            # 5) Exposure compensation (in-place)
            self._compensator.apply(idx, self._corners[idx], warped, mask_warped)

            # 6) Convert to int16 for blender
            warped_s = warped.astype(np.int16)

            # 7) AND seam mask with warp mask
            dilated = self._dilated_masks[idx]
            if dilated.shape != mask_warped.shape:
                dilated = cv2.resize(dilated, (mask_warped.shape[1], mask_warped.shape[0]),
                                     interpolation=cv2.INTER_LINEAR)
            seam_mask = cv2.bitwise_and(dilated, mask_warped)

            warped_s_list.append(warped_s)
            mask_list.append(seam_mask)

        # Feed blender sequentially
        for i in range(self._num):
            self._blender.feed(warped_s_list[i], mask_list[i], self._corners[i])

        result, result_mask = self._blender.blend(None, None)

        # Convert int16 blender output back to uint8
        panorama = np.clip(result, 0, 255).astype(np.uint8)
        return 0, panorama

    # ---------------------------------------------------------------- cleanup

    def release(self) -> None:
        """Release all capture resources."""
        for cap in self._captures:
            cap.release()
        self._ready = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        urls = sys.argv[1:]
    else: 
        print("Expected at least 2 MJPEG stream URLs as arguments")
        sys.exit(1)
    print(f"Opening streams: {urls}")
    with VideoStitcher(urls) as stitcher:
        print("Calibration done. Streaming panorama - press ESC to quit.")
        while True:
            status, frame = stitcher.get_next_frame()
            if status != 0 or frame is None:
                print(f"Frame error (status={status}), retrying…")
                continue
            cv2.imshow("Panorama", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    cv2.destroyAllWindows()
