# Screensaver Audit — `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py`

**Audited at:** git HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29` (2026-10-23)  
**File size:** 873 lines, three classes: `Saver` (500 lines), `Player` (151 lines), `Monitor` (122 lines) + module-level helpers. Size is informational; the maintainer is satisfied with production files below 1,000 lines.  
**Refactored (refactor plan step 4):** `ui.py` is now the Kodi adapter, and the logic moved into focused modules under `lib/umsa_screensaver/` (see *Implemented Module Map*).

---

## Responsibility Map

| Class | Responsibility | Key Methods | Kodi APIs Used |
|-------|----------------|-------------|----------------|
| `Saver` (`xbmcgui.WindowXMLDialog`) | Artwork rendering orchestration (cross, slide, wall), video playlist management, bad-image filtering, artwork path resolution, temporary video extraction/cleanup, screensaver history recording, settings interpretation | `__init__`, `onInit`, `onAction`, `remember_art`, `record_display`, `open_software`, `read_settings`, `check_snapshot`, `get_machine_pic`, `resolve_art_path`, `_extract_exodos_video`, `cleanup_temp_videos`, `add_video_to_playlist`, `get_art_and_call_saver`, `create_wall`, `shutdown_video_mode` | `xbmcgui.WindowXMLDialog`, `xbmc.PlayList`, `xbmcgui.ListItem`, `xbmcgui.ControlImage`, `xbmcvfs`, `xbmcaddon`, `xbmc.sleep`, `xbmc.log`, `xbmc.executebuiltin`, window properties |
| `Player` (`xbmc.Player`) | Video playback callbacks (`onAVStarted`, `onPlayBackStarted`, `onPlayBackEnded`, `onPlayBackStopped`, `onPlayBackError`), label fading, playlist advancement, history recording for videos | `__init__`, `_av_instance_token`, `onAVStarted`, `onPlayBackStarted`, `onPlayBackEnded`, `onPlayBackStopped`, `onPlayBackError` | `xbmc.Player`, `getVideoInfoTag`, `getTotalTime`, `getPlayingFile`, `isPlayingVideo`, `playnext` |
| `Monitor` (`xbmc.Monitor`) | Screensaver lifecycle (activation/deactivation/DPMS), mode selection, `Saver`/`Player` instantiation, frontend communication (window properties, `NotifyAll` via `vgm_active`/`send_vgm_action`) | `__init__`, `startme`, `onScreensaverActivated`, `onScreensaverDeactivated`, `reallyDeactivateScreensaver`, `onDPMSActivated` | `xbmc.Monitor`, `xbmcgui.Window(10000)`, `xbmcaddon`, `xbmc.log`, `vgm_active`, `send_vgm_action` |

---

## Boundary Analysis

### 1. Kodi Window & Lifecycle Management
- **`Monitor.startme`** (`ui.py:798`): Entry point from Kodi screensaver activation. Selects a mode from settings, resets per-session state, sets `UMSA.Screensaver.Mode`, calls `Saver.doModal()`.
- **`Monitor.onScreensaverDeactivated`** (`ui.py:832`): Handles deactivation — special cases for `emu` mode, `videos` mode (stays active), VGM commands. Calls `reallyDeactivateScreensaver`.
- **`Monitor.reallyDeactivateScreensaver`** (`ui.py:855`): Sets `Saver.running = 'no'` (breaks the loop), calls `shutdown_video_mode()`, clears `UMSA.Screensaver.Mode`.
- **`Saver.doModal()`** → `get_art_and_call_saver()` (`ui.py:530`) → `rendering.RenderSession.run()`: the main loop runs until `self.running == 'no'`.

### 2. Context-Key Handoff to Frontend
- **`Saver.open_software`** (`ui.py:216`): Called on context-menu action (`ACTION_CONTEXT`) in cross/slide/wall/video modes. Reads software id from `Votes` (video) or `current_software_id` (images). Calls `self.parent.umsa.open_software(int(software_id))` → frontend `UMSA.open_software` → `_remember_and_select`.
- **`Saver.onAction`** (`ui.py:157`): Routes the action through `actions.handle_action`; video mode also stops the player.

### 3. Artwork Selection & Rendering (cross, slide, wall)
- **`rendering.RenderSession.run()`** (`rendering.py:425`): the render loop.
  - Determines `art_types` by mode: videos=`['videosnaps']`, cross=`['covers','flyers']`, slide=`['covers','flyers','cabinets','cpanel','marquees']`, wall=`['snap']` + `create_wall()`
  - Loop: `ggdb.get_random_art(art_types)` → `remember_art(art)` → `resolve_art_path` → `check_snapshot` (bad-image filter) → aspect calc → set control images → info labels → **mode-specific rendering** (cross: random pos `ControlImage`; slide: flip `IMAGE[0/1]` + `BACKG[0/1]`; wall: grid `mesh` + free slots) → **`record_display(art)`** (display-success boundary) → wait loop (`kodi.sleep(1000)`)
- **`Saver.create_wall`** (`ui.py:546`): Calculates the grid layout, creates the `ControlImage` mesh, shuffles positions, handles free-slot logic. It is idempotent (`_wall_created` guard) and called once per wall session.

### 4. Artwork Path Resolution & Image Validation
- **`Saver.resolve_art_path`** (`ui.py:279`): Wrapper around Core `resolve_artwork_path`. Handles alternate art types (flyer/cover/snap) for left-image display.
- **`Saver._extract_exodos_video`** (`ui.py:291`) → `temp_video.extract_exodos_video`: Extracts an eXoDOS videosnap from a ZIP to `special://temp/umsa_screensaver_videos/`. Validates `relative_path` and `archive_member` lexically.
- **`Saver.cleanup_temp_videos`** (`ui.py:306`) → `temp_video.cleanup_temp_dir`: removes the files of the screensaver temp directory; the directory itself is kept.
- **`Saver.check_snapshot`** (`ui.py:256`) → `image_validator`: MD5 against hardcoded bad-image lists (PIL and non-PIL variants); variance check for solid-color images (PIL only).

