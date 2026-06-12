import cv2 as cv
import numpy as np
import imutils

use_high_level_api = False

# Configuration
# TODO: seperate the config

PARAMS_FILE = 'params.npz'          # None or path – skips setup() entirely and loads saved params instead

WORK_MEGAPIX            = 0.6
SEAM_MEGAPIX            = 0.1
COMPOSE_MEGAPIX         = -1         # -1 = original resolution

FEATURES                = 'orb'      # orb | sift | brisk | akaze
MATCH_CONF              = 0.45       # None → 0.3 for orb, 0.65 otherwise
CONF_THRESH             = 1.0

MATCHER                 = 'homography'   # homography | affine
ESTIMATOR               = 'homography'   # homography | affine
RANGEWIDTH              = -1

BA                      = 'ray'          # ray | reproj | affine | no
BA_REFINE_MASK          = 'xxxxx'

WAVE_CORRECT            = 'horiz'        # horiz | vert | no
WARP                    = 'spherical'

SEAM                    = 'dp_color'     # dp_color | dp_colorgrad | voronoi | no

EXPOS_COMP              = 'gain_blocks'  # gain_blocks | gain | channel | channel_blocks | no
EXPOS_COMP_NR_FEEDS     = 1
EXPOS_COMP_NR_FILTERING = 2
EXPOS_COMP_BLOCK_SIZE   = 32

BLEND                   = 'multiband'    # multiband | feather | no
BLEND_STRENGTH          = 5

TRY_CUDA                = True
# TODO: Save and use the save graph after making the camera stand
SAVE_GRAPH              = None           # None or output path string

# Lookup dicts for a "better" PyThoNiC API 😔
EXPOS_COMP_MAP = {
    'gain_blocks':    cv.detail.ExposureCompensator_GAIN_BLOCKS,
    'gain':           cv.detail.ExposureCompensator_GAIN,
    'channel':        cv.detail.ExposureCompensator_CHANNELS,
    'channel_blocks': cv.detail.ExposureCompensator_CHANNELS_BLOCKS,
    'no':             cv.detail.ExposureCompensator_NO,
}

BA_COST_MAP = {
    'ray':    cv.detail_BundleAdjusterRay,
    'reproj': cv.detail_BundleAdjusterReproj,
    'affine': cv.detail_BundleAdjusterAffinePartial,
    'no':     cv.detail_NoBundleAdjuster,
}

FEATURES_MAP = {'orb': cv.ORB.create}
for _key, _attr in [('sift', 'SIFT_create'), ('brisk', 'BRISK_create'), ('akaze', 'AKAZE_create')]:
    _fn = getattr(cv, _attr, None)
    if _fn:
        FEATURES_MAP[_key] = _fn

SEAM_MAP = {
    'dp_color':     cv.detail_DpSeamFinder('COLOR'),
    'dp_colorgrad': cv.detail_DpSeamFinder('COLOR_GRAD'),
    'voronoi':      cv.detail.SeamFinder_createDefault(cv.detail.SeamFinder_VORONOI_SEAM),
    'no':           cv.detail.SeamFinder_createDefault(cv.detail.SeamFinder_NO),
}

ESTIMATOR_MAP = {
    'homography': cv.detail_HomographyBasedEstimator,
    'affine':     cv.detail_AffineBasedEstimator,
}

WAVE_CORRECT_MAP = {
    'horiz': cv.detail.WAVE_CORRECT_HORIZ,
    'no':    None,
    'vert':  cv.detail.WAVE_CORRECT_VERT,
}

# Helpers
def make_matcher():
    conf = MATCH_CONF if MATCH_CONF is not None else (0.3 if FEATURES == 'orb' else 0.65)
    if MATCHER == 'affine':
        return cv.detail_AffineBestOf2NearestMatcher(False, TRY_CUDA, conf)
    if RANGEWIDTH != -1:
        return cv.detail_BestOf2NearestRangeMatcher(RANGEWIDTH, TRY_CUDA, conf)
    return cv.detail_BestOf2NearestMatcher(TRY_CUDA, conf)


def make_compensator():
    comp_type = EXPOS_COMP_MAP[EXPOS_COMP]
    if comp_type == cv.detail.ExposureCompensator_CHANNELS:
        return cv.detail_ChannelsCompensator(EXPOS_COMP_NR_FEEDS)
    if comp_type == cv.detail.ExposureCompensator_CHANNELS_BLOCKS:
        return cv.detail_BlocksChannelsCompensator(
            EXPOS_COMP_BLOCK_SIZE, EXPOS_COMP_BLOCK_SIZE, EXPOS_COMP_NR_FEEDS)
    return cv.detail.ExposureCompensator_createDefault(comp_type)


