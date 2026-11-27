# Deektator

Deektator is an offline dictation app for **Windows** and **Fedora KDE Plasma on Wayland**. Hold a global shortcut while you speak, then release it to transcribe. On Windows, Deektator pastes the result into the focused text box automatically. Whisper runs locally on your CPU, with no account or API key required.

- **Hold to dictate** from another app, or start and stop recording from Deektator's window.
- **See when the mic is live** with a bottom-of-screen recording indicator that leaves keyboard focus where it is.
- **Choose your microphone** and see its input level while recording.
- **Paste a cleaned-up transcript**, or keep spoken fillers for a more literal result.

## Install a release

Download the package for your platform from [GitHub Releases](https://github.com/Thebenmandude/Deektator/releases).

- **Windows x64**. Extract the ZIP and run `Deektator.exe`. Keep it in the extracted folder alongside `_internal`. The archive includes Python and Whisper. Install Microsoft's [x64 Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/) if Whisper reports a missing runtime DLL. Use `deektator-cli.exe --version` or `deektator-cli.exe --help` from a terminal.
- **Fedora 44 KDE x86_64 with AVX2**. Install the downloaded RPM with `sudo dnf install ./deektator-*.rpm`, then open **Deektator** from the application menu or run `deektator`.

Choose **Download Small** on first launch to download the speech model. After that, dictation works offline. Each release includes SHA-256 checksums for its packages.

## Run from source on Windows

On 64-bit Windows 10 (version 1607 or later) or Windows 11, install [64-bit Python 3.11 or newer](https://www.python.org/downloads/windows/) with Tcl/Tk and add Python to PATH. Clone this repository or download and extract its ZIP. In PowerShell, run these commands from the project folder:

```powershell
.\setup-windows.cmd
.\run-deektator.cmd
```

Setup installs the microphone dependency and downloads the [whisper.cpp Windows CPU runtime](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3) and the English Whisper Small model. The runtime and models are stored in `%LOCALAPPDATA%\Deektator`. Once setup finishes, recording and transcription work offline.

Keep Deektator open or minimized. Click into a text box, hold **Alt + Windows**, wait for the **Recording** indicator at the bottom of the screen, then speak. You can switch to another text box while speaking. When you release the shortcut, the bottom indicator changes to an animated **Transcribing…** message and stays visible until Deektator has copied the new result and sent **Ctrl + V**. Keep the intended text box selected until the indicator disappears and the transcript appears. **Start recording** and **Stop recording** use the same paste behavior; switch to the destination text box after clicking Stop. If the receiving app does not accept the paste, the transcript stays on the clipboard so you can use **Ctrl + V** yourself. If the Windows microphone is unavailable, check **Settings → Privacy & security → Microphone** and allow desktop apps to use it.

The insertion follows keyboard focus, so place the text caret in the destination field; hovering the mouse over a field is not enough. Pasting replaces highlighted text, just like **Ctrl + V**.

To change the dictation shortcut, click **Settings** beside the Deektator title. Choose your modifier keys and an optional additional key, then click **Save**. The change takes effect immediately and is remembered for future launches. You can also turn the global shortcut off or choose **Restore default** to return to **Alt + Windows**. Shortcuts are paused while Settings is open; release all shortcut keys before using the new combination. Preferences are stored in `%LOCALAPPDATA%\Deektator\windows-settings.json`.

The Windows launcher accepts the same model and language options as the Linux launcher. For example, `.\run-deektator.cmd --language auto --download-model` downloads the multilingual model, and `.\run-deektator.cmd --language auto` starts Deektator with language detection.

## Run from source on Fedora KDE

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

Transcription automatically uses more CPU threads on larger processors (up to 16, leaving some capacity for other apps), while keeping the same model. Windows also uses a faster CPU attention path when the installed runtime supports it. To tune CPU usage yourself, launch with `--threads 8`, for example `.\run-deektator.cmd --threads 8`. Lower values can help when other CPU-intensive apps are running; more threads are not always faster.

## Where your data goes

Inference and text cleanup run on your machine. Deektator uses temporary files during capture and transcription, keeps the latest text in memory for re-copying, and writes the result to the system clipboard. Your desktop clipboard manager may retain copied text.

## Release workflow

GitHub Actions builds and tests both packages on pull requests to `main`. After each update to `main`, the workflow publishes both tested packages as one release with GitHub-generated notes. Tags use `v0.1.<workflow run number>` so reruns retain the same version. Pull request builds use run numbers too, so published versions can skip numbers.
