"""
stitch.py — OpenCV panoramic stitching pipeline.
Supports SIFT (accurate) and ORB (fast) feature detectors.
"""

import cv2
import numpy as np


def stitch_images(left_path="img_left.jpg",
                  right_path="img_right.jpg",
                  out_path="panorama.jpg",
                  method="SIFT"):
    """
    Stitch two overlapping images into a panorama.
    method: "SIFT" (accurate, slower) or "ORB" (fast, less accurate)
    Returns out_path on success, raises Exception on failure.
    """
    img_left  = cv2.imread(left_path)
    img_right = cv2.imread(right_path)

    if img_left is None:
        raise Exception("Could not read left image — capture may have failed.")
    if img_right is None:
        raise Exception("Could not read right image — capture may have failed.")

    # 1. Feature detection
    if method == "ORB":
        detector = cv2.ORB_create(nfeatures=2000)
        norm     = cv2.NORM_HAMMING
    else:
        detector = cv2.SIFT_create()
        norm     = cv2.NORM_L2

    kp1, des1 = detector.detectAndCompute(img_left,  None)
    kp2, des2 = detector.detectAndCompute(img_right, None)

    if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
        raise Exception("Feature detection failed — check image overlap.")

    # 2. Feature matching with ratio test
    matcher     = cv2.BFMatcher(norm)
    raw_matches = matcher.knnMatch(des1, des2, k=2)
    good        = [m for m, n in raw_matches if m.distance < 0.75 * n.distance]

    print(f"[stitch] Good matches: {len(good)} (method={method})")

    if len(good) < 10:
        raise Exception(
            f"Only {len(good)} good matches — cameras need more overlap (~30%)."
        )

    # 3. Homography estimation
    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(dst, src, cv2.RANSAC, 5.0)

    if H is None:
        raise Exception("Homography failed — images may not overlap enough.")

    print(f"[stitch] Inliers: {int(mask.sum()) if mask is not None else 0}")

    # 4. Warp and blend
    h1, w1 = img_left.shape[:2]
    h2, w2 = img_right.shape[:2]

    warped = cv2.warpPerspective(img_right, H, (w1 + w2, max(h1, h2)))
    warped[0:h1, 0:w1] = img_left

    # 5. Crop black borders
    gray   = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    _, thr = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
    coords = cv2.findNonZero(thr)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        warped = warped[y:y + h, x:x + w]

    cv2.imwrite(out_path, warped, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[stitch] Saved → {out_path}")
    return out_path