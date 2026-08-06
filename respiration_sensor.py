"""
Respiration Belt Sensor Integration (MCP3008 + Piezo Stretch Belt)
=======================================================================

Piezoelectric respiration belts output a slowly-varying analog voltage as
the chest expands/contracts. The Pi has no analog input pins, so we read
it through an MCP3008 8-channel SPI ADC — the standard companion chip for
analog sensors on a Pi.

Hardware:
  - MCP3008 wired via SPI (VDD/VREF->3.3V, AGND/DGND->GND,
    CLK->GPIO11, DOUT->GPIO9, DIN->GPIO10, CS->GPIO8)
  - Respiration belt's analog output -> MCP3008 channel 0 (configurable)
  - Enable SPI: `sudo raspi-config` -> Interface Options -> SPI

Requires:
    pip install spidev
"""

from dataclasses import dataclass
from collections import deque
import time

try:
    import spidev

    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False


class MCP3008:
    """Minimal MCP3008 SPI ADC driver (10-bit, single-ended reads)."""

    def __init__(self, bus: int = 0, device: int = 0, max_speed_hz: int = 1350000):
        if not HARDWARE_AVAILABLE:
            raise RuntimeError(
                "spidev not installed or no SPI bus present. "
                "Run `pip install spidev` on the target device (e.g. Raspberry Pi)."
            )
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = max_speed_hz

    def read_channel(self, channel: int) -> int:
        """Return raw 10-bit ADC value (0-1023) for channel 0-7."""
        if not 0 <= channel <= 7:
            raise ValueError("MCP3008 channel must be 0-7")
        cmd = [1, (8 + channel) << 4, 0]
        reply = self.spi.xfer2(cmd)
        return ((reply[1] & 3) << 8) + reply[2]

    def close(self):
        self.spi.close()


@dataclass
class RespirationReading:
    breaths_per_min: float
    signal_quality: str


class RespirationBeltSensor:
    """
    Detects breathing cycles from a piezo belt's analog stretch signal.

    Runtime-focused implementation:
    - O(1) smoothing via rolling sums
    - O(1) rolling baseline via running smoothed sum
    """

    def __init__(
        self,
        adc: MCP3008,
        channel: int = 0,
        smoothing_window: int = 8,
        history_seconds: float = 30.0,
        sample_rate_hz: float = 10.0,
    ):
        self.adc = adc
        self.channel = channel
        self.sample_rate_hz = sample_rate_hz
        self.raw_buf = deque(maxlen=smoothing_window)
        self._raw_sum = 0.0
        max_len = int(history_seconds * sample_rate_hz)
        self.smoothed_buf = deque(maxlen=max_len)
        self._smoothed_sum = 0.0
        self._smoothed_minq = deque()
        self._smoothed_maxq = deque()
        self.timestamps = deque(maxlen=max_len)
        self._breath_times = deque(maxlen=6)
        self._recent = deque(maxlen=5)
        self._rising = False

    def _append_rolling(self, buf: deque, val: float, current_sum: float) -> float:
        if len(buf) == buf.maxlen:
            current_sum -= buf[0]
        buf.append(val)
        return current_sum + val

    def _smooth(self, raw_value: int) -> float:
        self._raw_sum = self._append_rolling(self.raw_buf, raw_value, self._raw_sum)
        return self._raw_sum / len(self.raw_buf)

    def _append_smoothed(self, val: float):
        if len(self.smoothed_buf) == self.smoothed_buf.maxlen:
            old = self.smoothed_buf[0]
            self._smoothed_sum -= old
            if self._smoothed_minq and old == self._smoothed_minq[0]:
                self._smoothed_minq.popleft()
            if self._smoothed_maxq and old == self._smoothed_maxq[0]:
                self._smoothed_maxq.popleft()

        self.smoothed_buf.append(val)
        self._smoothed_sum += val

        while self._smoothed_minq and self._smoothed_minq[-1] > val:
            self._smoothed_minq.pop()
        self._smoothed_minq.append(val)

        while self._smoothed_maxq and self._smoothed_maxq[-1] < val:
            self._smoothed_maxq.pop()
        self._smoothed_maxq.append(val)

    def poll(self):
        raw = self.adc.read_channel(self.channel)
        now = time.time()
        smoothed = self._smooth(raw)
        self._append_smoothed(smoothed)
        self.timestamps.append(now)
        self._detect_breath(smoothed, now)

    def _detect_breath(self, value: float, timestamp: float):
        self._recent.append(value)
        if len(self._recent) < 5:
            return

        baseline = self._smoothed_sum / len(self.smoothed_buf)
        threshold = baseline * 1.03
        prev = self._recent[-2]

        if not self._rising and value > threshold and prev <= threshold:
            self._rising = True
            if self._breath_times and (timestamp - self._breath_times[-1]) < 1.5:
                return
            self._breath_times.append(timestamp)
        elif value < baseline:
            self._rising = False

    def compute(self) -> RespirationReading:
        if not self.smoothed_buf or len(self.smoothed_buf) < self.smoothed_buf.maxlen // 4:
            return RespirationReading(0.0, "no_signal")

        signal_span = self._smoothed_maxq[0] - self._smoothed_minq[0]
        if signal_span < 3:
            return RespirationReading(0.0, "no_signal")

        if len(self._breath_times) >= 2:
            intervals = [t2 - t1 for t1, t2 in zip(self._breath_times, list(self._breath_times)[1:])]
            avg_interval = sum(intervals) / len(intervals)
            bpm = 60.0 / avg_interval if avg_interval > 0 else 0.0
            bpm = max(0.0, min(60.0, bpm))
            quality = "good" if 4 <= bpm <= 60 else "weak"
            return RespirationReading(round(bpm, 1), quality)

        return RespirationReading(0.0, "weak")

    def stream(self, duration_sec: float = 60.0):
        interval = 1.0 / self.sample_rate_hz
        start = time.time()
        print("Reading respiration belt...")
        while time.time() - start < duration_sec:
            self.poll()
            reading = self.compute()
            print(f"RR: {reading.breaths_per_min:5.1f} breaths/min   Signal: {reading.signal_quality}")
            time.sleep(interval)


if __name__ == "__main__":
    if not HARDWARE_AVAILABLE:
        print(
            "spidev / SPI hardware not detected — this script must run on a "
            "device with the MCP3008 + respiration belt physically wired."
        )
        print("Install with: pip install spidev")
    else:
        adc = MCP3008()
        belt = RespirationBeltSensor(adc, channel=0)
        belt.stream(duration_sec=60)
