# ULTRON — V1

**A local, offline-first voice assistant for Windows with a menacing machine voice, full system control, and a brain that runs entirely on your own hardware.**

```
   ___  __  __ ____    _____ _   _  ____ ___ _   _ _____
  / _ \|  \/  |  _ \  |_   _| | | |/ ___|_ _| \ | | ____|
 | | | | |\/| | |_) |   | | | |_| | |  _ | ||  \| |  _|
 | |_| | |  | |  _ <    | | |  _  | |_| || || |\  | |___
  \___/|_|  |_|_| \_\   |_| |_| |_|\____|___|_| \_|_____|
```

> ⚠️ **Fan project.** "Ultron" and all related characters belong to Marvel / Disney.
> This project is unofficial and unaffiliated. The voice is an **original synthesized
> character voice** (Windows SAPI + a custom robotic DSP chain) — it is *not* a clone of
> any actor's voice, including James Spader's.

---

## What it does

| Capability | Details |
|---|---|
| 🎙️ Wake word | Say **"Ultron"** (or press `Ctrl+Alt+U`) — offline recognition via **Vosk** (~40 MB model, bundled with the installer) |
| 🧠 Local AI brain | **Ollama** serving `llama3.2:3b` (~3.7 GB RAM) — free, offline, no API keys. Graceful fallback parser keeps basic commands working without it |
| 🤖 ULTRON voice | SAPI voice → custom DSP chain: pitch-down, detuned robotic chorus, ring modulation, saturation, dark EQ, convolution reverb |
| 🪟 System control | Open/close apps, window management (focus/minimize/maximize/snap/close), volume, media keys, brightness, screenshots, clipboard, typed input & key presses, file search/open, web search/URLs, timers & reminders, system reports |
| ⏻ Power control | Lock / sleep / restart / shutdown — **always requires a spoken confirmation** (say "cancel shutdown" to abort) |
| 🖥️ HUD | Custom dark interface with an animated reactive core, live transcript, conversation console, tray icon, first-run wizard |
| 🔒 Privacy | Everything runs locally. No cloud, no telemetry, no accounts |

### Memory budget (all models free & local)

| Component | RAM |
|---|---|
| `llama3.2:3b` via Ollama (default brain) | ~3.7 GB |
| Vosk small speech recognition | ~0.3 GB |
| TTS + FX + app | ~0.4 GB |
| **Total** | **~4.4 GB — comfortably inside an 8 GB budget** |

Lighter brains if you want more headroom: `gemma2:2b` (~2.6 GB), `qwen2.5:3b` (~3.5 GB).

---

## Getting the installer (`setup.exe`)

