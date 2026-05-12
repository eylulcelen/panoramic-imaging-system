"""
sync.py — Fetch images from both ESP32-CAM nodes simultaneously.
Cameras serve /image directly (no separate /capture trigger needed).
"""

import threading
import requests

CAM1_IP = "192.168.1.172"   # ← your cam1 IP
CAM2_IP = "192.168.1.107"   # ← your cam2 IP

TIMEOUT = 10


def _fetch(ip, filename, results, key):
    """Fetch the current frame from one camera and save to disk."""
    try:
        r = requests.get(f"http://{ip}/image", timeout=TIMEOUT)

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
    """Return online/offline status dict for both cameras."""
    status = {}
    for key, ip in [("cam1", CAM1_IP), ("cam2", CAM2_IP)]:
        try:
            r = requests.get(f"http://{ip}/status", timeout=3)
            status[key] = {"online": r.status_code == 200, "ip": ip}
        except Exception:
            status[key] = {"online": False, "ip": ip}
    return status


def sync_capture(resolution="UXGA", quality="high"):
    """
    Fetch both cameras in parallel and save as img_left.jpg / img_right.jpg.
    Returns (success: bool, error_message: str).
    resolution and quality are accepted for API compatibility but
    the ESP32 firmware handles those settings internally.
    """
    results = {}

    t1 = threading.Thread(
        target=_fetch,
        args=(CAM1_IP, "img_left.jpg", results, "cam1")
    )
    t2 = threading.Thread(
        target=_fetch,
        args=(CAM2_IP, "img_right.jpg", results, "cam2")
    )

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    ok1, err1 = results.get("cam1", (False, "No response"))
    ok2, err2 = results.get("cam2", (False, "No response"))

    if not ok1:
        return False, f"Camera 1: {err1}"
    if not ok2:
        return False, f"Camera 2: {err2}"

    return True, ""