"""
MAX30102 Pulse-Ox / Heart-Rate Sensor Integration
=====================================================

Real I2C driver for the MAX30102 reflective pulse oximeter / heart-rate
module (Maxim Integrated), wired into the robotic EMT vitals pipeline.

Hardware:
  - MAX30102 breakout (e.g. SparkFun, DFRobot, generic clones — all share
    the same register map)
  - I2C address: 0x57 (fixed)
  - Wiring (Raspberry Pi): VIN->3.3V, GND->GND, SCL->GPIO3(SCL), SDA->GPIO2(SDA)
  - Enable I2C: `sudo raspi-config` -> Interface Options -> I2C

Requires:
    pip install smbus2

NOTE on accuracy: the SpO2 formula here is the standard open-source
"ratio-of-ratios" linear approximation (SpO2 = 110 - 25*R). It is
sufficient for prototyping/robotics demos but is NOT clinically
calibrated — do not use for real medical decisions without calibration
against a reference oximeter.
"""

from dataclasses import dataclass
from collections import deque
import time

try:
    from smbus2 import SMBus

    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False


I2C_ADDR = 0x57

REG_FIFO_WR_PTR = 0x04
REG_OVF_COUNTER = 0x05
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07
REG_FIFO_CONFIG = 0x08
REG_MODE_CONFIG = 0x09
REG_SPO2_CONFIG = 0x0A
REG_LED1_PA = 0x0C
REG_LED2_PA = 0x0D
REG_PART_ID = 0xFF


class MAX30102:
    """Low-level I2C driver: init, config, and raw FIFO sample reads."""

    def __init__(self, bus_num: int = 1, addr: int = I2C_ADDR):
        if not HARDWARE_AVAILABLE:
            raise RuntimeError(
                "smbus2 not installed or no I2C bus present. "
                "Run `pip install smbus2` on the target device (e.g. Raspberry Pi)."
            )
        self.bus = SMBus(bus_num)
        self.addr = addr
        self._verify_part_id()
        self._reset()
        self._configure()

    def _write(self, reg: int, val: int):
        self.bus.write_byte_data(self.addr, reg, val)

    def _read(self, reg: int) -> int:
        return self.bus.read_byte_data(self.addr, reg)

    def _verify_part_id(self):
        part_id = self._read(REG_PART_ID)
        if part_id != 0x15:
            raise RuntimeError(
                f"Unexpected PART_ID 0x{part_id:02X} (expected 0x15). "
                "Check wiring / I2C address — is this actually a MAX30102?"
            )

    def _reset(self):
        self._write(REG_MODE_CONFIG, 0x40)
        time.sleep(0.1)

    def _configure(self):
        self._write(REG_FIFO_CONFIG, 0b01001111)
        self._write(REG_MODE_CONFIG, 0x03)
        self._write(REG_SPO2_CONFIG, 0b01100111)
        self._write(REG_LED1_PA, 0x24)
        self._write(REG_LED2_PA, 0x24)
        self._write(REG_FIFO_WR_PTR, 0x00)
        self._write(REG_OVF_COUNTER, 0x00)
        self._write(REG_FIFO_RD_PTR, 0x00)

    def available_samples(self) -> int:
        wr_ptr = self._read(REG_FIFO_WR_PTR)
        rd_ptr = self._read(REG_FIFO_RD_PTR)
        return (wr_ptr - rd_ptr) & 0x1F

    def read_fifo_samples(self):
        n = self.available_samples()
        samples = []
        for _ in range(n):
            data = self.bus.read_i2c_block_data(self.addr, REG_FIFO_DATA, 6)
            red = ((data[0] << 16) | (data[1] << 8) | data[2]) & 0x3FFFF
            ir = ((data[3] << 16) | (data[4] << 8) | data[5]) & 0x3FFFF
            samples.append((red, ir))
        return samples


@dataclass
class PulseOxReading:
    heart_rate_bpm: float
    spo2_percent: float
    signal_quality: str


