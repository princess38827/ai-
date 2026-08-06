"""
Voice/NLU Responsiveness Checker (AVPU Assessment)
======================================================

Automates the verbal-response portion of the AVPU scale used in EMS
mental-status assessment.
"""

from dataclasses import dataclass
from enum import Enum
import time

try:
    import speech_recognition as sr
    import pyttsx3

    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False


class AVPULevel(Enum):
    ALERT = "ALERT"
    VERBAL = "VERBAL"
    PAIN = "PAIN"
    UNRESPONSIVE = "UNRESPONSIVE"


@dataclass
class ResponsivenessReading:
    avpu_level: AVPULevel
    can_follow_commands: bool
    transcript: str
    needs_pain_stimulus_check: bool


def _looks_coherent(transcript: str) -> bool:
    if not transcript:
        return False
    words = transcript.strip().split()
    if len(words) < 2:
        return False
    return len({w.lower() for w in words}) != 1


class ResponsivenessChecker:
    def __init__(
        self, mic_index: int = None, listen_timeout: float = 6.0, phrase_time_limit: float = 8.0
    ):
        if not HARDWARE_AVAILABLE:
            raise RuntimeError("Missing dependencies. Run: pip install SpeechRecognition pyttsx3 pyaudio")
        self.recognizer = sr.Recognizer()
        self.mic = sr.Microphone(device_index=mic_index)
        self.listen_timeout = listen_timeout
        self.phrase_time_limit = phrase_time_limit
        self.tts = pyttsx3.init()

        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1.0)

    def speak(self, text: str):
        print(f"[TTS] {text}")
        self.tts.say(text)
        self.tts.runAndWait()

    def listen(self) -> str:
        with self.mic as source:
            try:
                audio = self.recognizer.listen(
                    source, timeout=self.listen_timeout, phrase_time_limit=self.phrase_time_limit
                )
            except sr.WaitTimeoutError:
                return ""
        try:
            return self.recognizer.recognize_google(audio)
        except (sr.UnknownValueError, sr.RequestError):
            return ""

    def assess(self, retry_once: bool = True) -> ResponsivenessReading:
        self.speak("Can you hear me? Please tell me your name and where you are.")
        transcript = self.listen()

        if not transcript and retry_once:
            self.speak("I need you to respond. Can you hear my voice?")
            time.sleep(0.5)
            transcript = self.listen()

        if not transcript:
            print("No verbal response detected — pain stimulus check required (manipulator).")
            return ResponsivenessReading(
                avpu_level=AVPULevel.UNRESPONSIVE,
                can_follow_commands=False,
                transcript="",
                needs_pain_stimulus_check=True,
            )

        if _looks_coherent(transcript):
            print(f'Coherent response: "{transcript}"')
            return ResponsivenessReading(
                avpu_level=AVPULevel.ALERT,
                can_follow_commands=True,
                transcript=transcript,
                needs_pain_stimulus_check=False,
            )

        print(f'Responded to voice but incoherently: "{transcript}"')
        return ResponsivenessReading(
            avpu_level=AVPULevel.VERBAL,
            can_follow_commands=False,
            transcript=transcript,
            needs_pain_stimulus_check=False,
        )


if __name__ == "__main__":
    if not HARDWARE_AVAILABLE:
        print("Missing dependencies. Install with: pip install SpeechRecognition pyttsx3 pyaudio")
    else:
        checker = ResponsivenessChecker()
        print(checker.assess())