### 5. Video Playlist Management & Playback Callbacks
- **`Saver.add_video_to_playlist`** (`ui.py:341`): `get_random_art(['videosnaps'])` → `_extract_exodos_video` or `resolve_art_path` → `ListItem` with info (title, genre, trailer=machine_pic, director=left_pic, `Votes`=software_id) → **`attach_set_id(video_item, set_id)`** (Kodi 20+ unique ID) → `playlist.add()`. **If eXoDOS extraction is required (archive_member present) and fails, the candidate is rejected — no fallback to zip:// URL.**
- **`Player.onPlayBackStarted`** (`ui.py:672`): Increments `_playback_instance`, remembers the playing temp file, sets info labels/images from `VideoInfoTag`, runs the label-fade loop (`rendering.run_playback_labels`).
- **`Player.onAVStarted`** (`ui.py:652`): **History recording point for videos**. Deduplicates by `_av_instance_token` (instance + playlist pos + file). Reads `umsa_set_id` via `read_set_id(video_tag)` (Kodi 20+), `software_id` via `read_software_id` (`Votes`). Calls `ggdb.record_screensaver_display(set_id, software_id)`. Capability-guarded for Kodi < 20.
- **`Player.onPlayBackEnded`**, **`onPlayBackStopped`**, **`onPlayBackError`** (`ui.py:693`, `698`, `707`): Shared handler `_handle_playback_stopped` releases the active temp video and, if the screensaver is still in video mode and not shutting down, queues the next video. **Playback is only stopped during shutdown when the screensaver owns it (`_playback_owned` flag).**

### 6. Screensaver-History Recording
- **`Saver.record_display`** (`ui.py:204`): Called **once per completed cross/slide/wall render** (`rendering.py:525`), after the bad-image check, before the wait loop. Normalizes `set_id` via `normalize_set_id` (Core), calls `ggdb.record_screensaver_display(normalized_set_id, software_id)`. Failures logged, never break rendering.
- **`Player.onAVStarted`**: Records video history (see above).
- **Core side**: `HistoryRepository.record_screensaver_display` (delete-reinsert-prune in one savepoint, 100-set limit), `DBMod.record_screensaver_display` facade.

