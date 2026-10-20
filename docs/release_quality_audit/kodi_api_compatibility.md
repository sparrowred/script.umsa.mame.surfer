# Kodi API Compatibility Audit

**Audited:** 2026-10-21  
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
| `xbmc.Monitor` | `gui.py:213`, `ui.py:1155` | All | ✅ Stable |
| `xbmc.Player` | `gui.py:312`, `ui.py:964` | All | ✅ Stable |
| `xbmc.PlayList` | `ui.py:147` | All | ✅ Stable |
| `xbmc.PLAYLIST_VIDEO` | `ui.py:147` | All | ✅ Stable |
| `xbmc.LOGDEBUG/INFO/WARNING/ERROR` | All add-ons | All | ✅ Stable |
| `xbmcvfs.translatePath()` | All add-ons | All | ✅ Stable |

### `xbmcgui` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmcgui.WindowXMLDialog` | `gui.py:236` | All | ✅ Stable |
| `xbmcgui.Window` | `gui.py:543`, `ui.py:55` | All | ✅ Stable |
| `xbmcgui.Dialog` | `gui.py:315`, `emulator_launcher.py` | All | ✅ Stable |
| `xbmcgui.DialogProgress` | `gui.py:316`, `emulator_launcher.py:59` | All | ✅ Stable |
| `xbmcgui.DialogProgressBG` | `gui.py:319` | All | ✅ Stable |
| `xbmcgui.ListItem` | All add-ons | All | ✅ Stable |
| `xbmcgui.ListItem.setInfo()` | All add-ons | All | ✅ Stable |
| `xbmcgui.ListItem.setArt()` | All add-ons | All | ✅ Stable |
| `xbmcgui.ListItem.setProperty()` | All add-ons | All | ✅ Stable |
| `xbmcgui.ControlImage` | `ui.py:58, 758, 813` | All | ✅ Stable |
| `xbmcgui.Keyboard` | `gui.py:611, 1439` | All | ✅ Stable |
| `xbmcgui.NOTIFICATION_*` | All add-ons | All | ✅ Stable |

### `xbmcaddon` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmcaddon.Addon()` | All add-ons | All | ✅ Stable |
| `Addon.getAddonInfo()` | All add-ons | All | ✅ Stable |
| `Addon.getSetting()` | All add-ons | All | ✅ Stable |
| `Addon.openSettings()` | `gui.py:290, 848` | All | ✅ Stable |

### `xbmcvfs` Module

| API | Used In | Kodi Version | Status |
|-----|---------|--------------|--------|
| `xbmcvfs.translatePath()` | All add-ons | All | ✅ Stable |
| `xbmcvfs.copy()` | `retroplayer_cache.py:103, 125, 137` | All | ✅ Stable |
| `xbmcvfs.exists()` | `ui.py:523, 589` | All | ✅ Stable |
| `xbmcvfs.delete()` | `ui.py:590` | All | ✅ Stable |
| `xbmcvfs.mkdirs()` | `ui.py:533` | All | ✅ Stable |

---

## Kodi 20+ Specific APIs (Capability-Guarded)

### `InfoTagVideo.setUniqueID()` / `getUniqueID()` — @python_v20

**Used in:** `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` (lines 59-90, 93-115)

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

**Used in:** `plugin.program.umsa.mame.surfer/resources/lib/retroplayer_cache.py` (lines 158-170)

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

**Used in:** `screensaver.umsa.mame.surfer/lib/umsa_screensaver/ui.py` (line 1012)

```python
def onAVStarted(self):
    """Record the displayed video once a stream is actually available."""
```

**Status:** ✅ Available since Kodi 18 (Leia) — `@python_v18`. Well within minimum.

**Note:** Preferred over `onPlayBackStarted` for stream-available detection.

---

## Potential Risks Requiring Runtime Verification

### 1. `DialogProgress` vs `DialogProgressBG` Behavior

**Used in:** `gui.py:316` (`DialogProgress`), `gui.py:319` (`DialogProgressBG`), `emulator_launcher.py:59` (`DialogProgress`)

**Risk:** Modal dialog behavior may differ on Kodi 20+ with new skinning engine.

**Verification needed:** Scenario A — emulator launch dialog displays correctly, updates work, dismisses cleanly.

### 2. `Player` Callback Ordering

**Used in:** `ui.py:964` (`Player` class with `onAVStarted`, `onPlayBackStarted`, `onPlayBackEnded`)

**Risk:** Callback ordering guarantees may have changed in Kodi 20.

**Current assumption:** `onPlayBackStarted` → `onAVStarted` → playback → `onPlayBackEnded`

**Verification needed:** Scenario B — screensaver video playback triggers `onAVStarted` exactly once per video.

### 3. `xbmcvfs` vs `os.path` for `special://` Paths

**Used in:** All add-ons for `special://temp/`, `special://profile/`, etc.

**Risk:** `os.path` functions may not work correctly on `special://` URIs in Kodi 20+.

**Current pattern:** `xbmcvfs.translatePath()` used consistently before `os.path` operations.

**Verification needed:** Confirm all `special://` paths go through `translatePath()` first.

### 4. `ListItem.setInfo()` Video vs Game Metadata

**Used in:** `gui.py` (video), `retroplayer_cache.py` (game)

**Risk:** Video metadata keys (`Title`, `Genre`, `Trailer`, `Director`) vs Game metadata keys (`Title`, `Platform`, `Genre`, `Developer`, `Publisher`) — ensure correct type parameter.

**Current:** Video uses `type='video'` (default), Retroplayer uses `type='game'` explicitly.

**Verification needed:** Scenario A/B — metadata displays correctly in both paths.

### 5. `Window(10000)` Shared Window Properties

**Used in:** `gui.py:543, 550, 556`, `ui.py:55, 185, 1226`, `runtime.py:78, 88`

**Risk:** Shared window property synchronization between add-ons.

**Current pattern:** `UMSA.Emulator.Running`, `UMSA.Screensaver.Mode`, `UMSA.Screensaver.Manual`, `UMSA.VGM.*`

**Verification needed:** Scenario A/C — property reads/writes atomic across add-ons.

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
| P0 | Execute Scenarios A–C in Kodi 20+ before release |
| P0 | Verify `special://` paths all use `xbmcvfs.translatePath()` before `os.path` |
| P1 | Test `DialogProgress`/`DialogProgressBG` on Kodi 20+ skin (Estuary) |
| P1 | Confirm `Player.onAVStarted` fires exactly once per video in screensaver |
| P2 | Test Retroplayer `GameInfoTag` metadata on Kodi 20+ |
| P2 | Document minimum Kodi version as 20 (Nexus) in README |

---

## Evidence

| Category | Source |
|----------|--------|
| ✅ Static source inspection | grep/read of all Python files |
| ✅ Capability guards verified | `ui.py` lines 79-84, 102-103 |
| 📋 Maintainer-reported | Database refactor, screensaver/emulator lifecycle, recent Kodi smoke tests |
| ❓ Unverified | Scenarios A–E runtime behavior |

---

## Status

| API Area | Status |
|----------|--------|
| Core Kodi modules (`xbmc`, `xbmcgui`, `xbmcaddon`, `xbmcvfs`) | ✅ Compatible |
| Kodi 20+ specific APIs (`setUniqueID`, `getGameInfoTag`) | ✅ Capability-guarded / Retroplayer-only |
| Deprecated APIs | ✅ None found |
| Runtime verification | ❓ Scenarios A–E needed |