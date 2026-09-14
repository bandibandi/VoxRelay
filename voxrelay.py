import os
import sys

if "LD_LIBRARY_PATH" not in os.environ:
    try:
        import glob
        import nvidia
        nvidia_paths = set()
        for base in nvidia.__path__:
            nvidia_paths.update(os.path.dirname(p) for p in glob.glob(os.path.join(base, "*", "lib", "*.so*")))
        os.environ["LD_LIBRARY_PATH"] = ":".join(sorted(nvidia_paths))
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except ImportError:
        pass

import sounddevice as sd
import numpy as np
import queue
import shutil
import threading
import tomllib
import re
import unicodedata
from evdev import InputDevice, ecodes
from faster_whisper import WhisperModel
import logging
LOG = logging.getLogger("voxrelay")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)



with open("config/config.toml", "rb") as f:
    CONFIG = tomllib.load(f)

if CONFIG.get("offline_mode"):
    os.environ["HF_HUB_OFFLINE"] = "1"

DIALOG_PYTHON = CONFIG.get("dialog_python", "/usr/bin/python3")


def beep(kind: str) -> None:
    import subprocess
    sounds = {
        "start": CONFIG["sound_start"],
        "stop": CONFIG["sound_stop"],
        "error": CONFIG["sound_error"],
    }
    subprocess.Popen(["paplay", sounds[kind]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def save_transcript(text: str) -> None:
    if not CONFIG["save_transcript"]:
        return
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open (CONFIG["transcript_file"], "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {text}\n")

def save_command_log(run_id: str, phrase: str, command: str, ran: bool) -> None:
    if not CONFIG["save_command_log"]:
        return
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "RAN" if ran else "SKIPPED"
    with open(CONFIG["command_log_file"], "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] #{run_id} {status} {phrase!r} -> {command}\n")


def find_device(name: str) -> InputDevice:
    from evdev import list_devices
    for path in list_devices():
        dev = InputDevice(path)
        if dev.name == name:
            return dev
        dev.close()
    raise SystemExit("Device not found: " + name)

def parse_trigger(value: str) -> tuple[str, int]:
    if value.lower().startswith("0x"):
        return "scancode", int(value, 16)
    return "keycode", getattr(ecodes, value)

def matches(trigger: tuple[str, int], event, last_scan) -> bool:
    kind, code = trigger
    if kind == "scancode":
        return last_scan == code
    return event.code == code


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("ly", "j")
    return re.sub(r"[^\w]", "", stripped)


def parse_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [
            stripped
            for line in f.read().splitlines()
            if (stripped := line.strip()) and not stripped.startswith("#")
        ]

def parse_toml(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


class WatchedFile:
    def __init__(self, path: str, parser, empty) -> None:
        self.path = path
        self.parser = parser
        self.empty = empty
        self._mtime = None
        self._data = empty

    def get(self):
        try:
            mtime = os.path.getmtime(self.path)
        except FileNotFoundError:
            self._mtime = None
            self._data = self.empty
            return self._data

        if mtime != self._mtime:
            self._mtime = mtime
            self._data = self.parser(self.path)
            LOG.info("Reloaded %s: %d entries", self.path, len(self._data))

        return self._data



class Recorder:
    def __init__(self) -> None:
        self.last_length = 0
        self._frames = queue.Queue()
        self._stream = None

    def start(self) -> None:
        beep("start")

        def callback(indata, frames, time_info ,status):
            self._frames.put(indata.copy())
        self._stream = sd.InputStream(samplerate=CONFIG["sample_rate"], channels=1, dtype="float32", callback=callback)
        self._stream.start()
        LOG.info("Recording started, hold the button!")

    def stop(self) -> np.ndarray:
        beep("stop")
        self._stream.stop()
        self._stream.close()
        chunks = []
        while not self._frames.empty():
            chunks.append(self._frames.get_nowait())
        if not chunks:
            LOG.info("No audio captured (tap too short)")
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(chunks, axis=0).flatten()
        self.last_length = len(audio)
        LOG.info("Done! Length: %d", len(audio))
        LOG.info("Loudness: %.4f", np.abs(audio).max())
        return audio

class Transcriber:
    def __init__(self) -> None:
        self.model = WhisperModel(CONFIG["model"], device=CONFIG["device"], compute_type=CONFIG["compute_type"])
        self.dictionary = WatchedFile(CONFIG["dictionary"], parse_lines, [])
        self.blocklist = WatchedFile(CONFIG["blocklist"], parse_lines, [])
        self.profanity = WatchedFile(CONFIG["profanity"], parse_lines, [])

    def _build_prompt(self) -> str:
        if not CONFIG["use_dictionary"]:
            return ""
        words = self.dictionary.get()
        kept = []
        used = 0
        for word in words:
            cost = len(word.split()) * CONFIG["tokens_per_word"]
            if used + cost > CONFIG["prompt_token_budget"]:
                break
            kept.append(word)
            used = used + cost
        percent = used / CONFIG["prompt_token_budget"] * 100
        LOG.info("Dictionary budget used: %.1f%%", percent)
        return ", ".join(kept)


    def transcribe_raw(self, audio: np.ndarray, prompt: str | None = None) -> str:
        if prompt is None:
            prompt = self._build_prompt()
        segments, _ = self.model.transcribe(
            audio,
            language=CONFIG["language"],
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": CONFIG["vad_min_silence_ms"],
                "speech_pad_ms": CONFIG["vad_speech_pad_ms"],
            },
            initial_prompt=prompt,
        )
        return "".join(segment.text for segment in segments).strip()

    def transcribe(self, audio: np.ndarray) -> str:
        full_text = self.transcribe_raw(audio)
        sentences = re.split(r"(?<=[.!?])\s+", full_text)

        blocklist_patterns = [_normalise(p) for p in self.blocklist.get()] if CONFIG["use_blocklist"] else []
        profanity_patterns = [_normalise(p) for p in self.profanity.get()] if CONFIG["use_profanity"] else []

        kept = []
        for sentence in sentences:
            norm = _normalise(sentence)
            if any(pattern and pattern in norm for pattern in blocklist_patterns):
                LOG.info("Blocklist dropped: %r", sentence.strip())
                beep("error")
                continue
            kept.append(self._censor(sentence, profanity_patterns))
        return " ".join(kept)


    def _censor(self, sentence: str, patterns: list[str]) -> str:
        words = sentence.split(" ")
        for i, word in enumerate(words):
            norm = _normalise(word)
            if any(pattern and pattern in norm for pattern in patterns):
                LOG.info("Profanity censored: %r", word)
                beep("error")
                words[i] = "[cenzúrázva]"
        return " ".join(words)



class Injector:
    def inject(self, text: str) -> None:
        import subprocess
        if CONFIG["inject_method"] == "clipboard":
            self._via_clipboard(text)
        else:
            self._via_xdotool(text)

    def _via_xdotool(self, text: str) -> None:
        import subprocess
        subprocess.run(["xdotool", "type", "--", text])

    def _via_clipboard(self, text: str) -> None:
        import subprocess
        import time
        saved = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True).stdout
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"))
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        time.sleep(0.25)
        subprocess.run(["xclip", "-selection", "clipboard"], input=saved)


class CommandRunner:
    def __init__(self, recorder: Recorder, transcriber: Transcriber) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.commands = WatchedFile(CONFIG["commands_file"], parse_toml, {})


    def on_press(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            LOG.error("Error occurred: %s", e)
            beep("error")

    def on_release(self) -> None:
        try:
            audio = self.recorder.stop()
            duration_ms = len(audio) / CONFIG["sample_rate"] * 1000
            if duration_ms < CONFIG["min_recording_ms"]:
                LOG.info("Recording too short (%.0f ms), discarded", duration_ms)
                return
            triggers = ", ".join(self.commands.get().keys())
            phrase = self.transcriber.transcribe_raw(audio, prompt=triggers)
            LOG.info("Command phrase: %r", phrase)
            threading.Thread(target=self._handle, args=(phrase,), daemon=True).start()
        except Exception as e:
            LOG.error("Error occurred: %s", e)
            beep("error")


    def _handle(self, phrase: str) -> None:
        spoken = _normalise(phrase)
        for trigger, command in self.commands.get().items():
            if _normalise(trigger) == spoken:
                self._confirm_and_run(phrase, command)
                return
        self._learn(phrase)

    def _fifo_path(self) -> str:
        base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        return os.path.join(base, "voxrelay_commands.fifo")

    def _open_terminal(self, fifo: str) -> None:
        import subprocess
        here = os.path.dirname(os.path.abspath(__file__))
        runner = os.path.join(here, "runner.sh")
        terminals = [
            ["gnome-terminal", "--", "bash", runner, fifo, CONFIG["command_output_file"]],
            ["alacritty", "-e", "bash", runner, fifo, CONFIG["command_output_file"]],
            ["x-terminal-emulator", "-e", "bash", runner, fifo, CONFIG["command_output_file"]],
        ]
        for terminal in terminals:
            if shutil.which(terminal[0]):
                LOG.info("Opening terminal: %s", terminal[0])
                subprocess.Popen(terminal, cwd=here)
                return
        raise SystemExit("No terminal emulator found")

    def _send_to_terminal(self, command: str) -> None:
        import subprocess
        import time
        fifo = self._fifo_path()
        if not os.path.exists(fifo):
            os.mkfifo(fifo)

        for attempt in range(40):
            try:
                handle = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError:
                if attempt == 0:
                    self._open_terminal(fifo)
                time.sleep(0.25)
        else:
            raise SystemExit("Terminal did not start")

        with os.fdopen(handle, "w") as pipe:
            pipe.write(command + "\n")

        subprocess.run(
            ["xdotool", "search", "--name", "^Voice command runner$", "windowactivate"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _dialog(self, phrase: str, command: str = "", ask: bool = False) -> tuple[bool, str]:
        import subprocess
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dialog.py")
        # The system interpreter, not whichever python3 happens to be on PATH:
        # dialog.py needs the distro's GTK bindings, which a virtualenv lacks.
        args = [DIALOG_PYTHON, script, "--phrase", phrase]
        if ask:
            args.append("--ask")
        else:
            args += ["--command", command]
        result = subprocess.run(args, capture_output=True, text=True)
        return result.returncode == 0, result.stdout.strip()

    def _confirm_and_run(self, phrase: str, command: str) -> None:
        import subprocess
        approved, _ = self._dialog(phrase, command)
        import datetime
        run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        save_command_log(run_id, phrase, command, approved)
        if not approved:
            LOG.info("Command cancelled: %s", command)
            return
        LOG.info("Running command: #%s %s", run_id, command)
        with open(CONFIG["command_output_file"], "a", encoding="utf-8") as output:
            output.write(f"\n=== #{run_id} {phrase!r} -> {command} ===\n")
            output.flush()
            if CONFIG.get("run_in_terminal"):
                self._send_to_terminal(command)
            else:
                subprocess.Popen(command, shell=True, stdout=output, stderr=output)

    def _learn(self, phrase: str) -> None:
        LOG.info("No command found for: %r", phrase)
        beep("error")
        provided, command = self._dialog(phrase, ask=True)
        if not provided or not command:
            LOG.info("No command defined, nothing saved")
            return
        escaped_phrase = phrase.replace("\\", "\\\\").replace('"', '\\"')
        escaped_command = command.replace("\\", "\\\\").replace('"', '\\"')
        with open(CONFIG["commands_file"], "a", encoding="utf-8") as f:
            f.write(f'"{escaped_phrase}" = "{escaped_command}"\n')
        LOG.info("Learned new command: %r -> %s", phrase, command)


class Daemon:
    def __init__(self, recorder: Recorder, transcriber: Transcriber) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.injector = Injector()

    def on_press(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            LOG.error("Error occurred: %s", e)
            beep("error")

    def on_release(self) -> None:
        try:
            audio = self.recorder.stop()
            duration_ms = len(audio) / CONFIG["sample_rate"] * 1000
            if duration_ms < CONFIG["min_recording_ms"]:
                LOG.info("Recording too short (%.0f ms), discarded", duration_ms)
                return
            text = self.transcriber.transcribe(audio)
            LOG.info("Transcribed: %s", text)
            save_transcript(text)
            self.injector.inject(text)
        except Exception as e:
            LOG.error("Error occurred: %s", e)
            beep("error")

def main() -> None:
    recorder = Recorder()
    transcriber = Transcriber()
    daemon = Daemon(recorder, transcriber)
    commander = CommandRunner(recorder, transcriber)

    device = find_device(CONFIG["keyboard_name"])
    dictate_trigger = parse_trigger(CONFIG["key"])
    command_trigger = parse_trigger(CONFIG["command_key"]) if CONFIG["use_commands"] else None
    LOG.info("Listening for the configured keys, press and hold!")

    last_scan = None
    for event in device.read_loop():
        if event.type == ecodes.EV_MSC and event.code == ecodes.MSC_SCAN:
            last_scan = event.value
            continue

        if event.type != ecodes.EV_KEY:
            continue

        if matches(dictate_trigger, event, last_scan):
            handler = daemon
        elif command_trigger and matches(command_trigger, event, last_scan):
            handler = commander
        else:
            handler = None

        if event.value == 0:
            last_scan = None

        if handler is None:
            continue

        if event.value == 1:
            handler.on_press()
        elif event.value == 0:
            handler.on_release()



if __name__ == "__main__":
    main()