### 7. Temporary Video Extraction & Cleanup
- **`temp_video.extract_exodos_video`**: On-demand extraction for eXoDOS videosnaps stored in ZIP. Atomic write (`.part` → rename). **No cache** — every extraction creates a new unique file (`uuid4`), so an extracted file is never reused. Lexical validation rejects absolute paths and `..` traversal in `relative_path`; the constructed archive path is passed directly to `ZipFile`, allowing the OS to follow intentional symlinks inside the configured eXoDOS tree. `archive_member` is also validated lexically. **If extraction fails for a required eXoDOS video, the candidate is rejected (no fallback to zip:// URL).**
- **`temp_video.cleanup_temp_dir`**: Scans the temp directory directly (no cache) and removes every file in it, including `.part` files from failed extractions; subdirectories are never touched and the directory itself is kept. Called at the start of video mode (`rendering._start_video_mode`) and from `Saver.shutdown_video_mode`.
- **`Saver.release_playing_video`** (`ui.py:328`): deletes only the file of the video that just ended; a file still queued for playback is not touched. This is deliberately narrower than the directory cleanup.

### 8. Settings Interpretation
- **`Saver.read_settings`** (`ui.py:237`): Core settings (`own_artwork`, `progettosnaps`, `aspect_ratio_factor`) + screensaver-specific settings (`ssaver_time`, `ssaver_info`, `ssaver_videos/slide/wall/cross`, `ssaver_trows/trows_b/srows/srows_b/free/titles`).
- **`Monitor.startme`**: Reads `ssaver_*` settings to build the `settings['type']` candidates for mode selection.

### 9. VGM Control Notifications
- **`Saver.onAction`** → `actions.handle_action` (`actions.py`): When `vgm_active()` (Core adapter), handles volume up/down (88/89), next (play_nextitem/right), stop (13) via `send_vgm_action`. Sets `parent.vgmaction = True` to prevent screensaver deactivation.
- **`Monitor.onScreensaverDeactivated`** (`ui.py:832`): Checks `vgm_active()` and `self.vgmaction` to avoid stopping the screensaver during VGM commands.

---

## Smallest Cohesive Extractions for Testability

This is the plan that was implemented in step 4; the module locations below are the
current ones. The authoritative implemented layout is the *Implemented Module Map*.

| Extraction | Source (pre-split) | Module | Rationale |
|------------|--------------------|--------|-----------|
| **Artwork selection + validation** | `get_art_and_call_saver` | `screensaver/artwork_selector.py` | Pure logic: `get_random_art` → `resolve_art_path` → `check_snapshot` → aspect. No Kodi controls. |
| **Mode-specific rendering** | `get_art_and_call_saver` cross/slide/wall blocks | `screensaver/rendering.py` | Each mode has distinct control manipulation. |
| **Wall layout calculation** | `create_wall` | `screensaver/wall_layout.py` | Pure geometry — no Kodi calls until `addControl`. |
| **Video playlist management** | `add_video_to_playlist` + `Player` callbacks | `screensaver/video_playlist.py` | Encapsulates `xbmc.PlayList`, `ListItem` creation, `attach_set_id`. |
| **History recording** | `Saver.record_display` + `Player.onAVStarted` | `screensaver/history.py` | Both call `ggdb.record_screensaver_display`; unify deduplication logic. |
| **Temp video extraction** | `_extract_exodos_video` + `_cleanup_temp_videos` | `screensaver/temp_video.py` | Self-contained extraction + cleanup (no cache). |
| **Bad-image detection** | `check_snapshot` | `screensaver/image_validator.py` | Pure function (path → bool); PIL/non-PIL variants. |
| **Settings model** | `Saver.read_settings` + `Monitor.startme` | `screensaver/settings.py` | Dataclass for screensaver settings; single parse point. |

**Keep in `ui.py` (Kodi callbacks):**
- `Saver.__init__`, `onInit`, `onAction` (dispatch only)
- `Player.__init__`, `onPlayBackStarted`, `onAVStarted`, `onPlayBackEnded` (callbacks)
- `Monitor.__init__`, `startme`, `onScreensaverActivated`, `onScreensaverDeactivated`, `reallyDeactivateScreensaver`, `onDPMSActivated`
- Window property management (`UMSA.Screensaver.Mode`, `UMSA.Emulator.Running`)

---

## Core Database APIs & Cross-Addon Contracts (Explicit)

| Contract | Core API | Screensaver Usage | GUI Usage |
|----------|----------|-------------------|-----------|
| Random artwork | `DBMod.get_random_art(art_types)` | `Saver.get_art_and_call_saver` (per loop) | `gui.py` (media chooser) |
| Artwork path resolution | `resolve_artwork_path(art, set_info, source_roots)` | `Saver.resolve_art_path` (wrapper) | `gui.create_artworklist` |
| Screensaver history write | `DBMod.record_screensaver_display(set_id, software_id)` | `Saver.record_display`, `Player.onAVStarted` | `gui.py` (not used) |
| Screensaver history read | `DBMod.get_screensaver_history()` | Not used | `gamelist_strategies.last_saver` |
| Core settings | `get_core_settings()` (adapter) | `Saver.read_settings`, `Monitor.startme` | `gui.read_settings` |
| VGM active check | `vgm_active()` (adapter) | `Saver.onAction`, `Monitor.onScreensaverDeactivated` | `gui._handle_vgm_action` |
| VGM action send | `send_vgm_action(action)` (adapter) | `Saver.onAction` | `gui._handle_vgm_action` |
| Frontend software open | `UMSA.open_software(software_id)` (GUI) | `Saver.open_software` → `parent.umsa.open_software` | `gui.open_software` |

---

## Implemented Module Map (refactor plan step 4)

All modules live in `screensaver.umsa.mame.surfer/lib/umsa_screensaver/`. The Kodi
modules (`xbmc`, `xbmcgui`, `xbmcaddon`, `xbmcvfs`) are resolved **at call
time** in `ui.py` and handed down as arguments, so the tests can patch
`ui.xbmc` / `ui.xbmcgui` / `ui.xbmcvfs` / `ui.PIL` as before.

Line counts below are current at the audited HEAD and are informational only.

| Module | Lines | Responsibility | Kodi imports |
|--------|-------|----------------|--------------|
| `ui.py` | 873 | `Saver` / `Player` / `Monitor` — the Kodi window, playlist and callbacks; compat re-exports of the old module-level names | yes |
| `actions.py` | 111 | Dispatch of the Kodi actions of the screensaver window (context handoff, playlist advance, VGM volume/next/stop) | no (injected) |
| `artwork_selector.py` | 131 | Artwork types per mode, source roots, artwork path resolution, machine picture, aspect handling | no |
| `availability.py` | 191 | Artwork availability checks, mode selection fallbacks | no |
| `constants.py` | 49 | Action codes, control ids, window properties, mode names, artwork types per mode | no |
| `history.py` | 164 | `record_display`, `record_video_display`, playback token, `PlaybackHistoryGuard` | no (injected) |
| `image_validator.py` | 117 | Bad-image detection (PIL and non-PIL variants) | no |
| `rendering.py` | 550 | `RenderContext`, cross/slide/wall rendering, video label fading, `RenderSession` (the render loop) | no (injected) |
| `settings.py` | 130 | `WallSettings`, `ScreensaverSettings` (dataclasses) + legacy dict of `Saver.settings`, `choose_mode` | no |
| `temp_video.py` | 231 | eXoDOS ZIP videosnap extraction and cleanup (no cache) | no (injected `xbmcvfs`) |
| `video_playlist.py` | 113 | `ListItem` creation, `attach_set_id` / `read_set_id` / `read_software_id` (Kodi 20 unique id) | `xbmc` (logging only) |
| `wall_layout.py` | 122 | Wall geometry: rows, cell grid, positions, free slots | no |

### Public contracts kept in `ui.py`

`ui.py` re-exports the names the previous monolithic module exposed, so
callers and tests keep working unchanged: `Saver`, `Player`, `Monitor`,
`attach_set_id`, `read_set_id`, `read_software_id`, `SET_ID_UNIQUE_TYPE`,
`PIL`, `ACTION_CONTEXT`, `ACTION_MOVEMENT_RIGHT`, `ACTION_PLAY_NEXTITEM`,
`BACKG`, `CROSS_BACKGROUND`, `IMAGE`, `INFO_DETAIL`, `INFO_LABEL`,
`PIC_1TO1`, `PIC_3TO4`, `PIC_4TO3`, `PIC_MACHINE`, `MEDIA_FOLDER`.

---

## Preserved Quirks (kept on purpose — report, do not fix)

The refactor moves code, it does not change behaviour. These oddities are still
present and are listed so nobody changes them by accident:

- The render loop leaves through `while saver.running != 'no'`. Cleanup is guaranteed by the `finally` block in `RenderSession.run()` and by `Saver.get_art_and_call_saver`, not by an unreachable post-loop block.
- Video mode returns before the artwork loop; the loop therefore only renders image modes.
- `Saver.settings['type']` is a mutable list and `Saver.wall` a plain dict — the monitor removes and re-appends `'videos'` while audio is playing.
- `settings.ScreensaverSettings.from_addon` raises `ValueError` on an empty numeric add-on setting (`int('')`) — same as the original `read_settings`.

The following defects were fixed and are **not** preserved quirks:

- `Saver` no longer calls a non-existent `snapshot_crossover()` method in the "no videos found" branch.
- `create_wall()` is idempotent (`_wall_created` guard) and is called once per wall session.

## Post-A4 Fixes (2026-10-22)

The following correctness issues were fixed after the initial A4 screensaver split:

1. **Playback Ownership (Fix 1)**: Added `_playback_owned` flag to `Saver`. `stop_video_playback()` and `shutdown_video_mode()` now only stop Kodi playback when the screensaver owns it. `prepare_artwork_mode()` and `shutdown_video_mode()` clear the flag. `_start_video_mode()` sets it when starting playback.

2. **Playback Callbacks (Fix 2)**: Added `onPlayBackStopped()` and `onPlayBackError()` to `Player` class, both delegating to shared `_handle_playback_stopped()` handler. Consolidated cleanup logic. Idempotent handling of duplicate callback sequences (error → stopped, etc.).

3. **eXoDOS Extraction Failure (Fix 3)**: `add_video_to_playlist()` no longer falls back to zip:// URL when required eXoDOS extraction fails. The candidate is rejected and the bounded retry/fallback policy handles it. Partial `.part` files are cleaned up on failure.

4. **Playlist Lifecycle (Fix 4)**: `Saver.onInit()` calls `self.playlist.clear()` once during initialization (`ui.py:146`). This clears the shared Kodi **video** playlist (not the audio playlist); existing user video-playlist entries are therefore not preserved. `shutdown_video_mode()` does not clear the playlist again; it only stops playback when the screensaver owns it and cleans up temporary files.

5. **Rendering Cleanup Guarantee (Fix 5)**: `RenderSession.run()` wrapped in `try/finally` to ensure `_cleanup(ctx)` runs even on unexpected exceptions. Dynamic controls and render state are properly released.

### The one deliberate deviation

`image_validator.check_snapshot` opens the snapshot file with a `with` block.
A read error on an openable file is now reported as "invalid snapshot"
instead of raising out of the render loop (the PIL branch already behaved
that way). The file handle is closed in every case now.

---

## Behavior That Must Remain Compatible

- `Saver.running` values: `'no' | 'videos' | 'cross' | 'slide' | 'wall' | 'emu'` — frontend reads `UMSA.Screensaver.Mode` property
- `UMSA.Screensaver.Mode` window property on window 10000 — bidirectional (Monitor sets, GUI reads)
- `UMSA.Emulator.Running` property — shared with GUI
- `Votes` on video `ListItem` = software id (context handoff)
- `umsa_set_id` unique ID on video `ListItem` (Kodi 20+) = set id (history)
- `attach_set_id`/`read_set_id`/`read_software_id` signatures — used by `Saver` and `Player`
- `record_display` called once per completed image render (post-render, pre-wait)
- `onAVStarted` called once per video playback (stream available)
- Every eXoDOS extraction produces a new unique file (no cache key)
- `special://temp/umsa_screensaver_videos/` directory for extractions
- Settings keys: `ssaver_time`, `ssaver_info`, `ssaver_videos`, `ssaver_slide`, `ssaver_wall`, `ssaver_cross`, `ssaver_trows`, `ssaver_trows_b`, `ssaver_srows`, `ssaver_srows_b`, `ssaver_free`, `ssaver_titles`
- `vgm_active()` / `send_vgm_action()` protocol for VGM control

---

## Verification (step 4)

```bash
# focused screensaver tests (history, addon wiring, eXoDOS extraction)
.venv-debian-vm/bin/python -m pytest tests/test_screensaver_history_hooks.py \
    tests/test_screensaver_history_repository.py tests/test_screensaver_addon.py \
    tests/test_screensaver_exodos_extraction.py -q      # 161 passed (139 history/addon + 22 extraction)

# new unit tests of the extracted modules
.venv-debian-vm/bin/python -m pytest tests/test_screensaver_ui_modules.py -q  # 62 passed

# full suite
.venv-debian-vm/bin/python -m pytest tests/ -q          # 1081 passed, 5 skipped, 18 subtests passed

# lint of the add-on (was 2 findings in the old ui.py, now 0)
.venv-debian-vm/bin/python -m ruff check screensaver.umsa.mame.surfer/
```

Not covered by the automated tests (needs a running Kodi): the skin
animation of the cross/slide/wall modes, the label fading of the video mode,
the eXoDOS playback of an archived videosnap and the context handoff to the
frontend. See `release-plan.md` open manual areas.