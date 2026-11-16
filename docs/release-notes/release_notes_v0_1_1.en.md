<div align="center">

> **In one sentence:** the audio editor grew a complete MIDI sub-editor (fix intonation, write arrangements, draw pitch curves), the AI Cover workspace grew a visual custom workflow, and PyMSS is fully integrated — alongside upgrades to real-time conversion and the RVC inference stack, and a fix for installer failures on Chinese install paths.

## ✨ Highlights

| Area                              | What changed                                                                                                    |
| :-------------------------------- | :-------------------------------------------------------------------------------------------------------------- |
| 🎼 **MIDI sub-editor**      | New: note-level pitch redraw · 128 GM instruments · real drum samples · full timeline · pitch curves        |
| 🧩 **Custom workflow**      | New: visual node canvas · save and reuse · per-node status and progress · one-click export                   |
| 🎚️ **Audio editor**       | Track rename · role pitch shift now applied · export-path layout fixed · messages no longer cover the nav    |
| 🎧 **Real-time conversion** | Automatic virtual-cable endpoint pairing · lower monitoring latency · clearer device errors                   |
| 🚀 **Inference engines**    | Full PyMSS integration · RVC back on the original implementation · high-band rebuild in high-pitch protection |
| 📦 **Installer**            | Fixed installation on Chinese paths · pip cache moved off the system drive · reproducible CI                  |

## 📌 Release scope

The release range starts at and includes commit `12f6db36754f5e86c9997449752367804e2da76a` ("fix export-path UI breaking the editor layout") — **28 commits** from 2026-11-03 to 2026-11-13.

Use the following range when generating commit lists or auditing changes:

```text
12f6db36754f5e86c9997449752367804e2da76a^..HEAD
```

---

## 🔧 Post-release fixes & polish (v0.1.1 · 2026-11-14 → 11-16)

Additional fixes after the initial release, focused on pitch curves, the installer and overall performance:

### 🎨 Pitch curve rework

- **One continuous curve**: the curve is no longer bound to a single MIDI note — it is a continuous, track-wide line you can draw anywhere (including rests); undrawn regions fall back to the original pitch (F0), drawn regions follow your stroke.
- **Pen-style drawing**: freehand drawing with Catmull-Rom smoothing, high-frequency sampling (`pointerrawupdate` + `getCoalescedEvents`) and a start threshold; a click only selects, dragging draws — no more "one click messes up the line".
- **Cross-note editing**: one stroke can span multiple notes; right-drag / eraser erases, Ctrl snaps to semitones.
- **Undo / redo**: each stroke is its own undo step (Ctrl+Z); fixed Ctrl+Z being swallowed by checkbox focus.
- **Adaptive range + F0 octave correction**: the vertical range covers notes, the original F0 and your curve (no more being pinned to the top edge); F0 is octave-corrected to avoid ±12-semitone spikes.

### 🎚️ Audio editor

- Fixed the **play button becoming disabled** after frequent operations: preview / playback now have timeouts and a watchdog that recovers automatically.
- Project list gained **search** and **batch management** (multi-select / select current view / batch delete with confirmation and result summary).

### 📦 Installer

- Fixed `%TEMP%` temp-directory creation (error 5): non-admin installs now grant the Users group write access via `icacls`.
- Fixed the **frozen / stuck progress bar**: now a time-based progressive fill, no longer relying on `GetTickCount`.
- Added a `-RequireAdmin` build switch; the default stays non-admin (lowest + elevation dialog), and desktop icons choose user / common desktop by install mode.

### 🚀 PyMSS

- **Stem / port alignment** for multi-stem models: only real stems are returned, with normalized port names (`vocals` / `instrumental` / `other`).
- Stems are now read from the model yaml.
- Added a **download progress bar** that maps per-file bytes onto the overall progress.

### ⚡ Performance

- The global i18n DOM localizer now **batches** mutations (one tree walk per macrotask) and short-circuits the Chinese UI.
- Pitch-curve drawing: display decimation, cached pitch range, shallow-copy / reference-shared undo snapshots — long songs no longer stutter while drawing.

### 🌏 Localization

- Added English / Japanese strings for the new buttons and hints (batch management, smooth curve, pitch-curve tips, etc.).

## 🎼 MIDI sub-editor

- **Note-level pitch redraw**: notes are extracted from clip audio and pitch is redrawn back onto the audio note by note. Redraw runs in the isolated vocal runtime through Praat PSOLA, preserving formants and timbre, touching only the notes you drag — unmodified notes keep their original intonation.
- **Two modes**: *Pitch correction* adjusts an existing take; *MIDI Composer* writes one from scratch. Composer ships 128 GM instruments and a GM drum kit whose pieces use real samples extracted from `gm.dls`, snapped to kick, snare, hi-hat and cymbal groups.
- **Full timeline**: BPM, time signature, duration, grid and quantize strength. Duration can be typed in (up to 24 hours) and extends automatically as notes are written further out. A blank-project entry point lets empty tracks be composed directly and rendered to audio.
- **Speed-ups**: context menus (add / delete / copy / paste / quantize / transpose / velocity / legato / split / select-all / undo-redo), shortcuts (`D` draw, `V` select, `E` erase, `Ctrl+C/V/D/A/Q/Z`, `Alt+↑↓`, `Shift+↑↓`, `Del`, `Space` to preview), plus render-to-this-track, render-as-separate-instrument-tracks, export `.mid`, and import `.mid` into a part.
- **Pitch curves (portamento / vibrato)**: drag across a note to draw a curve on top of the measured fundamental, with one-click *Vibrato*, *Portamento*, *Use original pitch* and *Clear curve*. The curve starts from the original F0, can be edited incrementally, and every step supports undo / redo.
- **Local shaping**: notes can be split at a chosen point and the pitch curve breaks at the split, so a partial segment can be shaped on its own.
- **Absolute target pitch**: the curve states the target directly instead of applying the singer's own deviation a second time — this fixes spurious glides and exaggerated vibrato that appeared after rendering the default curve.
- **Cleaner reference**: the original F0 is cleaned first (a local median filter removes whole-frame octave jumps and spikes) and drawn as a reference curve, so you can compare what was sung against what the notes say.

