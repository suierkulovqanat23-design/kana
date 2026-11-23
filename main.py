import time

import framebuf
import network
from machine import I2C, Pin, time_pulse_us

TRIG_PIN = 5
ECHO_PIN = 18
SDA_PIN = 21
SCL_PIN = 22
OLED_ADDRESS = 0x3C

DANGER_CM = 50
WARNING_CM = 100
MOTION_DELTA_CM = 2

try:
    from config import WIFI_SSID, WIFI_PASSWORD, API_URL, API_KEY
except ImportError:
    WIFI_SSID = WIFI_PASSWORD = API_URL = API_KEY = ""


class OLED:
    def __init__(self, bus):
        self.bus = bus
        self.buffer = bytearray(1024)
        self.frame = framebuf.FrameBuffer(
            self.buffer, 128, 64, framebuf.MONO_VLSB
        )
        self.command(
            0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
            0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
            0x81, 0x7F, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF
        )

    def command(self, *values):
        self.bus.writeto(OLED_ADDRESS, bytes((0x00,) + values))

    def show(self, lines):
        self.frame.fill(0)
        for row, line in enumerate(lines):
            self.frame.text(line[:16], 0, row * 12, 1)
        self.command(0x21, 0, 127, 0x22, 0, 7)
        self.bus.writevto(OLED_ADDRESS, (b"\x40", self.buffer))


def measure_cm(trigger, echo):
    trigger.off()
    time.sleep_us(2)
    trigger.on()
    time.sleep_us(10)
    trigger.off()

    try:
        duration = time_pulse_us(echo, 1, 30000)
    except OSError:
        return None

    distance = duration * 0.0343 / 2
    if 2 <= distance <= 400:
        return distance
    return None


def filtered_distance(trigger, echo):
    samples = []
    for _ in range(5):
        measurement = measure_cm(trigger, echo)
        if measurement is not None:
            samples.append(measurement)
        time.sleep_ms(60)

    if len(samples) < 3:
        return None

    samples.sort()
    middle = len(samples) // 2
    if len(samples) % 2:
        return samples[middle]
    return (samples[middle - 1] + samples[middle]) / 2


def get_zone(distance):
    if distance is None:
        return "ERROR"
    if distance < DANGER_CM:
        return "DANGER"
    if distance <= WARNING_CM:
        return "WARNING"
    return "SAFE"


def local_motion(previous, current):
    if previous is None or current is None:
        return "UNKNOWN"
    delta = current - previous
    if delta < -MOTION_DELTA_CM:
        return "APPROACHING"
    if delta > MOTION_DELTA_CM:
        return "MOVING_AWAY"
    return "STATIONARY"


def request_motion(previous, current):
    import requests

    response = requests.post(
        API_URL,
        headers={"Authorization": "Bearer " + API_KEY},
        json={"previous_cm": previous, "current_cm": current},
        timeout=2,
    )
    try:
        if response.status_code != 200:
            raise ValueError("HTTP " + str(response.status_code))
        data = response.json()
        motion = data.get("motion") if isinstance(data, dict) else None
        if motion not in ("APPROACHING", "MOVING_AWAY", "STATIONARY"):
            raise ValueError("Invalid motion")
        return motion
    finally:
        response.close()


def display_result(display, distance, zone, motion, source):
    if display is None:
        return
    distance_text = "NO ECHO" if distance is None else "{:.1f} cm".format(distance)
    try:
        display.show(("SMART PARKING", distance_text, zone, motion, source))
    except OSError:
        print("OLED update failed")


def main():
    trigger = Pin(TRIG_PIN, Pin.OUT, value=0)
    echo = Pin(ECHO_PIN, Pin.IN)

    display = None
    try:
        bus = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400000)
        display = OLED(bus)
    except (OSError, ValueError):
        print("OLED initialization failed")

    wifi = None
    if WIFI_SSID:
        try:
            wifi = network.WLAN(network.STA_IF)
            wifi.active(True)
        except OSError:
            wifi = None
            print("Wi-Fi initialization failed")

    previous = None
    last_connect = None
    last_request = None

    while True:
        distance = filtered_distance(trigger, echo)
        zone = get_zone(distance)
        motion = local_motion(previous, distance)
        source = "LOCAL"
        display_result(display, distance, zone, motion, source)

        connected = False
        now = time.ticks_ms()
        if wifi is not None:
            try:
                connected = wifi.isconnected()
                if not connected and (
                    last_connect is None
                    or time.ticks_diff(now, last_connect) >= 15000
                ):
                    last_connect = now
                    wifi.connect(WIFI_SSID, WIFI_PASSWORD)
            except OSError:
                print("Wi-Fi error")

        if (
            connected
            and API_URL
            and API_KEY
            and previous is not None
            and distance is not None
            and (
                last_request is None
                or time.ticks_diff(now, last_request) >= 3000
            )
        ):
            last_request = now
            try:
                motion = request_motion(previous, distance)
                source = "API"
                display_result(display, distance, zone, motion, source)
            except Exception as error:
                print("API error:", type(error).__name__)

        print("distance_cm={} zone={} motion={} source={}".format(
            distance, zone, motion, source
        ))
        previous = distance


if __name__ == "__main__":
    main()