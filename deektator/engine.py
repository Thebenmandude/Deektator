import array
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path


SAMPLE_RATE = 16_000
MAX_SECONDS = 120
RELEASE_TAIL_MS = 140
APP_ID = "io.github.deektator.Deektator"
TOOLS = Path(__file__).resolve().parents[2] / "tools"
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "deektator"
MODELS = {
    "ggml-small.en-q5_1.bin": "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30",
    "ggml-small-q5_1.bin": "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
}

FILLER = re.compile(r"\b(?:um+|uh+|erm+)\b[ \t]*[,;]?[ \t]*", re.IGNORECASE)
NON_SPEECH = re.compile(r"\[(?:blank_audio|silence|music|applause)\]|♪+", re.IGNORECASE)


class DictationError(Exception):
    pass


def clean_transcript(text, language, remove_fillers):
    text = NON_SPEECH.sub("", text)
    if remove_fillers and language == "en":
        text = FILLER.sub("", text)
    paragraphs = re.split(r"\n\s*\n", text)
    cleaned = []
    for paragraph in paragraphs:
        paragraph = " ".join(paragraph.split())
        paragraph = re.sub(r" +([,.;!?])", r"\1", paragraph)
        if remove_fillers and language == "en":
            paragraph = re.sub(r"[,;](?=[.!?])", "", paragraph)
            paragraph = re.sub(r"^[,;.!?]+\s*|(?<=[.!?])\s+[,;.!?]+(?=\s|$)", "", paragraph)
            paragraph = re.sub(r"(^|[.!?] )([a-z])", lambda match: match[0].upper(), paragraph)
        if any(character.isalnum() for character in paragraph):
            cleaned.append(paragraph)
    return "\n\n".join(cleaned)


