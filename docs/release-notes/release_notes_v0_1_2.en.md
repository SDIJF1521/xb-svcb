<div align="center">

[简体中文](release_notes_v0_1_2.md) | **English** | [日本語](release_notes_v0_1_2.ja.md)

<img src="../../assets/icon/xb-svcb.png" width="96" alt="XB-SVCB" />

# 🎉 XB-SVCB v0.1.2 Release Notes

#### Workflow Store: share, preview, download, and PyMSS sync

[![release](https://img.shields.io/badge/release-v0.1.2-ff6b9d?style=flat)](../../README.en.md)
[![date](https://img.shields.io/badge/date-2026--11--21-informational?style=flat)](#)

</div>

> **In one sentence:** This release adds a workflow store built on ModelScope for uploading, paginated search, read-only preview and download of cover workflows. Downloads automatically sync the PyMSS models listed in the manifest, and the workflow opens directly in the AI Cover studio. It also redesigns workflow previews and all confirmation dialogs, and fixes downloaded workflows losing valid connections.

## ✨ Highlights

| Area | What changed |
| :--- | :--- |
| 🛍️ **Workflow Store** | New: upload saved workflows · search and pagination · read-only preview · download public workflows from yourself or others |
| 🔗 **PyMSS sync** | Downloading a workflow installs missing PyMSS models declared in its manifest; installed models are skipped |
| 🎛️ **Studio integration** | Downloads are saved to Saved Workflows; “Open AI Cover studio” switches to workflow mode and loads that workflow automatically |
| 🖼️ **Preview** | Layered DAG layout, truncated/wrapped card text, direction arrows, theme-aware styling, redesigned thumbnails |
| 🪟 **Dialogs** | Unified centering, background, border, buttons and long-text layout for MessageBox and Dialog |
| 🧱 **Architecture** | Manifest rules moved to the domain layer, ModelScope networking/upload to an adapter, with the application layer orchestrating |

## 📌 Scope of this release

v0.1.2 starts at commit `5afbb7eb522b2bdc244aea9c6daeb8105acb62a5` ("自定义工作流节点优先级添加", 2026-11-20) and includes that commit. Use this range to generate the commit list or audit the diff:

```text
5afbb7eb522b2bdc244aea9c6daeb8105acb62a5^..HEAD
```

## 🔧 Post-release fixes & polish (v0.1.2 · 2026-11-21 → 11-27)

Follow-up fixes after the release, focused on MIDI pitch editing and the custom-workflow canvas:

### 🎼 MIDI sub-editor

- **Deleting a note now mutes it**: in Pitch Correction mode, a deleted note's sung range is silenced in preview and after applying instead of leaving the original vocal untouched. The editor records the extracted note spans as the reference vocal region (sidecar `voice_spans`); whatever the current notes do not cover is muted. Deleting every note mutes the whole vocal (breaths and unvoiced consonants are kept).
- **Empty note lists persist**: after deleting all notes and saving, reopening no longer re-analyzes them back. Save / Apply stay available with zero notes, and `midi/apply` with an explicit empty array mutes the whole extracted vocal range.
- **Track preview renders MIDI**: track-scope Preview now re-renders each clip into one track-length preview (mutes included), aligned with the piano-roll playhead, so deleted notes are audible there too.
- **Pitch curves are split per stroke**: hand-drawn curves are segmented per stroke — continuous inside a stroke, not interpolated across strokes, and un-drawn ranges fall back to the source F0. A later stroke no longer draws an imaginary straight line over a range you did not edit.
- **New “Continue” toggle (off by default)**: a new stroke near an existing segment endpoint joins it and stays continuous; when both ends are near, it joins both, which is useful for filling a gap.
- **Partial redraw and erase**: a stroke cuts the old segments by its time range (with interpolated boundary points) and keeps both sides without forcing them to connect; erasing splits segments instead of bridging the hole; undo/redo restores segments. Hand-drawn samples are thinned as needed, so long notes are no longer truncated by the 256-point-per-note cap.

### 🧩 Custom workflow canvas

- **No more misplaced edges after expanding Advanced**: port positions now follow node size, so expanding/collapsing sections or switching a model (which changes the parameter area height) keeps edges attached to the bottom output ports.
- **Performance**: a single `ResizeObserver` watches every node and coalesces updates per animation frame; only resized nodes are re-measured; unchanged offsets do not trigger edge recomputation; wheel zoom no longer forces layout on every tick (port offsets are zoom-invariant) and re-measures once after the gesture.

## 🛍️ Workflow Store

- Open it from **Library → Workflow Store**; it shares the ModelScope access token with the model store.
- Upload a saved workflow with its node graph, description, tags, version, author and required PyMSS models.
- Search by keyword, filter by all workflows / my uploads, choose page size, and paginate. The pager stays pinned to the bottom of the page.
- Pagination counts workflow repositories only; voice models in your namespace are no longer included in “My uploaded workflows”.
- Only workflows that pass manifest magic validation are shown, keeping unrelated models out of the results.

## 🔗 PyMSS and Studio integration

- Workflow details list related PyMSS models and their local installation status.
- Downloads are saved to Saved Workflows first, then missing PyMSS models are installed. Failed items are reported in the Transfers panel and can be retried later.
- “Open AI Cover studio” carries the local workflow ID, switches to Custom Workflow mode and loads the workflow.
- A downloaded workflow is auto-arranged on first open to reduce crossed connections from the author's original canvas; Undo can restore the previous positions.

## 🖼️ Preview and dialogs

- Workflow preview now uses a topological layered layout instead of the author's raw canvas coordinates.
- Node titles are single-line ellipsized and parameter summaries wrap to at most two lines, so model names no longer overflow.
- Previews use direction arrows, theme-aware backgrounds/cards and adapt their height to the graph.
- All `ElMessageBox` dialogs now use flex centering, explicit width and themed buttons, fixing confirmation boxes that appeared in the top-left, transparent, or with misplaced buttons in some environments.
- `el-dialog` also uses a unified glass background, rounded corners, shadow and blurred overlay.

## 🔧 Important fixes

- Fixed downloaded workflows losing valid connections when opened before the PyMSS catalog was ready: ports with unknown stems were treated as stale and their edges were pruned.
- Re-measure port positions after the model catalog loads so edges no longer land on node corners.
- Missing or duplicate edge IDs now receive unique fallback values, preventing Vue key reuse from rendering connections incorrectly.
- Fixed the “My uploaded workflows” count including voice models.
- Fixed MessageBox layout issues in some themes/environments.

## 🧱 Architecture and quality

- Added `domain/workflow_manifest.py` for manifest validation, graph sanitizing, PyMSS dependency parsing and source metadata.
- Added `infrastructure/workflow_hub_client.py` for ModelScope search, manifest fetching and subprocess uploads.
- `application/workflow_hub_service.py` now only orchestrates use cases; PyMSS installation state is accessed through the `PymssGateway` port.
- Added domain/application/port contract tests and updated the DDD architecture document.

## 📌 Upgrade notes

- The version is now `0.1.2`; existing data directories, models, works and editor projects remain compatible.
- If an older build opened a downloaded workflow and saved it after its edges were pruned, re-download that workflow after upgrading to restore all connections.
- Uploading workflows requires the model upload component in `.venv-hub`; search, preview and download do not.
