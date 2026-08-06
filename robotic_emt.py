"""
Robotic EMT — Emergency Medical Response Assist Simulation
=============================================================

Simulates a robotic first-responder unit performing:
  1. Rapid scene triage using the START protocol
     (Simple Triage And Rapid Treatment — standard mass-casualty method)
  2. Vitals-based intervention recommendations
  3. Priority-ordered transport/treatment queueing for multiple patients

This is a decision-support / simulation scaffold, not a certified medical
device driver. Swap `read_sensor_vitals()` for real sensor input
(pulse oximeter, capacitive respiration belt, etc.) to drive an actual unit.
"""

from dataclasses import dataclass, field
from enum import Enum
import random


class TriageCategory(Enum):
    RED = "IMMEDIATE"
    YELLOW = "DELAYED"
    GREEN = "MINOR"
    BLACK = "DECEASED"

    @property
    def priority(self) -> int:
        return {"RED": 0, "YELLOW": 1, "GREEN": 2, "BLACK": 3}[self.name]


@dataclass
class VitalSigns:
    respiratory_rate: int
    capillary_refill_sec: float
    radial_pulse_present: bool
    can_follow_commands: bool
    can_walk: bool


@dataclass
class Patient:
    patient_id: str
    vitals: VitalSigns
    triage: TriageCategory = None
    notes: list = field(default_factory=list)


def read_sensor_vitals(patient_id: str) -> VitalSigns:
    return VitalSigns(
        respiratory_rate=random.choice([0, 8, 14, 22, 34]),
        capillary_refill_sec=round(random.uniform(0.5, 4.0), 1),
        radial_pulse_present=random.random() > 0.2,
        can_follow_commands=random.random() > 0.3,
        can_walk=random.random() > 0.7,
    )


class RoboticEMT:
    """Autonomous triage and intervention-recommendation unit."""

    def __init__(self, unit_id: str):
        self.unit_id = unit_id
        self.patients: list[Patient] = []

    def triage_patient(self, patient: Patient, respiration_recheck_fn=None) -> TriageCategory:
        v = patient.vitals

        if v.can_walk:
            patient.notes.append("Ambulatory — directed to minor treatment area.")
            return TriageCategory.GREEN

        if v.respiratory_rate == 0:
            patient.notes.append("Apneic — airway repositioned.")
            if respiration_recheck_fn is not None:
                v.respiratory_rate = respiration_recheck_fn()
            else:
                patient.notes.append(
                    "No live respiration recheck available — treating apnea as confirmed."
                )
            if v.respiratory_rate == 0:
                patient.notes.append("No respiration after airway maneuver.")
                return TriageCategory.BLACK
            patient.notes.append("Respiration returned after repositioning.")
            return TriageCategory.RED

        if v.respiratory_rate > 30:
            patient.notes.append(f"Tachypneic ({v.respiratory_rate}/min).")
            return TriageCategory.RED

        if v.capillary_refill_sec > 2.0 or not v.radial_pulse_present:
            patient.notes.append("Delayed cap refill or absent radial pulse — poor perfusion.")
            return TriageCategory.RED

        if not v.can_follow_commands:
            patient.notes.append("Unable to follow simple commands.")
            return TriageCategory.RED

        return TriageCategory.YELLOW

    def recommend_intervention(self, patient: Patient) -> list[str]:
        v = patient.vitals
        actions = []

        if patient.triage == TriageCategory.RED:
            if v.respiratory_rate == 0:
                actions.append("Begin rescue breathing / prepare for CPR.")
            elif v.respiratory_rate > 30:
                actions.append("Administer high-flow oxygen; monitor for airway compromise.")
            if not v.radial_pulse_present or v.capillary_refill_sec > 2.0:
                actions.append("Control external hemorrhage; consider tourniquet if limb wound.")
                actions.append("Position for shock (supine, legs elevated if no spinal concern).")
            if not v.can_follow_commands:
                actions.append("Continuous neuro status monitoring; protect airway.")
            actions.append("Flag for immediate transport.")

        elif patient.triage == TriageCategory.YELLOW:
            actions.append("Reassess vitals every 5 minutes.")
            actions.append("Splint/dress non-critical injuries while awaiting transport.")

        elif patient.triage == TriageCategory.GREEN:
            actions.append("Direct to minor treatment area; reassess if condition changes.")

        elif patient.triage == TriageCategory.BLACK:
            actions.append("No further intervention; document time and location.")

        return actions

    def assess_scene(self, patient_ids: list[str]):
        for pid in patient_ids:
            vitals = read_sensor_vitals(pid)
            patient = Patient(patient_id=pid, vitals=vitals)
            patient.triage = self.triage_patient(patient)
            self.patients.append(patient)

    def transport_queue(self) -> list[Patient]:
        return sorted(self.patients, key=lambda p: p.triage.priority)

    def report(self):
        print(f"\n=== Robotic EMT Unit {self.unit_id} — Scene Report ===")
        for idx, p in enumerate(self.transport_queue(), start=1):
            print(f"\nPatient #{idx}: {p.triage.value}")
            print(
                f"  RR={p.vitals.respiratory_rate}/min  "
                f"CapRefill={p.vitals.capillary_refill_sec}s  "
                f"Pulse={'Y' if p.vitals.radial_pulse_present else 'N'}  "
                f"FollowsCmds={'Y' if p.vitals.can_follow_commands else 'N'}  "
                f"Walks={'Y' if p.vitals.can_walk else 'N'}"
            )
            for note in p.notes:
                print(f"  - {note}")
            for action in self.recommend_intervention(p):
                print(f"  -> {action}")


if __name__ == "__main__":
    random.seed(42)
    unit = RoboticEMT(unit_id="RESCUE-01")
    unit.assess_scene(patient_ids=[f"P{i + 1}" for i in range(6)])
    unit.report()
