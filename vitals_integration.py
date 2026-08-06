"""
Vitals Integration — merges real sensor readings into VitalSigns.
"""

import time
from dataclasses import dataclass

from max30102_vitals import VitalsMonitor, PulseOxReading
from respiration_sensor import MCP3008, RespirationBeltSensor, RespirationReading
from robotic_emt import VitalSigns, Patient, RoboticEMT

try:
    from capillary_refill_vision import CapillaryRefillMonitor

    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False

try:
    from responsiveness_voice import ResponsivenessChecker, AVPULevel

    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    AVPULevel = None

try:
    from mobility_assessment import MobilityAssessment

    MOBILITY_AVAILABLE = True
except ImportError:
    MOBILITY_AVAILABLE = False


@dataclass
class AssessmentInputs:
    capillary_refill_sec: float = 1.5
    can_follow_commands: bool = True
    can_walk: bool = False


def assess_subjective(
    camera_index: int = 0,
    mic_index: int = None,
    capillary_monitor=None,
    responsiveness_checker=None,
    mobility_assessor=None,
) -> AssessmentInputs:
    result = AssessmentInputs()

    cap_monitor = capillary_monitor
    if cap_monitor is None and VISION_AVAILABLE:
        cap_monitor = CapillaryRefillMonitor(camera_index=camera_index)
    if cap_monitor is not None:
        try:
            reading = cap_monitor.measure_refill(timeout_sec=15.0)
            if reading.quality != "no_signal":
                result.capillary_refill_sec = reading.refill_sec
        finally:
            cap_monitor.close()

    checker = responsiveness_checker
    if checker is None and VOICE_AVAILABLE:
        checker = ResponsivenessChecker(mic_index=mic_index)
    if checker is not None:
        reading = checker.assess()
        result.can_follow_commands = reading.can_follow_commands

        mobility = mobility_assessor
        avpu_value = getattr(reading.avpu_level, "value", str(reading.avpu_level))
        if str(avpu_value).upper() == "ALERT":
            if mobility is None and MOBILITY_AVAILABLE:
                mobility = MobilityAssessment(camera_index=camera_index, announce=checker.speak)
            if mobility is not None:
                try:
                    mobility_reading = mobility.assess(timeout_sec=20.0)
                    result.can_walk = mobility_reading.can_walk
                finally:
                    mobility.close()

    return result


class VitalsAggregator:
    """Polls both sensors and produces a triage-ready VitalSigns snapshot."""

    def __init__(self, respiration_adc_channel: int = 0, pulse_ox_monitor=None, respiration_sensor=None):
        self.pulse_ox = pulse_ox_monitor or VitalsMonitor()
        if respiration_sensor is not None:
            self.respiration = respiration_sensor
        else:
            adc = MCP3008()
            self.respiration = RespirationBeltSensor(adc, channel=respiration_adc_channel)

    def warm_up(self, seconds: float = 8.0, poll_interval_sec: float = 0.1):
        if seconds <= 0:
            return
        print(f"Warming up sensors ({seconds}s) — keep contact steady...")
        end_at = time.time() + seconds
        while time.time() < end_at:
            self.pulse_ox.poll_once()
            self.respiration.poll()
            time.sleep(poll_interval_sec)

    def capture(self) -> tuple[PulseOxReading, RespirationReading]:
        po_reading = self.pulse_ox.poll_once()
        self.respiration.poll()
        return po_reading, self.respiration.compute()

    def recheck_respiration(self) -> int:
        self.respiration.poll()
        reading = self.respiration.compute()
        return int(round(reading.breaths_per_min))

    def build_vital_signs(self, assessment: AssessmentInputs = None) -> VitalSigns:
        assessment = assessment or AssessmentInputs()
        po_reading, resp_reading = self.capture()
        return VitalSigns(
            respiratory_rate=int(round(resp_reading.breaths_per_min)),
            capillary_refill_sec=assessment.capillary_refill_sec,
            radial_pulse_present=(po_reading.signal_quality != "no_signal" and po_reading.heart_rate_bpm > 0),
            can_follow_commands=assessment.can_follow_commands,
            can_walk=assessment.can_walk,
        )


def run_live_triage(
    patient_id: str,
    assessment: AssessmentInputs = None,
    auto_assess_subjective: bool = True,
    camera_index: int = 0,
    mic_index: int = None,
    aggregator: VitalsAggregator = None,
    assess_subjective_kwargs: dict = None,
    warmup_seconds: float = 8.0,
):
    if auto_assess_subjective and assessment is None:
        assessment = assess_subjective(
            camera_index=camera_index, mic_index=mic_index, **(assess_subjective_kwargs or {})
        )

    aggregator = aggregator or VitalsAggregator()
    aggregator.warm_up(seconds=warmup_seconds)

    vitals = aggregator.build_vital_signs(assessment)
    patient = Patient(patient_id=patient_id, vitals=vitals)

    unit = RoboticEMT(unit_id="RESCUE-01")
    patient.triage = unit.triage_patient(patient, respiration_recheck_fn=aggregator.recheck_respiration)
    unit.patients.append(patient)
    unit.report()
    return patient
