# Kodi API Compatibility Audit

**Audited:** 2026-10-23 (at HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29`)  
**Scope:** All Kodi API usage across three add-ons  
**Declared Minimum:** `xbmc.python` 3.0.0 = **Kodi 20 (Nexus)**  
**Sources:** [Kodi Python API docs](https://xbmc.github.io/docs.kodi.tv/), [Kodi GitHub](https://github.com/xbmc/xbmc), Kodistubs 21.0.0

---

## Compatibility Summary

| Add-on | Kodi Modules Used | Minimum Version | Status |
|--------|-------------------|-----------------|--------|
| Frontend (`gui.py`, etc.) | `xbmc`, `xbmcgui`, `xbmcaddon`, `xbmcvfs` | 20 (3.0.0) | ✅ Compatible |
| Screensaver (`ui.py`, `runtime.py`) | `xbmc`, `xbmcgui`, `xbmcaddon`, `xbmcvfs` | 20 (3.0.0) | ✅ Compatible |
| Core Adapter (`umsa_core_kodi.py`) | `xbmc`, `xbmcgui`, `xbmcaddon`, `xbmcvfs` | 20 (3.0.0) | ✅ Compatible |

**No confirmed deprecated/removed APIs** found for Kodi 20+ in current codebase.

---

## API Usage Inventory

### `xbmc` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmc.log()` | All add-ons | All | ✅ Stable |
| `xbmc.sleep()` | All add-ons | All | ✅ Stable |
| `xbmc.executebuiltin()` | All add-ons | All | ✅ Stable |
| `xbmc.Monitor` | `VgmCommandMonitor` (`gui.py:248`), `Monitor` (`ui.py:752`) | All | ✅ Stable |
| `xbmc.Player` | `Player` (`ui.py:601`) | All | ✅ Stable |
| `xbmc.PlayList` | `Saver.__init__` (`ui.py:114`) | All | ✅ Stable |
| `xbmc.PLAYLIST_VIDEO` | `Saver.__init__` (`ui.py:114`) | All | ✅ Stable |
| `xbmc.LOGDEBUG/INFO/WARNING/ERROR` | All add-ons | All | ✅ Stable |
| `xbmcvfs.translatePath()` | All add-ons | All | ✅ Stable |

### `xbmcgui` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmcgui.WindowXMLDialog` | `UMSA` (`gui.py:272`), `Saver` (`ui.py:101`) | All | ✅ Stable |
| `xbmcgui.Window` | `Saver.set_mode_property` (`ui.py:254`), GUI window-property writes | All | ✅ Stable |
| `xbmcgui.Dialog` | `UMSA.__init__` (`gui.py:351`), `emulator_launcher.py` | All | ✅ Stable |
| `xbmcgui.DialogProgress` | `UMSA.__init__` (`gui.py:352`), `emulator_launcher.py` | All | ✅ Stable |
| `xbmcgui.DialogProgressBG` | `UMSA.__init__` (`gui.py:355`) | All | ✅ Stable |
| `xbmcgui.ListItem` | All add-ons | All | ✅ Stable |
| `xbmcgui.ListItem.setInfo()` | All add-ons | All | ✅ Stable |
| `xbmcgui.ListItem.setArt()` | All add-ons | All | ✅ Stable |
| `xbmcgui.ListItem.setProperty()` | All add-ons | All | ✅ Stable |
| `xbmcgui.ControlImage` | `Saver.create_wall` (`ui.py:580`) | All | ✅ Stable |
| `xbmcgui.Keyboard` | `gui.py:509` | All | ✅ Stable |
| `xbmcgui.NOTIFICATION_*` | All add-ons | All | ✅ Stable |

### `xbmcaddon` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmcaddon.Addon()` | All add-ons | All | ✅ Stable |
| `Addon.getAddonInfo()` | All add-ons | All | ✅ Stable |
| `Addon.getSetting()` | All add-ons | All | ✅ Stable |
| `Addon.openSettings()` | `gui.py:326, 746` | All | ✅ Stable |

### `xbmcvfs` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmcvfs.translatePath()` | All add-ons | All | ✅ Stable |
| `xbmcvfs.copy()` | `retroplayer_cache.py:103, 125, 138` | All | ✅ Stable |
| `xbmcvfs.exists()` | `temp_video.py:179, 210` | All | ✅ Stable |
| `xbmcvfs.delete()` | `temp_video.py:185` | All | ✅ Stable |
| `xbmcvfs.mkdirs()` | `temp_video.py:121` | All | ✅ Stable |

---

## Kodi 20+ Specific APIs (Capability-Guarded)

### `InfoTagVideo.setUniqueID()` / `getUniqueID()` — @python_v20

**Used in:** `screensaver.umsa.mame.surfer/lib/umsa_screensaver/video_playlist.py` (`attach_set_id`/`read_set_id`) and `history.py` (`getUniqueID` guard)

```python
# Capability-guarded usage pattern:
if video_tag is None or not hasattr(video_tag, 'setUniqueID'):
    xbmc.log("Kodi has no InfoTagVideo.setUniqueID (Kodi < 20)", xbmc.LOGDEBUG)
    return False
try:
    video_tag.setUniqueID(str(normalized), SET_ID_UNIQUE_TYPE)
except (TypeError, ValueError, RuntimeError) as error:
    xbmc.log(f"could not attach umsa_set_id: {error}", xbmc.LOGWARNING)
    return False
```

**Status:** ✅ Correctly capability-guarded. Degrades gracefully on Kodi < 20.

**Kodi Version:** Introduced in Kodi 20 (Nexus) — `@python_v20`

**Documentation:** [Kodi API](https://xbmc.github.io/docs.kodi.tv/python_api/xbmcgui.ListItem.html#xbmcgui.ListItem.setUniqueID)

---

### `ListItem.getGameInfoTag()` / `setInfo(type='game', ...)` — Kodi 20+

**Used in:** `plugin.program.umsa.mame.surfer/resources/lib/retroplayer_cache.py:160`

```python
game_item = xbmcgui.ListItem(playfile)
game_item.setInfo(type='game', infoLabels={ 'title': ctx.actset['gamename']})
game_tag = game_item.getGameInfoTag()
game_tag.setTitle(ctx.actset['name'])
game_tag.setPlatform(ctx.actset['machine_label'])
# ... more game metadata
```

**Status:** ✅ Used for Retroplayer integration. Kodi 20+ only feature.

**Kodi Version:** Game metadata API introduced in Kodi 20.

**Note:** This is only used in Retroplayer path (`exe == 'kodi'`), which requires Kodi 20+ anyway.

---

### `Player.onAVStarted()` — @python_v18

**Used in:** `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py:652`

```python
def onAVStarted(self):
    """Record the displayed video once a stream is actually available."""
```

**Status:** ✅ Available since Kodi 18 (Leia) — `@python_v18`. Well within minimum.

**Note:** Preferred over `onPlayBackStarted` for stream-available detection.

---

## Potential Risks Requiring Runtime Verification

### 1. `DialogProgress` vs `DialogProgressBG` Behavior

**Used in:** `gui.py:352` (`DialogProgress`), `gui.py:355` (`DialogProgressBG`), `emulator_launcher.py` (`DialogProgress`)

**Risk:** Modal dialog behavior may differ on Kodi 20+ with new skinning engine.

**Status:** ✅ MAINTAINER-VERIFIED — exercised by the confirmed GUI navigation and database-refactor smoke tests.

### 2. `Player` Callback Ordering

**Used in:** `Player` (`ui.py:601`) with `onAVStarted` (652), `onPlayBackStarted` (672), `onPlayBackEnded` (693)

**Risk:** Callback ordering guarantees may have changed in Kodi 20.

**Current assumption:** `onPlayBackStarted` → `onAVStarted` → playback → `onPlayBackEnded`

**Status:** ✅ MAINTAINER-VERIFIED — screensaver video playback/history confirmed; `onAVStarted` fires once per video.

### 3. `xbmcvfs` vs `os.path` for `special://` Paths

**Used in:** All add-ons for `special://temp/`, `special://profile/`, etc.

**Risk:** `os.path` functions may not work correctly on `special://` URIs in Kodi 20+.

**Current pattern:** `xbmcvfs.translatePath()` used consistently before `os.path` operations.

**Status:** ✅ CODE-VERIFIED — the only untranslated `special://` constant is `temp_video.py:19`, resolved via `temp_video.temp_dir` → `vfs.translatePath()`.

### 4. `ListItem.setInfo()` Video vs Game Metadata

**Used in:** `gui.py` (video), `retroplayer_cache.py` (game)

**Risk:** Video metadata keys (`Title`, `Genre`, `Trailer`, `Director`) vs Game metadata keys (`Title`, `Platform`, `Genre`, `Developer`, `Publisher`) — ensure correct type parameter.

**Current:** Video uses `type='video'` (default), Retroplayer uses `type='game'` explicitly.

**Status:** ⏳ OPEN — video path is maintainer-verified; Retroplayer game metadata is tracked in **Area 2**.

### 5. `Window(10000)` Shared Window Properties

**Used in:** `gui.py`, `ui.py` (`set_mode_property`), `runtime.py`

**Risk:** Shared window property synchronization between add-ons.

**Current pattern:** `UMSA.Emulator.Running`, `UMSA.Screensaver.Mode`, `UMSA.Screensaver.Manual`, `UMSA.Screensaver.Running`, `UMSA.VGM.*`

**Status:** ✅ MAINTAINER-VERIFIED — shared Kodi screensaver-inhibition lifecycle (C1–C3) confirmed.

---

## Kodi Version Support Matrix

| Feature | Min Kodi | Our Min (20) | Status |
|---------|----------|--------------|--------|
| `InfoTagVideo.setUniqueID` | 20 | 20 | ✅ Capability-guarded |
| `ListItem.getGameInfoTag` | 20 | 20 | ✅ Retroplayer-only |
| `Player.onAVStarted` | 18 | 20 | ✅ Available |
| `DialogProgressBG` | 18 | 20 | ✅ Available |
| `xbmcvfs.translatePath` | 17 | 20 | ✅ Available |
| `xbmcaddon.Addon.getSetting` | 17 | 20 | ✅ Available |
| `xbmc.Monitor` | 17 | 20 | ✅ Available |
| `xbmc.Player` callbacks | 17 | 20 | ✅ Available |

---

## Deprecated/Removed APIs — Not Found in Codebase

| Deprecated API | Removed In | Replacement | Found? |
|----------------|------------|-------------|--------|
| `xbmc.translatePath` | 19 (Matrix) | `xbmcvfs.translatePath` | ❌ Not used |
| `xbmc.makeLegalFilename` | 19 | `xbmcvfs.makeLegalFilename` | ❌ Not used |
| `xbmcgui.DialogProgress.create()` 3-arg | 19 | 2-arg + `update()` | ❌ Not used |
| `xbmc.Player.isPlaying()` | 19 | `isPlayingVideo()`/`isPlayingAudio()` | ❌ Not used (uses specific) |
| `ListItem.setInfo()` video-only keys | 20 | Game keys for `type='game'` | ✅ Used correctly |

---

## Kodi Runtime Verification Scenarios

### Scenario A: Emulator Idle Timeout
1. Set short Kodi idle-screensaver timeout (1 min)
2. Start external emulator (MAME)
3. Leave running beyond timeout
4. Exit emulator without pressing key in frontend
5. **Verify:** Screensaver inhibited during emulator; idle countdown resumes after exit

### Scenario B: Manual Screensaver Beyond Timeout
1. Start UMSA screensaver manually from GUI
2. Leave active longer than Kodi idle timeout
3. **Verify:** No competing idle screensaver activation
4. Press C-key → **Verify:** Correct game selected via handoff
5. Exit screensaver → **Verify:** Kodi idle timer resumes normally

### Scenario C: Automatic Screensaver
1. Let Kodi launch UMSA screensaver automatically (idle)
2. **Verify:** Screensaver stays active, key handling works
3. **Verify:** `UMSA.Screensaver.Manual` property NOT set for automatic invocation

### Scenario D: Retroplayer Game Launch
1. Select "Start with Kodi Retroplayer" from menu
2. **Verify:** Game launches, metadata displays, exits cleanly
3. **Verify:** `GameInfoTag` metadata populated correctly

### Scenario E: VGM Playback from Screensaver
1. Start random VGM from screensaver menu
2. Use volume/next/stop from screensaver
3. **Verify:** Commands reach frontend, playback controls work

---

## Recommendations

| Priority | Action |
|----------|--------|
| P0 | Close the 3 open manual areas (full emulator startup matrix, Retroplayer end-to-end, clean install + upgrade) |
| P0 | Verify `special://` paths all use `xbmcvfs.translatePath()` before `os.path` — **CODE-VERIFIED** (only `temp_video.py:19` template, resolved via translatePath) |
| P1 | Test `DialogProgress`/`DialogProgressBG` on Kodi 20+ skin (Estuary) — **MAINTAINER-VERIFIED** |
| P1 | Confirm `Player.onAVStarted` fires exactly once per video in screensaver — **MAINTAINER-VERIFIED** |
| P1 | Document minimum Kodi version as 20 (Nexus) in README (C9) |
| P2 | Test Retroplayer `GameInfoTag` metadata on Kodi 20+ — tracked in **Area 2** |

---

## Evidence

| Category | Source |
|----------|--------|
| ✅ Static source inspection | grep/read of all Python files |
| ✅ Capability guards verified | `video_playlist.py` lines 40-47/63-66, `history.py` 59-62 |
| 📋 Maintainer-confirmed manual smoke tests | GUI navigation, screensaver modes (Cross/Slide/Wall), video playback + random, VGM controls, playback history, DB refactor Phases 4.0–4.8, shared screensaver-inhibition lifecycle (C1–C3) — **recorded in `release-plan.md`** |
| ❓ Unverified | Scenario D (Retroplayer E2E) + 3 open manual areas (emulator matrix, Retroplayer E2E, clean install/upgrade) |

---

## Status

| API Area | Status |
|----------|--------|
| Core Kodi modules (`xbmc`, `xbmcgui`, `xbmcaddon`, `xbmcvfs`) | ✅ Compatible |
| Kodi 20+ specific APIs (`setUniqueID`, `getGameInfoTag`) | ✅ Capability-guarded / Retroplayer-only |
| Deprecated APIs | ✅ None found |
| Runtime verification | ✅ C1–C3 MAINTAINER-VERIFIED (screensaver-inhibition lifecycle); ❓ Scenario D (Area 2); 3 open manual areas explicitly listed in `release-plan.md` |