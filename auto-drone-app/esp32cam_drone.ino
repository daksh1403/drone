/*
 * ============================================================
 *  ESP32-CAM  –  Paint-Drone Controller (Drone Version)
 *  Adds /spray_start and /spray_stop for continuous painting
 * ============================================================
 *
 *  Port 80 → control: /ping /status /spray /spray_start
 *                      /spray_stop /capture_frame
 *  Port 81 → stream:  /stream
 *
 *  New endpoints for continuous painting:
 *    POST /spray_start → relay ON indefinitely until /spray_stop
 *    POST /spray_stop  → relay OFF immediately
 *
 *  Relay pin: GPIO 13 (active HIGH)
 *  Network:   AP SSID=PaintDrone pass=paintdrone123
 *  AP IP:     192.168.4.1
 * ============================================================
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>

// ── WiFi AP credentials ──────────────────────────────────────
const char* AP_SSID     = "PaintDrone";
const char* AP_PASSWORD = "paintdrone123";

// ── Relay ────────────────────────────────────────────────────
#define RELAY_PIN  13
#define RELAY_ON   HIGH   // Change to LOW if relay is active-LOW
#define RELAY_OFF  LOW

// ── Relay state ──────────────────────────────────────────────
bool          relayActive      = false;
bool          continuousMode   = false;  // true = spray until stopped
unsigned long relayOnTime      = 0;
unsigned long relayDuration    = 0;

// ── AI-Thinker ESP32-CAM pins ────────────────────────────────
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22

// ── Two servers ──────────────────────────────────────────────
WebServer controlServer(80);
WebServer streamServer(81);

// ── CORS helper ──────────────────────────────────────────────
void addCors(WebServer& srv) {
  srv.sendHeader("Access-Control-Allow-Origin", "*");
  srv.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  srv.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

/* ============================================================
 *  setup()
 * ============================================================ */
void setup() {
  Serial.begin(115200);
  Serial.println("\n[ESP32-CAM] Booting — drone paint mode...");

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, RELAY_OFF);

  setupCamera();

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASSWORD);
  delay(500);
  Serial.print("[ESP32-CAM] AP IP: ");
  Serial.println(WiFi.softAPIP());

  // ── Control server routes (port 80) ──
  controlServer.on("/ping",          HTTP_GET,     handlePing);
  controlServer.on("/status",        HTTP_GET,     handleStatus);
  controlServer.on("/spray",         HTTP_POST,    handleSpray);
  controlServer.on("/spray_start",   HTTP_POST,    handleSprayStart); // NEW
  controlServer.on("/spray_stop",    HTTP_POST,    handleSprayStop);  // NEW
  controlServer.on("/capture_frame", HTTP_GET,     handleCaptureFrame);

  // CORS preflight for all POST routes
  controlServer.on("/spray",       HTTP_OPTIONS, handleOptions);
  controlServer.on("/spray_start", HTTP_OPTIONS, handleOptions);
  controlServer.on("/spray_stop",  HTTP_OPTIONS, handleOptions);
  controlServer.on("/ping",        HTTP_OPTIONS, handleOptions);

  controlServer.begin();
  Serial.println("[ESP32-CAM] Control server on port 80");

  // ── Stream server (port 81) ──
  streamServer.on("/stream", HTTP_GET, handleStream);
  streamServer.begin();
  Serial.println("[ESP32-CAM] Stream server on port 81");
  Serial.println("[ESP32-CAM] Ready!");
}

/* ============================================================
 *  loop()
 * ============================================================ */
void loop() {
  controlServer.handleClient();
  streamServer.handleClient();

  // Non-blocking relay shutoff — only in precision mode
  if (relayActive && !continuousMode) {
    if (millis() - relayOnTime >= relayDuration) {
      digitalWrite(RELAY_PIN, RELAY_OFF);
      relayActive = false;
      Serial.println("[ESP32-CAM] Relay OFF (precision spray done)");
    }
  }
}

/* ============================================================
 *  Camera setup
 * ============================================================ */
void setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode    = CAMERA_GRAB_LATEST;
  config.frame_size   = FRAMESIZE_VGA;
  config.jpeg_quality = 10;
  config.fb_count     = 2;
  config.fb_location  = CAMERA_FB_IN_PSRAM;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("[ESP32-CAM] Camera init FAILED — restarting");
    delay(3000);
    ESP.restart();
  }

  sensor_t* s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
  s->set_brightness(s, 1);
  s->set_saturation(s, -1);
  Serial.println("[ESP32-CAM] Camera OK");
}

/* ============================================================
 *  GET /ping
 * ============================================================ */
void handlePing() {
  addCors(controlServer);
  controlServer.send(200, "application/json", "{\"status\":\"ok\"}");
}

/* ============================================================
 *  GET /status
 * ============================================================ */
void handleStatus() {
  addCors(controlServer);
  StaticJsonDocument<128> doc;
  doc["relay"]      = relayActive ? "on" : "off";
  doc["mode"]       = continuousMode ? "continuous" : "precision";
  String out;
  serializeJson(doc, out);
  controlServer.send(200, "application/json", out);
}

/* ============================================================
 *  POST /spray  — precision spray for duration_ms
 *  Body: {"duration_ms": 800}
 * ============================================================ */
void handleSpray() {
  addCors(controlServer);
  if (relayActive) {
    controlServer.send(409, "application/json",
                       "{\"error\":\"spray in progress\"}");
    return;
  }
  StaticJsonDocument<128> doc;
  deserializeJson(doc, controlServer.arg("plain"));
  unsigned long dur = doc["duration_ms"] | 800UL;
  dur = constrain(dur, 50, 5000);

  Serial.printf("[ESP32-CAM] Precision spray %lu ms\n", dur);
  digitalWrite(RELAY_PIN, RELAY_ON);
  relayActive    = true;
  continuousMode = false;
  relayOnTime    = millis();
  relayDuration  = dur;

  controlServer.send(200, "application/json", "{\"sprayed\":true}");
}

/* ============================================================
 *  POST /spray_start  — continuous spray ON (no timeout)
 *  Used when drone flies along wall continuously
 * ============================================================ */
void handleSprayStart() {
  addCors(controlServer);

  Serial.println("[ESP32-CAM] CONTINUOUS spray START");
  digitalWrite(RELAY_PIN, RELAY_ON);
  relayActive    = true;
  continuousMode = true;   // Will NOT auto-shutoff in loop()

  controlServer.send(200, "application/json",
                     "{\"status\":\"spraying\",\"mode\":\"continuous\"}");
}

/* ============================================================
 *  POST /spray_stop  — stop continuous spray immediately
 * ============================================================ */
void handleSprayStop() {
  addCors(controlServer);

  Serial.println("[ESP32-CAM] CONTINUOUS spray STOP");
  digitalWrite(RELAY_PIN, RELAY_OFF);
  relayActive    = false;
  continuousMode = false;

  controlServer.send(200, "application/json",
                     "{\"status\":\"stopped\"}");
}

/* ============================================================
 *  GET /capture_frame  — single JPEG for Flask /capture
 * ============================================================ */
void handleCaptureFrame() {
  addCors(controlServer);
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    controlServer.send(500, "application/json",
                       "{\"error\":\"capture failed\"}");
    return;
  }
  controlServer.send_P(200, "image/jpeg",
                       (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

/* ============================================================
 *  OPTIONS preflight
 * ============================================================ */
void handleOptions() {
  addCors(controlServer);
  controlServer.send(204);
}

/* ============================================================
 *  GET /stream (port 81) — MJPEG stream
 * ============================================================ */
#define BOUNDARY "----frame"

void handleStream() {
  WiFiClient client = streamServer.client();
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: multipart/x-mixed-replace; boundary=" BOUNDARY);
  client.println("Access-Control-Allow-Origin: *");
  client.println("Cache-Control: no-cache");
  client.println();

  while (client.connected()) {
    controlServer.handleClient();  // Keep control server alive during stream

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { delay(30); continue; }

    client.printf("--%s\r\n", BOUNDARY);
    client.println("Content-Type: image/jpeg");
    client.printf("Content-Length: %u\r\n\r\n", fb->len);
    client.write(fb->buf, fb->len);
    client.println();

    esp_camera_fb_return(fb);
    delay(50);
  }
}
