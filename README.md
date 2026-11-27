# Deektator

Deektator is an offline dictation app for **Windows** and **Fedora KDE Plasma on Wayland**. Hold a global shortcut while you speak, release it to transcribe, then paste the text into another app. Whisper runs locally on your CPU, with no account or API key required.

- **Hold to dictate** from another app, or start and stop recording from Deektator's window.
- **See when the mic is live** with a bottom-of-screen recording indicator that leaves keyboard focus where it is.
- **Choose your microphone** and see its input level while recording.
- **Paste a cleaned-up transcript**, or keep spoken fillers for a more literal result.

## Install on Windows

On 64-bit Windows 10 (version 1607 or later) or Windows 11, install [64-bit Python 3.11 or newer](https://www.python.org/downloads/windows/) with Tcl/Tk and add Python to PATH. Clone this repository or download and extract its ZIP. In PowerShell, run these commands from the project folder:

```powershell
.\setup-windows.cmd
.\run-deektator.cmd
```

Setup installs the microphone dependency and downloads the [whisper.cpp Windows CPU runtime](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3) and the English Whisper Small model. The runtime and models are stored in `%LOCALAPPDATA%\Deektator`. Once setup finishes, recording and transcription work offline.

Keep Deektator open or minimized. Hold **Alt + Windows**, wait for the **Recording** indicator at the bottom of the screen, then speak. Release either key and wait for the result to copy. Paste with **Ctrl + V**. You can also use **Start recording** and **Stop recording** in the window. If the Windows microphone is unavailable, check **Settings → Privacy & security → Microphone** and allow desktop apps to use it.

The Windows launcher accepts the same model and language options as the Linux launcher. For example, `.\run-deektator.cmd --language auto --download-model` downloads the multilingual model, and `.\run-deektator.cmd --language auto` starts Deektator with language detection.

## Install on Fedora KDE

Install the desktop and build dependencies, then clone Deektator.

```sh
sudo dnf install git cmake gcc-c++ python3-gobject gtk4 gtk-layer-shell \
  pulseaudio-utils wl-clipboard xdg-desktop-portal-kde
git clone https://github.com/Thebenmandude/Deektator.git
cd Deektator
```

Deektator uses [whisper.cpp](https://github.com/ggml-org/whisper.cpp) for transcription. If `whisper-cli` is already on your PATH, skip the build. Otherwise, build it in the sibling directory shown below, where Deektator can find it automatically.

```sh
mkdir -p ../tools
git clone --branch v1.9.6 --depth 1 https://github.com/ggml-org/whisper.cpp.git ../tools/whisper.cpp
cmake -S ../tools/whisper.cpp -B ../tools/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build ../tools/whisper.cpp/build --target whisper-cli --parallel 4
```

Download the default English model once, then launch Deektator.

```sh
./run-deektator --download-model
./run-deektator
```

The [Whisper Small model](https://huggingface.co/ggerganov/whisper.cpp/blob/main/ggml-small.en-q5_1.bin) is a 190 MB download. You can also download it from the app with **Download Small**. After setup, dictation works offline.

## Dictate on Fedora KDE

1. Approve **Hold to dictate** when KDE prompts you. The suggested shortcut is **Ctrl + Alt + Space**. Use **Shortcut Settings** in Deektator to assign a different combination.
2. With Deektator open or minimized, hold the shortcut. Wait for **Recording** to appear at the bottom of the screen, then speak.
3. Release the shortcut and wait for the transcript to copy. Paste it with **Ctrl + V**.

If the input meter stays flat while you speak, choose another **Microphone** in Deektator. Closing the app ends the shortcut session.

### Use Alt + Windows

To use just **Alt + Super** (the Windows key), choose a keyboard event device your user already has permission to read. Use a stable device path and press both keys on that keyboard.

```sh
ls -l /dev/input/by-id/*-event-kbd /dev/input/by-path/*-event-kbd
./run-deektator --keyboard /dev/input/by-id/YOUR-KEYBOARD-event-kbd
```

Add `--install-launcher` to that command to save the keyboard choice in the desktop launcher. The regular KDE shortcut works with the desktop's standard shortcut permissions.

## Language and model options

- **Other languages.** Download the multilingual model with `./run-deektator --language auto --download-model`, then launch with `./run-deektator --language auto`. You can also set a language explicitly, for example `--language af` for Afrikaans.
- **Custom models.** Set `--model` to a GGML model path or `--whisper` to a whisper.cpp executable path. On Linux, the app looks in `${XDG_DATA_HOME:-$HOME/.local/share}/deektator` and `../tools/whisper-models` for its default model. The app can also use an existing `ggml-base.bin` in the model directory.
- **More options.** Use `--keep-fillers` to retain spoken English fillers, `--manual` to start with the global shortcut off, or `--transcribe path/to/audio.wav` to transcribe a file from the terminal. Run `./run-deektator --help` for all options.

## Where your data goes

Inference and text cleanup run on your machine. Deektator uses temporary files during capture and transcription, keeps the latest text in memory for re-copying, and writes the result to the system clipboard. Your desktop clipboard manager may retain copied text.
