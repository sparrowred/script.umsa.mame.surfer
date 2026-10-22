# Screensaver Audit — `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py`

**Audited at:** git HEAD `9a98cfe`  
**File size:** ~1231 lines, three classes: `Saver` (~887 lines), `Player` (~170 lines), `Monitor` (~70 lines) + module-level helpers  
**Refactored (refactor plan step 4):** `ui.py` is now 522 lines, `Saver` 258, `Player` 86, `Monitor` 79 lines — the logic moved into 11 focused modules (see *Implemented Module Map*).

---

## Responsibility Map

| Class | Responsibility | Key Methods | Kodi APIs Used |
|-------|----------------|-------------|----------------|
| `Saver` (`xbmcgui.WindowXMLDialog`) | Artwork rendering loop (cross, slide, wall), video playlist management, bad-image filtering, artwork path resolution, temporary video extraction/cleanup, screensaver history recording, settings interpretation | `__init__`, `onInit`, `onAction`, `remember_art`, `record_display`, `open_software`, `read_settings`, `check_snapshot`, `get_machine_pic`, `resolve_art_path`, `_extract_exodos_video`, `_cleanup_temp_videos`, `add_video_to_playlist`, `get_art_and_call_saver`, `create_wall` | `xbmcgui.WindowXMLDialog`, `xbmc.PlayList`, `xbmcgui.ListItem`, `xbmcgui.ControlImage`, `xbmcvfs`, `xbmcaddon`, `xbmc.sleep`, `xbmc.log`, `xbmc.executebuiltin`, window properties |
| `Player` (`xbmc.Player`) | Video playback callbacks (`onAVStarted`, `onPlayBackStarted`, `onPlayBackEnded`), label fading, playlist advancement, history recording for videos | `__init__`, `_av_instance_token`, `onAVStarted`, `onPlayBackStarted`, `onPlayBackEnded` | `xbmc.Player`, `getVideoInfoTag`, `getTotalTime`, `getPlayingFile`, `isPlayingVideo`, `playnext` |
| `Monitor` (`xbmc.Monitor`) | Screensaver lifecycle (activation/deactivation/DPMS), mode selection, `Saver`/`Player` instantiation, frontend communication (window properties, `NotifyAll` via `vgm_active`/`send_vgm_action`) | `__init__`, `startme`, `onScreensaverActivated`, `onScreensaverDeactivated`, `reallyDeactivateScreensaver`, `onDPMSActivated` | `xbmc.Monitor`, `xbmcgui.Window(10000)`, `xbmcaddon`, `xbmc.log`, `vgm_active`, `send_vgm_action` |

---

## Boundary Analysis

### 1. Kodi Window & Lifecycle Management
- **`Monitor.startme`** (lines 1166–1189): Entry point from Kodi screensaver activation. Checks `UMSA.Emulator.Running` property, audio playback, selects mode from settings, sets `UMSA.Screensaver.Mode` property, calls `Saver.doModal()`.
- **`Monitor.onScreensaverDeactivated`** (lines 1191–1212): Handles deactivation — special cases for `emu` mode, `videos` mode (stays active), VGM commands. Calls `reallyDeactivateScreensaver`.
- **`Monitor.reallyDeactivateScreensaver`** (lines 1214–1227): Sets `Saver.running = 'no'` (breaks render loop), cleans up temp videos, clears `UMSA.Screensaver.Mode`.
- **`Saver.doModal()`** → `get_art_and_call_saver()` → render loop (lines 647–885): **Main loop** runs until `self.running == 'no'`.

### 2. Context-Key Handoff to Frontend
- **`Saver.open_software`** (lines 317–337): Called on context-menu action (`ACTION_CONTEXT`) in cross/slide/wall/video modes. Reads software id from `Votes` (video) or `current_software_id` (images). Calls `self.parent.umsa.open_software(int(software_id))` → frontend `UMSA.open_software` → `_remember_and_select`.
- **`Saver.onAction`** (lines 214–278): Routes context action; video mode also stops player.

### 3. Artwork Selection & Rendering (cross, slide, wall)
- **`get_art_and_call_saver`** (lines 647–885): **400-line method** — the render loop.
  - Determines `art_types` by mode: videos=`['videosnaps']`, cross=`['covers','flyers']`, slide=`['covers','flyers','cabinets','cpanel','marquees']`, wall=`['snap']` + `create_wall()`
  - Loop: `ggdb.get_random_art(art_types)` → `remember_art(art)` → `resolve_art_path` → `check_snapshot` (bad-image filter) → aspect calc → set control images → info labels → **mode-specific rendering** (cross: random pos `ControlImage`; slide: flip `IMAGE[0/1]` + `BACKG[0/1]`; wall: grid `mesh` + free slots) → **`record_display(art)`** (display-success boundary) → wait loop (`xbmc.sleep(1000)`)
