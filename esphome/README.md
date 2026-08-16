# KEMS 16x16 ESPHome panel

`kems16x16.yaml` is the official KEMS 16x16 WS2812/WS2812B panel configuration.

## Managed updates

KEMS can keep an existing ESPHome panel YAML aligned with the KEMS version installed in Home Assistant.

The opt-in is deliberately simple and safe:

1. Install the panel in ESPHome as `/config/esphome/kems16x16.yaml`.
2. Keep the filename exactly `kems16x16.yaml`.
3. When KEMS starts, it compares that existing file with the panel YAML packaged with KEMS.
4. If KEMS shipped a newer panel definition, the existing file is atomically replaced.

KEMS **does not create** `kems16x16.yaml` for users who do not already have the panel, so installing KEMS does not add an unwanted ESPHome device.

## Firmware flashing

Updating the YAML cannot by itself change firmware already running on the ESP32. After KEMS updates the managed YAML, open ESPHome Builder and choose **Install** for `kems16x16` to compile and OTA-flash the new firmware.

## Local customisation

The managed file is KEMS-owned. Local edits to `/config/esphome/kems16x16.yaml` may be replaced on a later KEMS restart. Keep experimental or personalised panel configurations under a different filename if they should not be managed by KEMS.

## Current hardware assumptions

- ESP32
- WS2812/WS2812B 16x16 matrix
- 256 LEDs
- Data pin: GPIO21
- GRB colour order
- Existing KEMS faceplate mapping and horizontal mirror correction
