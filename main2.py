import time
from machine import ADC, Pin

PIR_PIN = 25
LDR_PIN = 34
LAMP_PIN = 26

# Примерные показания LDR по шкале read_u16() от 0 до 65535.
# Замени их результатами своей калибровки из консоли Thonny.
LDR_BRIGHT = 18000
LDR_DARK = 46000

HOLD_SECONDS = 10
PIR_WARMUP_SECONDS = 30

try:
    from config import WIFI_SSID, WIFI_PASSWORD
except ImportError:
    WIFI_SSID = WIFI_PASSWORD = ""


def start_wifi():
    if not WIFI_SSID:
        return None

    import network

    try:
        wifi = network.WLAN(network.STA_IF)
        wifi.active(True)
        wifi.connect(WIFI_SSID, WIFI_PASSWORD)
        return wifi
    except OSError as error:
        print("WIFI ERROR:", error)
        return None


def read_light(ldr):
    total = 0
    for _ in range(5):
        total += ldr.read_u16()
        time.sleep_ms(5)
    return total // 5


def main():
    if LDR_BRIGHT == LDR_DARK:
        raise ValueError("LDR_BRIGHT and LDR_DARK must be different")

    lamp = Pin(LAMP_PIN, Pin.OUT, value=0)
    pir = Pin(PIR_PIN, Pin.IN)
    ldr = ADC(Pin(LDR_PIN), atten=ADC.ATTN_11DB)

    wifi = start_wifi()
    wifi_was_connected = False

    print("A2 STARTED")
    print("LDR calibration:", LDR_BRIGHT, LDR_DARK)
    print("HOLD TIME:", HOLD_SECONDS, "sec")
    print("PIR warm-up:", PIR_WARMUP_SECONDS, "sec")

    started = time.ticks_ms()
    last_report = started
    last_motion = None
    previous_motion = False
    lamp_on = False
    dark = False

    try:
        while True:
            light = read_light(ldr)
            now = time.ticks_ms()

            # 0% соответствует показанию на свету, а 100% — в темноте.
            # Формула работает и для LDR, у которого число в темноте падает.
            darkness = 100 * (light - LDR_BRIGHT) / (LDR_DARK - LDR_BRIGHT)

            if darkness >= 60:
                dark = True
            elif darkness <= 40:
                dark = False

            pir_ready = (
                time.ticks_diff(now, started) >= PIR_WARMUP_SECONDS * 1000
            )
            motion = pir_ready and bool(pir.value())

            if motion != previous_motion:
                print("PIR:", "MOTION" if motion else "NO MOTION")
                previous_motion = motion

            if not dark:
                last_motion = None
            elif motion:
                last_motion = now
            elif (
                last_motion is not None
                and time.ticks_diff(now, last_motion) >= HOLD_SECONDS * 1000
            ):
                last_motion = None

            should_turn_on = last_motion is not None
            if should_turn_on != lamp_on:
                lamp_on = should_turn_on
                lamp.value(int(lamp_on))
                print("LAMP:", "ON" if lamp_on else "OFF")

            if time.ticks_diff(now, last_report) >= 1000:
                last_report = now
                print("LDR:", light, "STATUS:", "DARK" if dark else "LIGHT")

                if wifi is not None:
                    try:
                        connected = wifi.isconnected()
                        if connected and not wifi_was_connected:
                            print("WIFI IP:", wifi.ifconfig()[0])
                        elif not connected and wifi_was_connected:
                            print("WIFI LOST")
                        wifi_was_connected = connected
                    except OSError as error:
                        print("WIFI ERROR:", error)
                        wifi = None

            time.sleep_ms(75)

    except OSError as error:
        print("HARDWARE ERROR:", error)
    finally:
        lamp.off()


if __name__ == "__main__":
    main()