- **`create_wall`** (lines 887–963): Calculates grid layout (rows/cols/spacing), creates `ControlImage` mesh, shuffles positions, handles free-slot logic.

### 4. Artwork Path Resolution & Image Validation
- **`resolve_art_path`** (lines 454–472): Wrapper around Core `resolve_artwork_path`. Handles alternate art types (flyer/cover/snap) for left-image display.
- **`_extract_exodos_video`** (lines 474–573): Extracts eXoDOS videosnap from ZIP to `special://temp/umsa_screensaver_videos/`. Caches by `set_id:archive_member`. Validates path containment, member safety.
- **`_cleanup_temp_videos`** (lines 575–596): Deletes tracked temp files on shutdown or mode change.
- **`check_snapshot`** (lines 372–411): MD5 against hardcoded bad-image lists (PIL and non-PIL variants); variance check for solid-color images (PIL only).

### 5. Video Playlist Management & Playback Callbacks
- **`add_video_to_playlist`** (lines 598–645): `get_random_art(['videosnaps'])` → `_extract_exodos_video` or `resolve_art_path` → `ListItem` with info (title, genre, trailer=machine_pic, director=left_pic, `Votes`=software_id) → **`attach_set_id(video_item, set_id)`** (Kodi 20+ unique ID) → `playlist.add()`. **If eXoDOS extraction is required (archive_member present) and fails, the candidate is rejected — no fallback to zip:// URL.**
- **`Player.onPlayBackStarted`** (lines 1077–1139): Increments `_playback_instance`, clears label, waits for `getTotalTime() > 0`, calculates fade timings, sets info labels/images from `VideoInfoTag`, runs fade loop.
- **`Player.onAVStarted`** (lines 1012–1075): **History recording point for videos**. Deduplicates by `_av_instance_token` (instance + playlist pos + file). Reads `umsa_set_id` via `read_set_id(video_tag)` (Kodi 20+), `software_id` via `read_software_id` (`Votes`). Calls `ggdb.record_screensaver_display(set_id, software_id)`. Capability-guarded for Kodi < 20.
- **`Player.onPlayBackEnded`**, **`onPlayBackStopped`**, **`onPlayBackError`**: Shared handler `_handle_playback_stopped` releases the active temp video and, if the screensaver is still in video mode and not shutting down, queues the next video. **Playback is only stopped during shutdown when the screensaver owns it (`_playback_owned` flag).**

### 6. Screensaver-History Recording
- **`Saver.record_display`** (lines 285–315): Called **once per completed cross/slide/wall render** (line 835), after bad-image check, before wait loop. Normalizes `set_id` via `normalize_set_id` (Core), calls `ggdb.record_screensaver_display(normalized_set_id, software_id)`. Failures logged, never break rendering.
- **`Player.onAVStarted`**: Records video history (see above).
- **Core side**: `HistoryRepository.record_screensaver_display` (delete-reinsert-prune in one savepoint, 100-set limit), `DBMod.record_screensaver_display` facade.

