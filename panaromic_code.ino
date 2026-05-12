#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"

// =====================================
// WIFI SETTINGS
// =====================================
const char* ssid     = "Superbox_Wifi_2530";
const char* password = "83KH4B77Y8";

const char* CAM_ID = "cam2";

// =====================================
// AI THINKER ESP32-CAM PINS
// =====================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5

#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(80);

// =====================================
// CAMERA START
// =====================================
bool startCamera() {

  camera_config_t config;

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;

  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;

  config.pin_pwdn  = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  // LOWER CLOCK = MORE STABLE
  config.xclk_freq_hz = 10000000;

  config.pixel_format = PIXFORMAT_JPEG;

  // SAFE / STABLE SETTINGS
  config.frame_size   = FRAMESIZE_QVGA; // 320x240
  config.jpeg_quality = 15;
  config.fb_count     = 1;

  Serial.println("Starting camera...");

  esp_err_t err = esp_camera_init(&config);

  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }

  sensor_t * s = esp_camera_sensor_get();

  // EXTRA SAFETY
  s->set_framesize(s, FRAMESIZE_QVGA);

  Serial.println("Camera started successfully");

  return true;
}

// =====================================
// ROOT PAGE
// =====================================
void handleRoot() {

  String html = R"rawliteral(
  <!DOCTYPE html>
  <html>
  <head>
      <title>ESP32-CAM</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
  </head>

  <body style="text-align:center;font-family:Arial;">
      <h2>ESP32-CAM SERVER</h2>

      <img src="/image" width="320">

      <p>Camera running</p>
  </body>
  </html>
  )rawliteral";

  server.send(200, "text/html", html);
}

// =====================================
// IMAGE ENDPOINT
// =====================================
void handleImage() {

  camera_fb_t * fb = esp_camera_fb_get();

  if (!fb) {
    Serial.println("Camera capture failed");
    server.send(503, "text/plain", "Camera capture failed");
    return;
  }

  WiFiClient client = server.client();

  // Proper HTTP headers
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: image/jpeg");
  client.println("Content-Length: " + String(fb->len));
  client.println("Connection: close");
  client.println();

  // Send image
  client.write(fb->buf, fb->len);

  esp_camera_fb_return(fb);

  Serial.println("Image sent");
}

// =====================================
// STATUS ENDPOINT
// =====================================
void handleStatus() {

  String json =
    "{"
    "\"cam\":\"" + String(CAM_ID) + "\","
    "\"ip\":\"" + WiFi.localIP().toString() + "\""
    "}";

  server.send(200, "application/json", json);
}

// =====================================
// SETUP
// =====================================
void setup() {

  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println("Booting ESP32-CAM...");

  // START CAMERA
  if (!startCamera()) {
    Serial.println("Camera failed to start");
    return;
  }

  // WIFI CONNECT
  WiFi.begin(ssid, password);

  Serial.print("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected");

  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // ROUTES
  server.on("/", handleRoot);
  server.on("/image", handleImage);
  server.on("/status", handleStatus);

  server.begin();

  Serial.println("HTTP server started");
}

// =====================================
// LOOP
// =====================================
void loop() {

  server.handleClient();

  delay(1);
}