class Whisper:
    def __init__(self, binary, model, language, remove_fillers):
        bundled_binary = TOOLS / "whisper.cpp/build/bin/whisper-cli"
        self.binary = binary or shutil.which("whisper-cli") or str(bundled_binary)
        self.custom_model = model
        self.small_model = "ggml-small.en-q5_1.bin" if language == "en" else "ggml-small-q5_1.bin"
        self.language = language
        self.remove_fillers = remove_fillers

    @property
    def model(self):
        if self.custom_model:
            return self.custom_model
        for filename in (self.small_model, "ggml-base.bin"):
            for directory in (DATA, TOOLS / "whisper-models"):
                candidate = directory / filename
                if candidate.is_file():
                    return candidate
        return DATA / self.small_model

    def download_model(self, cancel=None):
        cancel = cancel or threading.Event()
        DATA.mkdir(parents=True, exist_ok=True)
        destination = DATA / self.small_model
        url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{self.small_model}?download=true"
        checksum = hashlib.sha256()
        with tempfile.TemporaryDirectory(prefix="model-", dir=DATA) as directory:
            temporary = Path(directory) / self.small_model
            with urllib.request.urlopen(url, timeout=12) as response, temporary.open("wb") as output:
                while not cancel.is_set():
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    checksum.update(chunk)
                    output.write(chunk)
            if cancel.is_set():
                raise DictationError("Model download cancelled.")
            if checksum.hexdigest() != MODELS[self.small_model]:
                raise DictationError("The download did not match the published model checksum.")
            temporary.replace(destination)
        return destination

    def validate(self):
        if not shutil.which(self.binary):
            raise DictationError("Whisper executable is missing. Set --whisper to the path to whisper-cli.")
        if not self.model.is_file():
            raise DictationError(f"Whisper model is missing at {self.model}. Download Whisper Small or pass --model.")

    def transcribe(self, audio, cancel=None):
        self.validate()
        cancel = cancel or threading.Event()
        with tempfile.TemporaryDirectory(prefix="deektator-text-") as tmp:
            output = Path(tmp) / "transcript"
            command = [
                self.binary, "-m", str(self.model), "-f", str(audio), "-l", self.language,
                "-nt", "-otxt", "-of", str(output), "-ng", "-sns", "-t", str(min(os.cpu_count() or 1, 4)),
            ]
            with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as process:
                deadline = time.monotonic() + 300
                while True:
                    if cancel.is_set() or time.monotonic() >= deadline:
                        process.kill()
                        process.communicate()
                        reason = "Transcription cancelled." if cancel.is_set() else "Transcription timed out."
                        raise DictationError(reason)
                    try:
                        _, errors = process.communicate(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode or not output.with_suffix(".txt").is_file():
                    error_lines = errors.decode(errors="replace").strip().splitlines()
                    detail = next((line for line in reversed(error_lines) if "error" in line.lower()), "")
                    raise DictationError(f"Whisper could not transcribe the recording. {detail}".strip())
            return clean_transcript(
                output.with_suffix(".txt").read_text(encoding="utf-8"), self.language, self.remove_fillers
            )


def microphone_sources():
    result = subprocess.run(
        ["pactl", "--format=json", "list", "sources"], capture_output=True, check=True, timeout=3,
    )
    sources = [
        (source["name"], source.get("description") or source["name"])
        for source in json.loads(result.stdout)
        if not source["name"].endswith(".monitor") and (source.get("properties") or {}).get("device.class") != "monitor"
    ]
    try:
        default = subprocess.run(["pactl", "get-default-source"], capture_output=True, check=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return sources, None
    return sources, default.stdout.decode(errors="replace").strip()


def decode_samples(pcm):
    samples = array.array("h", pcm[:len(pcm) & ~1])
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def rms(samples):
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0


def normalize_quiet_audio(samples):
    peak = max(map(abs, samples), default=0)
    # Use several loud windows so a long pause or one transient has little weight.
    window = SAMPLE_RATE // 10
    levels = sorted(rms(samples[offset:offset + window]) for offset in range(0, len(samples), window))
    voice_level = levels[-min(3, len(levels))] if levels else 0
    if peak <= 32 or voice_level <= 16:
        return None
    gain = min(4, 3200 / voice_level, 30_000 / peak)
    if gain > 1.05:
        samples = array.array("h", (round(sample * gain) for sample in samples))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


class Recording:
    def __init__(self, source=None):
        if not shutil.which("parec"):
            raise DictationError("Install pulseaudio-utils to record from your microphone (parec).")
        self.temp = tempfile.TemporaryDirectory(prefix="deektator-audio-")
        self.raw = Path(self.temp.name) / "capture.pcm"
        self.errors = Path(self.temp.name) / "capture.log"
        try:
            with self.raw.open("wb") as audio, self.errors.open("wb") as errors:
                command = [
                    "parec", "--raw", f"--rate={SAMPLE_RATE}", "--channels=1", "--format=s16le",
                    "--latency-msec=30", "--process-time-msec=10", "--client-name=Deektator", "--stream-name=Dictation",
                ]
                if source:
                    command += ["--device", source]
                self.process = subprocess.Popen(command, stdout=audio, stderr=errors)
        except OSError:
            self.temp.cleanup()
            raise

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()

    def input_level(self):
        with self.raw.open("rb") as capture:
            size = capture.seek(0, os.SEEK_END) & ~1
            if not size:
                return None
            capture.seek(max(0, size - SAMPLE_RATE // 5))
            return min(1, rms(decode_samples(capture.read(SAMPLE_RATE // 5))) / 4000)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.temp.cleanup()

    def to_wav(self):
        self.stop()
        try:
            result = self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise DictationError("The microphone recorder did not stop.") from None
        if result not in (0, -15, 143):
            detail = self.errors.read_text(errors="replace").strip()
            raise DictationError(f"Could not record from the default microphone. {detail}".strip())
        with self.raw.open("rb") as capture:
            pcm = capture.read(MAX_SECONDS * SAMPLE_RATE * 2)
        samples = decode_samples(pcm)
        if not samples:
            raise DictationError("No audio arrived from the microphone. Choose another input or check its connection.")
        if len(samples) < SAMPLE_RATE // 4:
            return None
        pcm = normalize_quiet_audio(samples)
        if pcm is None:
            return None
        audio = self.raw.with_suffix(".wav")
        with wave.open(str(audio), "wb") as wav:
            wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        return audio