# Phase 1 – Setup
# Feature detection → matching → camera estimation → bundle adjustment → wave correction.
# Returns a dict of parameters needed by stitch().
def setup(input_images):
    finder = FEATURES_MAP[FEATURES]()

    work_scale       = 1.0
    seam_scale       = 1.0
    seam_work_aspect = 1.0
    work_scale_set   = False
    seam_scale_set   = False

    full_img_sizes = []
    features       = []
    seam_images    = []

    for name in input_images:
        full = cv.imread(name)
        if full is None:
            raise Exception(f"Cannot read image: {name}")
        full_img_sizes.append((full.shape[1], full.shape[0]))

        if WORK_MEGAPIX < 0:
            work_img = full
            work_scale = 1.0
            work_scale_set = True
        else:
            if not work_scale_set:
                work_scale = min(1.0, np.sqrt(
                    WORK_MEGAPIX * 1e6 / (full.shape[0] * full.shape[1])))
                work_scale_set = True
            work_img = cv.resize(full, None, fx=work_scale, fy=work_scale,
                                 interpolation=cv.INTER_LINEAR_EXACT)

        if not seam_scale_set:
            seam_scale = min(1.0, np.sqrt(
                SEAM_MEGAPIX * 1e6 / (full.shape[0] * full.shape[1])))
            seam_work_aspect = seam_scale / work_scale
            seam_scale_set = True

        features.append(cv.detail.computeImageFeatures2(finder, work_img))
        seam_images.append(cv.resize(full, None, fx=seam_scale, fy=seam_scale,
                                     interpolation=cv.INTER_LINEAR_EXACT))

    # Feature matching
    matcher  = make_matcher()
    pairwise = matcher.apply2(features)
    matcher.collectGarbage()

    # Filter to largest connected component; modifies features/pairwise in-place
    indices       = cv.detail.leaveBiggestComponent(features, pairwise, CONF_THRESH)
    img_names_sub = [input_images[i]      for i in indices]
    images_sub    = [seam_images[i]    for i in indices]
    sizes_sub     = [full_img_sizes[i] for i in indices]

    if len(img_names_sub) < 2:
        raise Exception("Couldn't find enough matches for any panoramic output")
    if len(img_names_sub) < 4:
        print("Not all camera outputs made it to the final panorama, creating a partial panorama instead.")

    # Camera estimation
    estimator = ESTIMATOR_MAP[ESTIMATOR]()
    ok, cameras = estimator.apply(features, pairwise, None)
    if not ok:
        raise Exception("Homography estimation failed.")
    for cam in cameras:
        cam.R = cam.R.astype(np.float32)

    # Bundle adjustment
    adjuster = BA_COST_MAP[BA]()
    adjuster.setConfThresh(1)
    refine_mask  = np.zeros((3, 3), np.uint8)
    mask_pos     = [(0,0),(0,1),(0,2),(1,1),(1,2)]
    for i, ch in enumerate(BA_REFINE_MASK[:5]):
        if ch == 'x':
            refine_mask[mask_pos[i]] = 1
    adjuster.setRefinementMask(refine_mask)
    ok, cameras = adjuster.apply(features, pairwise, cameras)
    if not ok:
        raise Exception("Camera parameters adjusting failed.")

    # Warped image scale from median focal length
    focals = sorted(cam.focal for cam in cameras)
    n = len(focals)
    warped_image_scale = focals[n // 2] if n % 2 else (focals[n//2] + focals[n//2 - 1]) / 2

    # Wave correction
    wc = WAVE_CORRECT_MAP[WAVE_CORRECT]
    if wc is not None:
        rmats = cv.detail.waveCorrect([np.copy(cam.R) for cam in cameras], wc)
        for cam, R in zip(cameras, rmats):
            cam.R = R

    return {
        'cameras':            cameras,
        'seam_images':        images_sub,
        'img_names':          img_names_sub,
        'full_img_sizes':     sizes_sub,
        'warped_image_scale': warped_image_scale,
        'work_scale':         work_scale,
        'seam_work_aspect':   seam_work_aspect,
    }

def crop_black_borders(img):
    img = cv.copyMakeBorder(img, 10, 10, 10, 10, cv.BORDER_CONSTANT, (0, 0, 0))
    grayscale = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    thresh = cv.threshold(grayscale, 0, 255, cv.THRESH_BINARY)[1]

    contours = cv.findContours(thresh.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contours = imutils.grab_contours(contours)
    area_of_interest = max(contours, key=cv.contourArea)

    mask = np.zeros(thresh.shape, dtype="uint8")
    x, y, w, h = cv.boundingRect(area_of_interest)
    cv.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

    # Fill black holes/noise inside the panorama region
    kernel = cv.getStructuringElement(cv.MORPH_RECT, (7, 7))
    thresh = cv.morphologyEx(thresh, cv.MORPH_CLOSE, kernel)

    minimum_rectangle = mask.copy()
    sub = mask.copy()
    while cv.countNonZero(sub) > 0:
        minimum_rectangle = cv.erode(minimum_rectangle, None)
        sub = cv.subtract(minimum_rectangle, thresh)

    contours = cv.findContours(minimum_rectangle.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contours = imutils.grab_contours(contours)
    area_of_interest = max(contours, key=cv.contourArea)

    x, y, w, h = cv.boundingRect(area_of_interest)
    return img[y:y + h, x:x + w]

# Phase 2 – Stitch
# Warp → exposure compensation → seam finding → composite → blend → write.
def stitch(data, out_path):
    cameras          = data['cameras']
    seam_images      = data['seam_images']
    img_names        = data['img_names']
    full_img_sizes   = data['full_img_sizes']
    warp_scale       = data['warped_image_scale']
    work_scale       = data['work_scale']
    seam_work_aspect = data['seam_work_aspect']
    num_images       = len(img_names)

    # Warp at seam scale
    warper       = cv.PyRotationWarper(WARP, warp_scale * seam_work_aspect)
    corners      = []
    sizes        = []
    warped_imgs  = []
    warped_masks = []

    for i in range(num_images):
        K = cameras[i].K().astype(np.float32)
        K[0, 0] *= seam_work_aspect;  K[0, 2] *= seam_work_aspect
        K[1, 1] *= seam_work_aspect;  K[1, 2] *= seam_work_aspect

        corner, img_wp = warper.warp(
            seam_images[i], K, cameras[i].R, cv.INTER_LINEAR, cv.BORDER_REFLECT)
        corners.append(corner)
        sizes.append((img_wp.shape[1], img_wp.shape[0]))
        warped_imgs.append(img_wp)

        mask = cv.UMat(255 * np.ones(seam_images[i].shape[:2], np.uint8))
        _, mask_wp = warper.warp(mask, K, cameras[i].R, cv.INTER_NEAREST, cv.BORDER_CONSTANT)
        warped_masks.append(mask_wp.get())

    # Exposure compensation
    compensator = make_compensator()
    compensator.feed(corners=corners, images=warped_imgs, masks=warped_masks)

    # Seam finding
    warped_imgs_f = [img.astype(np.float32) for img in warped_imgs]
    warped_masks  = SEAM_MAP[SEAM].find(warped_imgs_f, corners, warped_masks)

    # Compositing
    compose_scale_set = False
    compose_scale     = 1.0
    corners           = []
    sizes             = []
    blender           = None

    for idx, name in enumerate(img_names):
        full = cv.imread(name)

        if not compose_scale_set:
            if COMPOSE_MEGAPIX > 0:
                compose_scale = min(1.0, np.sqrt(
                    COMPOSE_MEGAPIX * 1e6 / (full.shape[0] * full.shape[1])))
            compose_scale_set   = True
            compose_work_aspect = compose_scale / work_scale
            warp_scale         *= compose_work_aspect
            warper              = cv.PyRotationWarper(WARP, warp_scale)
            for i in range(num_images):
                cameras[i].focal *= compose_work_aspect
                cameras[i].ppx   *= compose_work_aspect
                cameras[i].ppy   *= compose_work_aspect
                sz  = (int(round(full_img_sizes[i][0] * compose_scale)),
                       int(round(full_img_sizes[i][1] * compose_scale)))
                K   = cameras[i].K().astype(np.float32)
                roi = warper.warpRoi(sz, K, cameras[i].R)
                corners.append(roi[0:2])
                sizes.append(roi[2:4])

        img = cv.resize(full, None, fx=compose_scale, fy=compose_scale,
                        interpolation=cv.INTER_LINEAR_EXACT) \
              if abs(compose_scale - 1) > 1e-1 else full

        K = cameras[idx].K().astype(np.float32)
        corner, img_warped = warper.warp(img, K, cameras[idx].R,
                                         cv.INTER_LINEAR, cv.BORDER_REFLECT)
        mask = 255 * np.ones(img.shape[:2], np.uint8)
        _, mask_warped = warper.warp(mask, K, cameras[idx].R,
                                      cv.INTER_NEAREST, cv.BORDER_CONSTANT)

        compensator.apply(idx, corners[idx], img_warped, mask_warped)
        img_warped_s = img_warped.astype(np.int16)
        dilated_mask = cv.dilate(warped_masks[idx], None)
        seam_mask    = cv.resize(dilated_mask, (mask_warped.shape[1], mask_warped.shape[0]),
                                 interpolation=cv.INTER_LINEAR_EXACT)
        mask_warped  = cv.bitwise_and(seam_mask, mask_warped)

        if blender is None:
            dst_sz      = cv.detail.resultRoi(corners=corners, sizes=sizes)
            blend_width = np.sqrt(dst_sz[2] * dst_sz[3]) * BLEND_STRENGTH / 100
            if blend_width < 1 or BLEND == 'no':
                blender = cv.detail.Blender_createDefault(cv.detail.Blender_NO)
            elif BLEND == 'multiband':
                blender = cv.detail_MultiBandBlender()
                blender.setNumBands(int(np.log(blend_width) / np.log(2.) - 1.))
            elif BLEND == 'feather':
                blender = cv.detail_FeatherBlender()
                blender.setSharpness(1. / blend_width)
            blender.prepare(dst_sz)
        blender.feed(cv.UMat(img_warped_s), mask_warped, corners[idx])

    result, _ = blender.blend(None, None)
    result = result.get() if hasattr(result, 'get') else np.array(result)
    return np.clip(result, 0, 255).astype(np.uint8)


def save_params(data, path):
    """Serialize camera parameters returned by setup() to a .npz file."""
    cameras = data['cameras']
    d = {
        'img_names':          np.array(data['img_names']),
        'full_img_sizes':     np.array(data['full_img_sizes']),
        'warped_image_scale': np.float64(data['warped_image_scale']),
        'work_scale':         np.float64(data['work_scale']),
        'seam_work_aspect':   np.float64(data['seam_work_aspect']),
        'focal':  np.array([c.focal  for c in cameras]),
        'ppx':    np.array([c.ppx    for c in cameras]),
        'ppy':    np.array([c.ppy    for c in cameras]),
        'aspect': np.array([c.aspect for c in cameras]),
    }
    for i, cam in enumerate(cameras):
        d[f'R_{i}'] = cam.R
        d[f't_{i}'] = cam.t
    np.savez(path, **d)


def load_params(path):
    """Reconstruct a setup() result dict from a saved .npz file."""
    d = np.load(path)
    img_names = [str(s) for s in d['img_names']]
    n = len(img_names)

    cameras = []
    for i in range(n):
        cam        = cv.detail.CameraParams()
        cam.focal  = float(d['focal'][i])
        cam.ppx    = float(d['ppx'][i])
        cam.ppy    = float(d['ppy'][i])
        cam.aspect = float(d['aspect'][i])
        cam.R      = d[f'R_{i}'].astype(np.float32)
        cam.t      = d[f't_{i}']
        cameras.append(cam)

    work_scale       = float(d['work_scale'])
    seam_work_aspect = float(d['seam_work_aspect'])
    seam_scale       = seam_work_aspect * work_scale

    seam_images = []
    for name in img_names:
        full = cv.imread(name)
        if full is None:
            raise Exception(f"Cannot read image: {name}")
        seam_images.append(cv.resize(full, None, fx=seam_scale, fy=seam_scale,
                                     interpolation=cv.INTER_LINEAR_EXACT))

    return {
        'cameras':            cameras,
        'seam_images':        seam_images,
        'img_names':          img_names,
        'full_img_sizes':     [tuple(int(v) for v in row) for row in d['full_img_sizes']],
        'warped_image_scale': float(d['warped_image_scale']),
        'work_scale':         work_scale,
        'seam_work_aspect':   seam_work_aspect,
    }


def stitch_images(input_images, out_path, save_parameters=False, crop_borders=False):
    if use_high_level_api:
        stitcher = cv.Stitcher.create(cv.STITCHER_PANORAMA)
        imgs = []
        for img_name in input_images:
            img = cv.imread(cv.samples.findFile(img_name))
            if img is None:
                raise Exception("can't read image " + img_name)
            imgs.append(img)
        status, pano = stitcher.stitch(imgs)
        result = crop_black_borders(pano) if crop_borders else pano
        cv.imwrite(out_path, result)
    else:
        if not save_parameters:
            parameters = load_params(PARAMS_FILE)
        else:
            parameters = setup(input_images)
            save_params(parameters, PARAMS_FILE)
        stitched = stitch(parameters, out_path)
        result = crop_black_borders(stitched) if crop_borders else stitched
        cv.imwrite(out_path, result)


# Test
if __name__ == '__main__':
    stitch_images(["cam1.jpg", "cam2.jpg"], "result.jpg")