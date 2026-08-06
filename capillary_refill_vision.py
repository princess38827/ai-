"""
Vision-Based Capillary Refill Monitor
=========================================

Automates timing of the standard EMS capillary refill test:
  1. Pressure is applied to a nail bed / fingertip until it blanches (pales)
  2. Pressure is released
  3. Time until normal color returns = capillary refill time (<2s = normal)

This module only handles the VISION/TIMING half — a manipulator or human
still has to physically apply and release the pressure. It watches an ROI
(region of interest) via camera, tracks HSV saturation as a proxy for skin
"pinkness", and times blanch -> release -> color-return automatically.
"""

from dataclasses import dataclass
from enum import Enum, auto
import time

try:
    import cv2

    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False


@dataclass
class CapillaryRefillReading:
    refill_sec: float
    quality: str


class _State(Enum):
    CALIBRATING = auto()
    WAITING_FOR_BLANCH = auto()
    BLANCHED = auto()
    REFILLING = auto()


class CapillaryRefillMonitor:
    def __init__(self, camera_index: int = 0, roi: tuple = None):
        if not HARDWARE_AVAILABLE:
            raise RuntimeError("opencv-python not installed. Run `pip install opencv-python`.")
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera index {camera_index}.")
        self.roi = roi

    def _default_roi(self, frame):
        h, w = frame.shape[:2]
        box_w, box_h = w // 6, h // 6
        return (w // 2 - box_w // 2, h // 2 - box_h // 2, box_w, box_h)

    def _saturation(self, frame) -> float:
        x, y, w, h = self.roi or self._default_roi(frame)
        crop = frame[y : y + h, x : x + w]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        return float(hsv[:, :, 1].mean())

    def measure_refill(
        self, timeout_sec: float = 15.0, calibration_frames: int = 20
    ) -> CapillaryRefillReading:
        state = _State.CALIBRATING
        baseline_samples = []
        blanch_threshold = None
        recover_threshold = None
        release_start = None
        start_time = time.time()

        print("Calibrating baseline color — keep finger still, unpressed...")
        while time.time() - start_time < timeout_sec:
            ok, frame = self.cap.read()
            if not ok:
                return CapillaryRefillReading(0.0, "no_signal")

            sat = self._saturation(frame)
            now = time.time()

            if state == _State.CALIBRATING:
                baseline_samples.append(sat)
                if len(baseline_samples) >= calibration_frames:
                    baseline = sum(baseline_samples) / len(baseline_samples)
                    blanch_threshold = baseline * 0.5
                    recover_threshold = baseline * 0.95
                    state = _State.WAITING_FOR_BLANCH
                    print(f"Baseline set (sat={baseline:.1f}). Apply pressure to blanch now...")

            elif state == _State.WAITING_FOR_BLANCH and sat < blanch_threshold:
                state = _State.BLANCHED
                print("Blanch detected. Release pressure when ready...")

            elif state == _State.BLANCHED and sat > blanch_threshold * 1.15:
                state = _State.REFILLING
                release_start = now
                print("Release detected — timing refill...")

            elif state == _State.REFILLING and sat >= recover_threshold:
                refill_sec = now - release_start
                print(f"Color returned. Capillary refill time: {refill_sec:.2f}s")
                return CapillaryRefillReading(round(refill_sec, 2), "good")

            time.sleep(0.03)

        if release_start is not None:
            elapsed = time.time() - release_start
            print(f"Timeout — refill not complete after {elapsed:.1f}s (delayed).")
            return CapillaryRefillReading(round(elapsed, 2), "timeout")
        return CapillaryRefillReading(0.0, "no_signal")

    def close(self):
        self.cap.release()


if __name__ == "__main__":
    if not HARDWARE_AVAILABLE:
        print("opencv-python not detected. Install with: pip install opencv-python")
    else:
        monitor = CapillaryRefillMonitor(camera_index=0)
        try:
            print(monitor.measure_refill(timeout_sec=15.0))
        finally:
            monitor.close()