class SpO2HRCalculator:
    """Rolling-buffer peak detection + ratio-of-ratios SpO2 estimation."""

    def __init__(self, window_size: int = 100, sample_rate_hz: float = 25.0):
        self.window_size = window_size
        self.sample_rate_hz = sample_rate_hz
        self.red_buf = deque(maxlen=window_size)
        self.ir_buf = deque(maxlen=window_size)
        self._recent_ir = deque(maxlen=5)
        self._red_sum = 0.0
        self._ir_sum = 0.0
        self._last_peak_time = None
        self._bpm_estimates = deque(maxlen=5)

    def _append_sample(self, red: int, ir: int):
        if len(self.red_buf) == self.red_buf.maxlen:
            self._red_sum -= self.red_buf[0]
            self._ir_sum -= self.ir_buf[0]
        self.red_buf.append(red)
        self.ir_buf.append(ir)
        self._red_sum += red
        self._ir_sum += ir

    def add_samples(self, samples):
        if not samples:
            return
        now = time.time()
        dt = 1.0 / self.sample_rate_hz
        for i, (red, ir) in enumerate(samples):
            self._append_sample(red, ir)
            self._check_peak(ir, now + (i * dt))

    def _check_peak(self, ir_value: int, timestamp: float):
        self._recent_ir.append(ir_value)
        if len(self._recent_ir) < 5:
            return
        mid = self._recent_ir[2]
        if mid == max(self._recent_ir) and mid > self._recent_ir[0] and mid > self._recent_ir[4]:
            if self._last_peak_time is not None:
                delta = timestamp - self._last_peak_time
                if 0.3 < delta < 2.0:
                    self._bpm_estimates.append(60.0 / delta)
            self._last_peak_time = timestamp

    def compute(self) -> PulseOxReading:
        if len(self.ir_buf) < self.window_size:
            return PulseOxReading(0.0, 0.0, "no_signal")

        ir_dc = self._ir_sum / len(self.ir_buf)
        red_dc = self._red_sum / len(self.red_buf)
        ir_ac = max(self.ir_buf) - min(self.ir_buf)
        red_ac = max(self.red_buf) - min(self.red_buf)

        if ir_dc < 5000 or ir_ac < 50:
            return PulseOxReading(0.0, 0.0, "no_signal")

        ratio_r = (red_ac / red_dc) / (ir_ac / ir_dc)
        spo2 = max(70.0, min(100.0, 110.0 - (25.0 * ratio_r)))
        bpm = sum(self._bpm_estimates) / len(self._bpm_estimates) if self._bpm_estimates else 0.0
        quality = "good" if (ir_ac > 500 and bpm > 0) else "weak"

        return PulseOxReading(round(bpm, 1), round(spo2, 1), quality)


class VitalsMonitor:
    """Polls the MAX30102 and produces live PulseOxReading updates."""

    def __init__(self):
        self.sensor = MAX30102()
        self.calc = SpO2HRCalculator()

    def poll_once(self) -> PulseOxReading:
        samples = self.sensor.read_fifo_samples()
        if samples:
            self.calc.add_samples(samples)
        return self.calc.compute()

    def stream(self, duration_sec: float = 30.0, interval_sec: float = 1.0):
        start = time.time()
        print("Place finger on sensor...")
        while time.time() - start < duration_sec:
            reading = self.poll_once()
            print(
                f"HR: {reading.heart_rate_bpm:5.1f} bpm   "
                f"SpO2: {reading.spo2_percent:5.1f}%   "
                f"Signal: {reading.signal_quality}"
            )
            time.sleep(interval_sec)


if __name__ == "__main__":
    if not HARDWARE_AVAILABLE:
        print(
            "smbus2 / I2C hardware not detected — this script must run on a "
            "device with the MAX30102 physically wired (e.g. Raspberry Pi)."
        )
        print("Install with: pip install smbus2")
    else:
        monitor = VitalsMonitor()
        monitor.stream(duration_sec=30)