### 7. Temporary Video Extraction & Cleanup
- **`_extract_exodos_video`**: On-demand extraction for eXoDOS videosnaps stored in ZIP. Atomic write (`.part` → rename). **No cache** — every extraction creates a new unique file. Validates archive path inside eXoDOS root, member path safety. **If extraction fails for a required eXoDOS video, the candidate is rejected (no fallback to zip:// URL).**
- **`_cleanup_temp_videos`** (now `cleanup_temp_dir` in `temp_video.py`): Scans the temp directory directly and removes all files (including `.part` files from failed extractions). Called from `get_art_and_call_saver` exit and `reallyDeactivateScreensaver`. **Does not delete files still queued for playback** — only the file of the video that just ended is deleted via `release_playing_video()`. Full directory cleanup at startup/shutdown is disabled to avoid deleting queued files; only `.part` cleanup remains.

### 8. Settings Interpretation
- **`Saver.read_settings`** (lines 338–370): Core settings (`own_artwork`, `progettosnaps`, `aspect_ratio_factor`) + screensaver-specific settings (`ssaver_time`, `ssaver_info`, `ssaver_videos/slide/wall/cross`, `ssaver_trows/trows_b/srows/srows_b/free/titles`).
- **`Monitor.startme`**: Reads `ssaver_*` settings to build `settings['type']` list for mode selection.

### 9. VGM Control Notifications
- **`Saver.onAction`** (lines 255–270): When `vgm_active()` (Core adapter), handles volume up/down (88/89), next (play_nextitem/right), stop (13) via `send_vgm_action`. Sets `parent.vgmaction = True` to prevent screensaver deactivation.
- **`Monitor.onScreensaverDeactivated`** (lines 1205–1209): Checks `vgm_active()` and `self.vgmaction` to avoid stopping screensaver during VGM commands.

---

## Smallest Cohesive Extractions for Testability

| Extraction | Current Location | Proposed Module | Rationale |
|------------|------------------|-----------------|-----------|
| **Artwork selection + validation** | `get_art_and_call_saver` (lines 685–746) | `screensaver/artwork_selector.py` | Pure logic: `get_random_art` → `resolve_art_path` → `check_snapshot` → aspect. No Kodi controls. |
| **Mode-specific rendering** | `get_art_and_call_saver` cross/slide/wall blocks (lines 753–828) | `screensaver/rendering.py` | Each mode has distinct control manipulation. Could be strategy classes. |
| **Wall layout calculation** | `create_wall` (lines 887–963) | `screensaver/wall_layout.py` | Pure geometry — no Kodi calls until `addControl`. |
| **Video playlist management** | `add_video_to_playlist` (lines 598–645) + `Player.onPlayBackEnded` | `screensaver/video_playlist.py` | Encapsulates `xbmc.PlayList`, `ListItem` creation, `attach_set_id`. |
| **History recording** | `Saver.record_display` + `Player.onAVStarted` | `screensaver/history.py` | Both call `ggdb.record_screensaver_display`; unify deduplication logic. |
| **Temp video extraction** | `_extract_exodos_video` + `_cleanup_temp_videos` | `screensaver/temp_video.py` | Self-contained extraction + cache + cleanup. |
| **Bad-image detection** | `check_snapshot` (lines 372–411) | `screensaver/image_validator.py` | Pure function (path → bool); PIL/non-PIL variants. |
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

| Module | Lines | Responsibility | Kodi imports |
|--------|-------|----------------|--------------|
| `ui.py` | 522 | `Saver` / `Player` / `Monitor` — the Kodi window, playlist and callbacks; compat re-exports of the old module-level names | yes |
| `actions.py` | 106 | Dispatch of the Kodi actions of the screensaver window (context handoff, playlist advance, VGM volume/next/stop) | no (injected) |
| `artwork_selector.py` | 131 | Artwork types per mode, source roots, artwork path resolution, machine picture, aspect handling | no |
| `constants.py` | 49 | Action codes, control ids, window properties, mode names, artwork types per mode | no |
| `history.py` | 164 | `record_display`, `record_video_display`, playback token, `PlaybackHistoryGuard` | no (injected) |
| `image_validator.py` | 117 | Bad-image detection (PIL and non-PIL variants) | no |
| `rendering.py` | 384 | `RenderContext`, cross/slide/wall rendering, video label fading, `RenderSession` (the render loop) | no (injected) |
| `settings.py` | 130 | `WallSettings`, `ScreensaverSettings` (dataclasses) + legacy dict of `Saver.settings`, `choose_mode` | no |
| `temp_video.py` | 173 | eXoDOS ZIP videosnap extraction, cache, cleanup | no (injected `xbmcvfs`) |
| `video_playlist.py` | 113 | `ListItem` creation, `attach_set_id` / `read_set_id` / `read_software_id` (Kodi 20 unique id) | `xbmc` (logging only) |
| `wall_layout.py` | 122 | Wall geometry: rows, cell grid, positions, free slots | no |

### Class size targets

| Class | Before | After | Target |
|-------|--------|-------|--------|
| `Saver` | ~887 | 258 | < 300 ✅ |
| `Player` | ~170 | 86 | < 100 ✅ |
| `Monitor` | ~70 | 79 | < 80 ✅ |

### Public contracts kept in `ui.py`

`ui.py` re-exports the names the previous monolithic module exposed, so
callers and tests keep working unchanged: `Saver`, `Player`, `Monitor`,
`attach_set_id`, `read_set_id`, `read_software_id`, `SET_ID_UNIQUE_TYPE`,
`PIL`, `ACTION_CONTEXT`, `ACTION_MOVEMENT_RIGHT`, `ACTION_PLAY_NEXTITEM`,
`BACKG`, `CROSS_BACKGROUND`, `IMAGE`, `INFO_DETAIL`, `INFO_LABEL`,
`PIC_1TO1`, `PIC_3TO4`, `PIC_4TO3`, `PIC_MACHINE`, `MEDIA_FOLDER`.

---

## Preserved Quirks (kept on purpose — report, do not fix)

The refactor moves code, it does not change behaviour. These oddities of the
original file are still there and are listed so nobody "fixes" them by
accident:

- `Saver.add_video_to_playlist` calls `self.snapshot_crossover(['covers', 'flyers'])` in the "no videos found" branch — `Saver` has no such method (it would raise `AttributeError`). Kept verbatim.
- The render loop leaves through `while saver.running != 'no'`; the cleanup block after the loop in `get_art_and_call_saver` is therefore unreachable. The cleanup now runs in `Saver.get_art_and_call_saver` after `RenderSession.run()` returned `True`.
- The videos-mode wait branch in the render loop is unreachable (the video mode returns before the loop).
- The wall mode calls `create_wall()` twice (once for the artwork types, once for the layout) — kept.
- `Saver.settings['type']` is a mutable list, `Saver.wall` a plain dict — the monitor removes and re-appends `'videos'` while audio is playing.
- `settings.ScreensaverSettings.from_addon` raises `ValueError` on an empty numeric add-on setting (`int('')`) — same as the original `read_settings`.

## Post-A4 Fixes (2026-10-22)

The following correctness issues were fixed after the initial A4 screensaver split:

1. **Playback Ownership (Fix 1)**: Added `_playback_owned` flag to `Saver`. `stop_video_playback()` and `shutdown_video_mode()` now only stop Kodi playback when the screensaver owns it. `prepare_artwork_mode()` and `shutdown_video_mode()` clear the flag. `_start_video_mode()` sets it when starting playback.

2. **Playback Callbacks (Fix 2)**: Added `onPlayBackStopped()` and `onPlayBackError()` to `Player` class, both delegating to shared `_handle_playback_stopped()` handler. Consolidated cleanup logic. Idempotent handling of duplicate callback sequences (error → stopped, etc.).

3. **eXoDOS Extraction Failure (Fix 3)**: `add_video_to_playlist()` no longer falls back to zip:// URL when required eXoDOS extraction fails. The candidate is rejected and the bounded retry/fallback policy handles it. Partial `.part` files are cleaned up on failure.

4. **Playlist Clearing Removed (Fix 4)**: `onInit()` no longer calls `playlist.clear()`. `shutdown_video_mode()` no longer calls `clear_video_playlist()`. The user's Kodi video playlist is preserved when the screensaver runs in image modes. Temporary video files are still cleaned up after playback ends.

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
- Temp video cache key format: `f"{set_id}:{archive_member}"`
- `special://temp/umsa_screensaver_videos/` directory for extractions
- Settings keys: `ssaver_time`, `ssaver_info`, `ssaver_videos`, `ssaver_slide`, `ssaver_wall`, `ssaver_cross`, `ssaver_trows`, `ssaver_trows_b`, `ssaver_srows`, `ssaver_srows_b`, `ssaver_free`, `ssaver_titles`
- `vgm_active()` / `send_vgm_action()` protocol for VGM control

---

## Verification (step 4)

```bash
# focused screensaver tests (history, addon wiring, eXoDOS extraction)
.venv-debian-vm/bin/python -m pytest tests/test_screensaver_history_hooks.py \
    tests/test_screensaver_history_repository.py tests/test_screensaver_addon.py \
    tests/test_screensaver_exodos_extraction.py -q      # 139 passed

# new unit tests of the extracted modules
.venv-debian-vm/bin/python -m pytest tests/test_screensaver_ui_modules.py -q  # 62 passed

# full suite
.venv-debian-vm/bin/python -m pytest tests/ -q          # 1028 passed, 5 skipped, 18 subtests passed

# lint of the add-on (was 2 findings in the old ui.py, now 0)
.venv-debian-vm/bin/python -m ruff check screensaver.umsa.mame.surfer/
```

Not covered by the automated tests (needs a running Kodi): the skin
animation of the cross/slide/wall modes, the label fading of the video mode,
the eXoDOS playback of an archived videosnap and the context handoff to the
frontend.