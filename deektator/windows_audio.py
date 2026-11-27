"""PortAudio microphone capture for Windows."""

import threading

from .engine import MAX_SECONDS, DictationError, decode_samples, rms, write_recording


def microphones(audio):
    host_apis = audio.query_hostapis()
    wasapi = next((api for api in host_apis if "WASAPI" in api["name"]), None)
    devices = audio.query_devices()
    if wasapi and any(devices[index]["max_input_channels"] for index in wasapi["devices"]):
        indices = wasapi["devices"]
        default = wasapi["default_input_device"]
    else:
        indices = range(len(devices))
        default = audio.default.device[0]
    inputs = [(index, devices[index]["name"]) for index in indices if devices[index]["max_input_channels"]]
    return inputs, default if default in dict(inputs) else (inputs[0][0] if inputs else None)


class WindowsRecording:
    def __init__(self, audio, device):
        self.audio = audio
        self.device = device
        self.pcm = bytearray()
        self.latest = b""
        self.sample_rate = None
        self.error = None
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self.capture, name="windows-microphone", daemon=True)
        self.worker.start()

    def capture(self):
        try:
            device = self.audio.query_devices(self.device, "input")
            self.sample_rate = round(device["default_samplerate"])
            host = self.audio.query_hostapis(device["hostapi"])
            options = {}
            if "WASAPI" in host["name"]:
                options["extra_settings"] = self.audio.WasapiSettings(auto_convert=True)
            with self.audio.RawInputStream(
                device=self.device, samplerate=self.sample_rate, channels=1, dtype="int16",
                latency="low", **options,
            ) as stream:
                limit = MAX_SECONDS * self.sample_rate * 2
                while not self.stop.is_set() and len(self.pcm) < limit:
                    if not stream.active:
                        raise DictationError("The microphone disconnected.")
                    available = min(stream.read_available, self.sample_rate // 20, (limit - len(self.pcm)) // 2)
                    if available <= 0:
                        self.stop.wait(0.01)
                        continue
                    data, _overflowed = stream.read(available)
                    self.latest = bytes(data)
                    self.pcm.extend(self.latest)
        except (OSError, ValueError, DictationError, self.audio.PortAudioError) as error:
            self.error = str(error)

    def input_level(self):
        block = self.latest
        return min(1, rms(decode_samples(block)) / 4000) if block else None

    def to_wav(self, destination):
        self.stop.set()
        self.worker.join(timeout=3)
        if self.worker.is_alive():
            raise DictationError("The microphone did not respond. Check the device and try again.")
        if self.error is not None:
            raise DictationError(f"Could not record from the microphone. {self.error}")
        return write_recording(self.pcm, destination, self.sample_rate)
