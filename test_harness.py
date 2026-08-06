"""
Test Harness — End-to-End Triage Pipeline, No Physical Hardware Required.
"""

from robotic_emt import TriageCategory
from vitals_integration import run_live_triage
from mock_sensors import PatientScenario, build_mock_bundle, AVPULevel


SCENARIOS = [
    dict(
        scenario=PatientScenario(
            name="Minor — ambulatory",
            heart_rate_bpm=88,
            spo2_percent=98,
            respiratory_rate=16,
            capillary_refill_sec=1.0,
            avpu_level=AVPULevel.ALERT,
            can_walk=True,
        ),
        expected={TriageCategory.GREEN},
    ),
    dict(
        scenario=PatientScenario(
            name="Delayed — stable, non-ambulatory",
            heart_rate_bpm=78,
            spo2_percent=97,
            respiratory_rate=18,
            capillary_refill_sec=1.2,
            avpu_level=AVPULevel.ALERT,
            can_walk=False,
        ),
        expected={TriageCategory.YELLOW},
    ),
    dict(
        scenario=PatientScenario(
            name="Immediate — tachypneic",
            heart_rate_bpm=110,
            spo2_percent=91,
            respiratory_rate=34,
            capillary_refill_sec=1.0,
            avpu_level=AVPULevel.ALERT,
            can_walk=False,
        ),
        expected={TriageCategory.RED},
    ),
    dict(
        scenario=PatientScenario(
            name="Immediate — poor perfusion",
            heart_rate_bpm=130,
            spo2_percent=94,
            respiratory_rate=20,
            capillary_refill_sec=3.0,
            avpu_level=AVPULevel.ALERT,
            can_walk=False,
        ),
        expected={TriageCategory.RED},
    ),
    dict(
        scenario=PatientScenario(
            name="Immediate — unresponsive, no pain reaction",
            heart_rate_bpm=82,
            spo2_percent=96,
            respiratory_rate=18,
            capillary_refill_sec=1.0,
            avpu_level=AVPULevel.UNRESPONSIVE,
            can_walk=False,
            pain_reaction=False,
        ),
        expected={TriageCategory.RED},
    ),
    dict(
        scenario=PatientScenario(
            name="Apneic — confirmed, no recovery after reposition",
            heart_rate_bpm=0,
            spo2_percent=70,
            respiratory_rate=0,
            post_reposition_respiratory_rate=0,
            capillary_refill_sec=1.0,
            avpu_level=AVPULevel.UNRESPONSIVE,
            can_walk=False,
            pain_reaction=False,
        ),
        expected={TriageCategory.BLACK},
    ),
    dict(
        scenario=PatientScenario(
            name="Apneic — breathing resumes after airway reposition",
            heart_rate_bpm=60,
            spo2_percent=85,
            respiratory_rate=0,
            post_reposition_respiratory_rate=20,
            capillary_refill_sec=1.0,
            avpu_level=AVPULevel.UNRESPONSIVE,
            can_walk=False,
            pain_reaction=False,
        ),
        expected={TriageCategory.RED},
    ),
]


def run_all():
    results = []
    for case in SCENARIOS:
        scenario = case["scenario"]
        print(f"\n{'=' * 60}\nSCENARIO: {scenario.name}\n{'=' * 60}")
        bundle = build_mock_bundle(scenario)
        patient = run_live_triage(
            patient_id=scenario.name,
            aggregator=bundle["aggregator"],
            assess_subjective_kwargs=bundle["assess_subjective_kwargs"],
            warmup_seconds=0.2,
        )
        passed = patient.triage in case["expected"]
        results.append((scenario.name, patient.triage, case["expected"], passed))

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    all_passed = True
    for name, actual, expected, passed in results:
        status = "PASS" if passed else "FAIL"
        all_passed = all_passed and passed
        expected_str = "/".join(e.value for e in expected)
        print(f"[{status}] {name}: got {actual.value}, expected {expected_str}")

    print(f"\n{'ALL SCENARIOS PASSED' if all_passed else 'SOME SCENARIOS FAILED'}")
    return all_passed


if __name__ == "__main__":
    import sys

    success = run_all()
    sys.exit(0 if success else 1)