## 🎚️ Audio editor

- Added **track rename**.
- Fixed the **export-path control stretching the timeline header** and squeezing the toolbar; narrow screens now wrap and long paths are ellipsized.
- **Role pitch shift is now actually rendered**: a role with a non-zero shift gets its own bus and a duration-preserving transposition, and the value is part of the mix cache signature so stale renders are no longer reused.
- **Top-of-screen messages moved below the navigation bar**, so they no longer cover the header or the search box.
- General interaction polish across the editor, the VST3 plugin host, role effect scopes and partial re-inference.

## 🧩 AI Cover workspace: custom workflow

Wire the whole cover pipeline on a canvas:

| Category         | Nodes                                                                                                                                    |
| :--------------- | :--------------------------------------------------------------------------------------------------------------------------------------- |
| Input / output   | Input audio · Final output                                                                                                              |
| Vocal processing | Vocal separation (UVR / PyMSS) · Dereverb cleanup · Vocal repair · Voice conversion · Vocal harmony stacking · AI vocal enhancement |
| Synthesis        | Mixdown · Multi-track merge · Sequential concat                                                                                        |
| Audio shaping    | Audio effects · Trim · Fade · Pitch shift · Time stretch · Loudness normalization                                                   |

- Workflows can be **saved and reused**, and nodes report their own status and progress while running.
- Nodes support **copy / cut / paste** and shortcuts; choosing a separation method switches to the matching separation / dereverb node automatically.
- The finished-audio row gained a **Download result** button that exports `WAV / FLAC / MP3 / M4A` directly, without detouring through the standard player.

## 🎧 Real-time conversion

- **Automatic virtual-cable endpoint pairing**: a capture endpoint such as `CABLE Output` is mapped to the playable `CABLE Input`, avoiding the common "no sound because the output was picked wrong" case.
- **Lower monitoring latency**: smaller audio blocks and a shorter queue; dropped stale blocks no longer crossfade against non-adjacent audio, so the stream does not replay old audio.
- Improved system-audio device detection and error messages, with regression tests for real-time conversion.

## 🚀 PyMSS and inference engines

- **PyMSS fully integrated**: model catalog and download, vocal separation, dereverb / harmony removal, and purpose-based model filtering in the audio editor, real-time conversion and custom workflow nodes.
- **RVC moved from `rvc-python` back to the original RVC implementation**: bundled v1 / v2 configs, HuBERT / RMVPE JIT and the inference pipeline, with matching installer and packaging changes.
- **Optimized the pre-conversion vocal repair stage**, shortening the separation-to-conversion path.
- **High-pitch protection rebuilds the high band**: an F0-conditioned vocoder (Snake-HiFiGAN when weights are available, NSF-HiFiGAN as fallback) rebuilds the very high band, reducing harmonic smearing after the pitch-down / pitch-up round trip.

## 📦 Installer and build

- **Fixed installer failures on Chinese (and other non-ASCII) install paths**: batch scripts pin the UTF-8 code page and child processes emit paths as explicit UTF-8 bytes, so `for /f` no longer mis-decodes them and rejects a valid Python or uv location.
- **Moved the pip bootstrap cache into the install directory's `.tmp`** so it no longer fills the system drive, and ensured the uv cache directory exists before use.
- Added and adjusted GitHub Actions configuration and pinned `setup-uv` for reproducible CI.

## 🏗️ Architecture, typing and tests

- Continued the **DDD consolidation**: rules moved into the domain layer, explicit port/adapter contracts, architecture tests locking the dependency direction, and earlier compatibility debt cleaned up.
- Added **type annotations** across `conversion_service`, the service layer and infrastructure to catch interface drift before release.
- Fixed several **flaky tests**: CI temp directory 8.3 short-name comparison, requirements checks when engine sources are absent, and download-cache directory timestamp collisions.

## 🌏 Interface and languages

- Filled in missing English and Japanese text across the audio editor, cover workspace, workflow canvas, plugin dialogs, model management, works and player pages, including buttons, placeholders, hints and error messages.
- Everything new in `0.1.1` — **MIDI editor, pitch curves, workflow nodes and the export dialog** — ships in Simplified Chinese / English / Japanese.
- Added README status badges and refreshed the architecture, runtime and getting-started documents.

## ⚠️ Compatibility and upgrade notes

> **Runtime**: still built on Python 3.12 with the hardware-specific runtime layout — CPU, ROCm 10, DirectML, CUDA 12.6 and CUDA 12.8.

- Overwriting upgrades do not remove models, works, editor projects, themes, API settings or plugin data; backing up the user data directory before upgrading is still recommended.
- Note-level pitch redraw needs the **vocal runtime** (Praat / Parselmouth) and F0 analysis needs the **SVC runtime**; a missing environment is reported explicitly instead of failing silently.
- The generated pitch curve **starts as the original fundamental**, so applying it unchanged means "no edit". To correct intonation, drag the curve toward the note line or use *Clear curve* to quantize that note to its MIDI pitch.

---

<div align="center">
