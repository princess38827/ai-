"""Mock sensors for end-to-end triage pipeline tests."""

from dataclasses import dataclass
from enum import Enum

from max30102_vitals import PulseOxReading
from respiration_sensor import RespirationReading
from vitals_integration import VitalsAggregator


class AVPULevel(Enum):
    ALERT = "ALERT"
    VERBAL = "VERBAL"
    PAIN = "PAIN"
    UNRESPONSIVE = "UNRESPONSIVE"


@dataclass
class PatientScenario:
    name: str
    heart_rate_bpm: float
    spo2_percent: float
    respiratory_rate: int
    capillary_refill_sec: float
    avpu_level: AVPULevel
    can_walk: bool
    pain_reaction: bool = False
    post_reposition_respiratory_rate: int | None = None


class MockPulseOxMonitor:
    def __init__(self, scenario: PatientScenario):
        self.scenario = scenario

    def poll_once(self) -> PulseOxReading:
        quality = "good" if self.scenario.heart_rate_bpm > 0 else "no_signal"
        return PulseOxReading(
            heart_rate_bpm=self.scenario.heart_rate_bpm,
            spo2_percent=self.scenario.spo2_percent,
            signal_quality=quality,
        )


class MockRespirationSensor:
    def __init__(self, scenario: PatientScenario):
        self.scenario = scenario
        self._compute_calls = 0

    def poll(self):
        return None

    def compute(self) -> RespirationReading:
        self._compute_calls += 1
        rate = self.scenario.respiratory_rate
        if self._compute_calls >= 2 and self.scenario.post_reposition_respiratory_rate is not None:
            rate = self.scenario.post_reposition_respiratory_rate
        quality = "good" if rate > 0 else "no_signal"
        return RespirationReading(float(rate), quality)


class _MockCapReading:
    def __init__(self, refill_sec: float):
        self.refill_sec = refill_sec
        self.quality = "good"


class MockCapillaryRefillMonitor:
    def __init__(self, scenario: PatientScenario):
        self.scenario = scenario

    def measure_refill(self, timeout_sec: float = 15.0):
        return _MockCapReading(self.scenario.capillary_refill_sec)

    def close(self):
        return None


class _MockResponsivenessReading:
    def __init__(self, avpu_level: AVPULevel, can_follow: bool):
        self.avpu_level = avpu_level
        self.can_follow_commands = can_follow
        self.needs_pain_stimulus_check = avpu_level == AVPULevel.UNRESPONSIVE


class MockResponsivenessChecker:
    def __init__(self, scenario: PatientScenario):
        self.scenario = scenario

    def speak(self, text: str):
        return None

    def assess(self):
        can_follow = self.scenario.avpu_level == AVPULevel.ALERT
        return _MockResponsivenessReading(self.scenario.avpu_level, can_follow)


class _MockMobReading:
    def __init__(self, can_walk: bool):
        self.can_walk = can_walk


class MockMobilityAssessment:
    def __init__(self, scenario: PatientScenario):
        self.scenario = scenario

    def assess(self, timeout_sec: float = 20.0):
        return _MockMobReading(self.scenario.can_walk)

    def close(self):
        return None


def build_mock_bundle(scenario: PatientScenario):
    pulse = MockPulseOxMonitor(scenario)
    resp = MockRespirationSensor(scenario)
    aggregator = VitalsAggregator(pulse_ox_monitor=pulse, respiration_sensor=resp)

    return {
        "aggregator": aggregator,
        "assess_subjective_kwargs": {
            "capillary_monitor": MockCapillaryRefillMonitor(scenario),
            "responsiveness_checker": MockResponsivenessChecker(scenario),
            "mobility_assessor": MockMobilityAssessment(scenario),
        },
    }
