# Synchronized Multi-Camera Panoramic Imaging System
**BAU Capstone Project — Faculty of Engineering and Natural Sciences, 2026**

## Team
| Name | Department |
|------|-----------|
| Ece Bezirci | Electrical & Electronics Engineering · Software Engineering |
| Eylül Çelen | Computer Engineering · Software Engineering |
| Onur Sinan Güler | Computer Engineering · Software Engineering |

**Advisors:** Assist. Prof. Duygu Çakır · Assist. Prof. Tarkan Aydın

---

## What It Does
Two ESP32-CAM modules capture overlapping images simultaneously over WiFi. A Python/Flask server fetches both images in parallel, stitches them into a single panoramic image using OpenCV, and serves a web interface where users can log in, trigger captures, view results, and download their panoramas. Each user's captures are stored privately in a SQLite database.

---

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Camera hardware | ESP32-CAM (AI Thinker, OV2640 sensor) |
| Firmware | Arduino C++ |
| Backend | Python 3, Flask |
| Computer vision | OpenCV (SIFT / ORB feature matching) |
| Database | SQLite |
| Frontend | HTML, CSS, JavaScript |

---

## Hardware Setup — Wiring ESP32-CAM to FTDI (for flashing)

Connect 4 wires between the FTDI adapter and the ESP32-CAM:

| FTDI pin | ESP32-CAM pin |
|----------|---------------|
| VCC (5V) | 5V |
| GND | GND |
| TX | U0R |
| RX | U0T |

**Flash mode only:** add one extra wire — GPIO0 → GND. This tells the chip to accept new firmware. Remove this wire after uploading, then press RESET.

After flashing you no longer need the FTDI adapter. Power the ESP32-CAM through its 5V and GND pins from any USB source (phone charger, power bank, or PC USB port).

---

## Arduino IDE Setup

1. Open Arduino IDE → **File → Preferences**
2. Paste the following into *Additional Boards Manager URLs*:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. **Tools → Boards Manager** → search `esp32` → install by **Espressif Systems**
4. **Tools → Board → ESP32 Arduino → AI Thinker ESP32-CAM**
5. **Tools → Port** → select the COM port that appeared when you plugged in the FTDI
6. **Tools → Partition Scheme → Huge APP (3MB No OTA)**

---

## Flashing the Firmware

1. Open the ESP32-CAM firmware sketch in Arduino IDE
2. Fill in your WiFi credentials at the top of the file:
   ```cpp
   const char* ssid     = "YOUR_WIFI_NAME";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```
3. Set the camera ID:
   ```cpp
   const char* CAM_ID = "cam1";   // use "cam2" for the second board
   ```
4. Wire **GPIO0 → GND**, press **RESET** on the board, then click **Upload**
5. When the IDE says *Done uploading* — remove the GPIO0 wire and press **RESET** again
6. Open **Tools → Serial Monitor** at **115200 baud** — the camera's IP address will be printed. Write it down.
7. Repeat all steps for the second camera using `CAM_ID = "cam2"`

---

## PC Software Setup

1. Install Python 3 from [python.org](https://www.python.org/downloads/) — check **"Add Python to PATH"** during installation
2. Open Command Prompt and install dependencies:
   ```
   pip install flask opencv-python requests numpy
   ```
3. Place all four project files in one folder:
   ```
   panorama_project/
     app.py
     sync.py
     stitch.py
     database.py
   ```
4. Open `sync.py` and replace the placeholder IPs with the addresses you wrote down:
   ```python
   CAM1_IP = "192.168.x.xxx"   # IP of cam1 from Serial Monitor
   CAM2_IP = "192.168.x.xxx"   # IP of cam2 from Serial Monitor
   ```
5. Open `app.py` and change the admin password:
   ```python
   ADMIN_PASS = "your_secure_password"
   ```

---

## Running the System

```
python app.py
```

| URL | Purpose |
|-----|---------|
| `http://localhost:5000/admin/login` | Admin panel — create/delete user accounts |
| `http://localhost:5000` | User login and capture interface |

**Both ESP32-CAMs must be connected to the same WiFi network as the PC running the app.**

---

## How It Works

```
[ESP32-CAM #1] ──┐
                  ├── WiFi ──> [PC: Flask server] ──> [OpenCV stitch] ──> [Web UI]
[ESP32-CAM #2] ──┘
```

1. User clicks *Capture & Stitch* in the browser
2. The server fetches images from both cameras simultaneously using Python threads
3. OpenCV detects features in both images, estimates a homography, warps and blends them
4. The stitched panorama is saved to disk and recorded in the SQLite database under the user's account
5. The result is displayed in the browser with a download link

---

## Project Structure

```
panorama_project/
├── app.py          # Flask web server, routes, login, admin panel
├── sync.py         # Parallel image fetching from both ESP32-CAMs
├── stitch.py       # OpenCV panoramic stitching pipeline
├── database.py     # SQLite setup, user and capture management
├── panoptic.db     # Auto-created on first run (do not commit)
└── captures/       # Per-user saved panoramas (do not commit)
```

---

## Notes
- The system is designed for **static or low-motion scenes**
- Cameras should overlap by approximately **30%** for reliable stitching
- SIFT produces more accurate stitching; ORB is faster but less precise
- The database file and captures folder are excluded from version control via `.gitignore`
