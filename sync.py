"""
sync.py — Fetch images from multiple ESP32-CAM nodes simultaneously.
Cameras serve /image directly (no separate /capture trigger needed).
"""

import concurrent.futures
import requests

CAM_IPS = [
    "10.108.169.169",  # cam1
    "10.108.169.217",  # cam2
]

TIMEOUT = 10


def _fetch(ip, filename, results, key):
    """Fetch the current frame from one camera and save to disk."""
    try:
        r = requests.get(f"http://{ip}/capture", timeout=TIMEOUT)

        if r.status_code == 200:
            with open(filename, "wb") as f:
                f.write(r.content)
            results[key] = (True, "OK")
        else:
            results[key] = (False, f"HTTP {r.status_code}")

    except requests.exceptions.ConnectionError:
        results[key] = (False, f"Cannot connect to {ip}")
    except requests.exceptions.Timeout:
        results[key] = (False, f"Timeout from {ip}")
    except Exception as e:
        results[key] = (False, str(e))


def check_camera_status():
    """Return online/offline status dict for all cameras in CAM_IPS."""
    status = {}
    for idx, ip in enumerate(CAM_IPS, start=1):
        key = f"cam{idx}"
        try:
            r = requests.get(f"http://{ip}/status", timeout=3)
            status[key] = {"online": r.status_code == 200, "ip": ip}
        except Exception:
            status[key] = {"online": False, "ip": ip}
    return status


def sync_capture(resolution="UXGA", quality="high"):
    """
    Fetch all cameras in CAM_IPS in parallel and save as cam1.jpg, cam2.jpg, ...
    Returns (success: bool, error_message: str).
    resolution and quality are accepted for API compatibility but
    the ESP32 firmware handles those settings internally.
    """
    results = {}
    # use a thread pool sized to the number of cameras (bounded)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(CAM_IPS)) as exe:
        futures = []
        for idx, ip in enumerate(CAM_IPS, start=1):
            key = f"cam{idx}"
            filename = f"{key}.jpg"
            futures.append(exe.submit(_fetch, ip, filename, results, key))

        # wait for all to complete (raises exceptions only if submit failed)
        concurrent.futures.wait(futures)

    # aggregate results
    for idx, ip in enumerate(CAM_IPS, start=1):
        key = f"cam{idx}"
        ok, err = results.get(key, (False, "No response"))
        if not ok:
            return False, f"{key}: {err}"

    return True, ""