**Direct download:** grab `UltronSetup-<version>-x64.exe` from the repo's
[**Releases** page](https://github.com/LebronJamer/Ultron/releases/latest) — every
`v*` tag automatically builds and publishes a release with the signed-off installer.

Alternatively, the installer is also produced by GitHub Actions on every push:

1. Open the repo's **Actions** tab → **Build Ultron Windows Installer** → pick the latest run.
2. Download the **`Ultron-Windows-Setup`** artifact → unzip → `UltronSetup-<version>-x64.exe`.

### System requirements

- Windows 10 (19041+) / 11, 64-bit
- Microphone (for voice input; typed input always works)
- 8 GB RAM recommended (runs fine on 4 GB with `gemma2:2b` or basic mode)
- ~2 GB free disk for the optional Ollama brain model

### Install & first run

1. Run `UltronSetup-<version>-x64.exe` (accepts the UAC prompt — installs to Program Files).
2. Launch Ultron. The **first-run wizard** opens:
   - **Voice check** — hear the Ultron voice.
   - **Brain setup** — one-click `winget` install of [Ollama](https://ollama.com), then pull `llama3.2:3b` (~2 GB download, progress shown in the wizard).
   - No Ollama? Ultron still works in **basic command mode** (regex intents).
3. Say **"Ultron"**, press **Ctrl+Alt+U**, or type a command.

---

## Using Ultron

Say `Ultron, <command>` in one breath, or just `Ultron` then wait for the chime.

| Try saying… | What happens |
|---|---|
| "Ultron, open notepad / chrome / spotify" | Launches apps |
| "close spotify" / "close this window" | Closes apps/windows |
| "what's my CPU doing" | CPU / RAM / disk / battery report |
| "set volume to 40" / "mute" / "next song" | Audio & media control |
| "take a screenshot" | Saves to `Pictures\Ultron`, tells you the path |
| "set brightness to 60" | Display brightness |
| "minimize / maximize / snap window left" | Window management |
| "find the file report.docx" | Searches your user folders |
| "google the weather in Rome" | Opens a web search |
| "set a timer for 5 minutes" | Spoken alert when it elapses |
| "remind me to stretch in 30 minutes" | Spoken reminder |
| "type hello world" / "press enter" | Types into the focused window |
| "what's on my clipboard" / "clipboard buy more coffee" | Clipboard I/O |
| "list windows" / "focus chrome" | Window survey & focus |
| "shut down the computer" | Asks for confirmation, then schedules it (20 s grace, cancellable) |
| "tell me a joke" | …he has opinions |

The console in the HUD shows the full conversation log; the status ring shows
**STANDBY / LISTENING / PROCESSING / SPEAKING**.

### Settings

`SETTINGS` in the HUD (or tray menu): wake word, hotkey, SAPI voice selection,
pitch/rate, FX intensity & pitch drop, Ollama URL & model, speak-replies,
sound cues, start-with-Windows, start-minimized, speech-model download.

---

## Voice engine notes

The Ultron voice is produced by a DSP chain in `app/fx.py`:

1. **Resample pitch-down** (+ slow, deliberate delivery)
2. **Detuned robotic chorus** (11 ms / 17 ms short delays, ±0.4% pitch offsets)
3. **Ring modulation** at 57 Hz (metallic sidebands)
4. **Tanh saturation** (a "powered" edge)
5. **FFT equalisation** — low-shelf boost + gentle low-pass (dark timbre)
6. **Convolution reverb** with a synthetic dark impulse response
7. **Edge gating & normalisation**

All parameters are exposed in Settings (`fx_intensity`, `fx_pitch_semitones`,
`sapi_pitch`, `sapi_rate`). Push FX intensity to 1.5 for maximum menace.

---

## Building from source

### Local (Windows)

```powershell
cd UltronV1
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# → installer\Output\UltronSetup-1.0.0-x64.exe
```

The script creates a venv, installs dependencies, downloads the Vosk model,
runs PyInstaller (onedir, per `scripts/ultron.spec`) and compiles the installer
with Inno Setup 6 (install from <https://jrsoftware.org/isdl.php> if missing).

### Dev run (no packaging)

```powershell
cd UltronV1
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\download_models.ps1
.venv\Scripts\python launch.py            # or:  python -m app.main
```

### CI (this repository)

`.github/workflows/build-installer.yml` (repo root — GitHub requires workflows
to live there) builds on `windows-latest` and uploads:

- `Ultron-Windows-Setup` — the **setup.exe** (Inno Setup, LZMA2, admin scope, Start-menu/desktop icons, optional autostart task)
- `Ultron-Windows-Portable` — the raw PyInstaller folder
- On `v*` tags: a GitHub **Release** with the setup.exe attached

---

## Project layout

```
UltronV1/
├── launch.py                 # thin launcher (PyInstaller entry)
├── requirements.txt
├── app/
│   ├── main.py               # wiring, single-instance, lifecycle
│   ├── service.py            # wake-word state machine, command dispatch
│   ├── config.py             # %APPDATA%\Ultron\config.json
│   ├── bus.py                # thread-safe event bus
│   ├── stt.py                # Vosk continuous recognition
│   ├── tts.py / tts_sapi.py  # speech worker + SAPI synthesis
│   ├── fx.py                 # the ULTRON voice DSP chain
│   ├── audio_io.py           # playback + synthesized UI cues
│   ├── llm.py / persona.py / fallback.py   # Ollama brain + offline fallback
│   ├── modelfetch.py         # first-run speech-model download
│   ├── setup_ollama.py       # guided Ollama install / model pull
│   ├── gui.py                # HUD (animated core, console, input)
│   ├── settings_ui.py        # settings dialog
│   ├── wizard.py             # first-run wizard
│   ├── tray.py               # system tray
│   ├── paths.py / log.py
│   ├── commands/             # executor + system/apps/windows control
│   └── assets/icons/         # icon.ico / banner.bmp (installer art)
├── installer/
│   ├── ultron.iss            # Inno Setup script
│   └── LICENSE.txt
└── scripts/
    ├── ultron.spec           # PyInstaller spec
    ├── version_info.txt      # exe version resource
    ├── download_models.ps1
    ├── build.ps1
    ├── selfcheck.py          # static wiring audit (runs in CI)
    ├── gui_smoke.py          # instantiates the real GUI in CI before packaging
    └── test_functional.py    # functional test suite (runs in CI)
```

## Safety & security

- Destructive power actions (shutdown / restart / sleep) **always require an
  explicit spoken/typed confirmation** and have a 20-second cancellation window.
- Ultron only executes the whitelisted actions in `app/commands/executor.py`;
  the LLM chooses among them but cannot run arbitrary shell commands.
- Everything is local — no network calls except downloads you explicitly
  trigger (speech model, Ollama) and web pages you explicitly request.

## Troubleshooting

- **"brain: offline"** — Ollama isn't running. `ollama serve` in a terminal, or
  re-run the wizard (SETUP button in the HUD).
- **No voice** — check Windows sound output; test via Settings → TEST VOICE.
- **Mic not detected** — Settings → RESTART MIC; check Windows privacy settings
  (`Settings → Privacy → Microphone` allows desktop apps).
- **SmartScreen warning** — the installer is unsigned (no code-signing
  certificate). Choose *More info → Run anyway*, or build from source.
- **Logs** — `%APPDATA%\Ultron\logs\ultron.log`.

## License

MIT for code — see `installer/LICENSE.txt` (includes the fan-project and voice
disclaimers). Third-party runtime licenses (Python, Vosk, Ollama models,
pystray LGPL, etc.) belong to their authors.
