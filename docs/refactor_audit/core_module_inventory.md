# Core Module Inventory — `script.module.umsa.core/lib/umsa_core/`

**Audited at:** git HEAD `4186b5f5dd3479b19df84215d1fa21a4cbb38f29` (2026-10-23)  
**Total modules:** 38 Python files (excluding `__init__.py`, `__pycache__`)

---

## Module Catalog

| Module | Main Responsibility | Public API | Key Imports | DB/FS/Net/Subprocess/Parse/Orchestrate | Kodi Imports | Callers (Core / GUI / Screensaver) | Boundary Coherence |
|--------|---------------------|------------|-------------|----------------------------------------|--------------|-----------------------------------|-------------------|
| `artwork.py` | Artwork type constants, categorization, aspect-ratio check, path resolution helpers | `IMAGE_ART_TYPES`, `LEFT_IMAGELIST`, `RIGHT_IMAGELIST`, `build_artwork_path`, `categorize_art_type`, `check_image_aspect`, `find_local_snapshots`, `get_machine_artwork_path`, `resolve_artwork_path`, `root_key_for_path` | `os`, `pathlib` | FS (path building), Parse (aspect from DB) | No | Core: `artwork_repository`, `artwork_scanner`, `exodos_artwork`; GUI: `gui.py`; Screensaver: `ui.py` | ✅ Cohesive — pure path/type helpers |
| `artwork_repository.py` | Authoritative `artwork.db` schema + CRUD (`ArtworkRepository`) | `create_artwork_tables`, `ArtworkRepository.get_art_types`, `get_artwork_for_set`, `get_artwork_for_sets`, `get_scan_unit_status`, `list_scan_units`, `update_scan_unit_status` | `sqlite3`, `umsa_core.sqlite` | DB (read/write `artwork.db`), Schema | No | Core: `artwork_scanner`, `exodos_scanner`, `exodos_artwork`, `database.py` (facade) | ✅ Cohesive — single DB domain |
| `artwork_scanner.py` | Scan workflow for artwork folders (Progetto Snaps, own) | `ArtworkScanner.scan`, `ArtworkScanner.__init__` | `os`, `zipfile`, `umsa_core.artwork`, `artwork_repository`, `scan_coordinator` | FS (walk dirs, read zips), DB (write `artwork.db`), ScanLock | No | GUI: `gui.py` via `DBMod.scan_artwork` facade | ✅ Cohesive — self-contained scan |
| `database.py` | `DBMod` — compatibility facade, connection lifecycle, cross-db sync, mixed queries, orchestration | `DBMod.__init__`, `open_db`, `close*`, `scan_*` facades, `get_*` facades (repos), `define_filter`/`execute_statement`/`get_by_*` (filter), `get_cmd_line_options`, `create_cmdline`, `get_all_for_software`, `get_last_played`, `get_random_id`, `get_random_art`, `get_artwork_by_software_id`, `get_random_vgm_batch`, `load_lastgames`/`save_lastgames`, `load_filter_selections`/`save_filter_selections`/`list_filter_names`/`get_import_marker`/`run_legacy_import`/`retry_legacy_import`/`discover_legacy_paths`, `record_screensaver_display`/`get_screensaver_history`; module helpers `split_gamename`, `parse_recommended_games`, `build_filter_lists`, `run_scan_with_progress` | All Core modules | DB (persistent `umsa.db`/`status.db`, `ATTACH`), Orchestrate | **No** (enforced by boundary tests) | GUI: `gui.py` (`self.ggdb`), `umsa_gui/scan_orchestrator.py`, `umsa_gui/filter_ui.py`, `umsa_gui/media_list.py`, `umsa_gui/gamelist_actions.py`, `umsa_gui/software_selector.py`; Screensaver: `runtime.py` (`self.umsa.ggdb`); Core: internal | ⚠️ Large (~1857 lines, down from 69k) — Phase 4.9.1 inventory complete (2026-10-24, HEAD `9b62f4b`); no extraction implemented. See [`database_refactor/phase_4_9_1_inventory.md`](../database_refactor/phase_4_9_1_inventory.md) |
| `data_paths.py` | Core profile/data directory resolution (`CoreDataPaths`) | `CoreDataPaths` (dataclass with `data_dir`, `umsa_db`, `status_db`, `dat_db`, `artwork_db`, `filters_dir`, `lastgames_file`, `lastsaver_file`, `filter_file`) | `pathlib`, `xbmcvfs` (via adapter only) | FS (paths) | **No** (`xbmcvfs` only in `umsa_core_kodi.py`) | Core: all modules needing paths; GUI/Screensaver: via `get_core_data_paths()` adapter | ✅ Cohesive — pure path logic |
| `dat_parser.py` | Parse DAT files (clrmamepro, Logiqx) | `DatParser.parse`, `DatParser.__init__` | `xml.etree.ElementTree`, `gzip` | Parse (XML), FS (read) | No | Core: `dat_scanner.py` | ✅ Cohesive — single parser |
| `dat_repository.py` | Authoritative `dat.db` schema + reads (`DatRepository`) | `create_dat_tables`, `DatRepository.get_dat_for_set`, `get_dat_for_sets`, `get_dat_set` | `sqlite3`, `umsa_core.sqlite` | DB (read `dat.db`), Schema | No | Core: `dat_scanner`, `database.py` (facade), `game_repository` (for `get_machines`) | ✅ Cohesive — single DB domain |
| `dat_scanner.py` | Scan workflow for DAT files | `DatScanner.scan`, `DatScanner.__init__` | `os`, `gzip`, `dat_parser`, `dat_repository`, `scan_coordinator` | FS (walk, read), DB (write `dat.db`), ScanLock | No | GUI: `gui.py` via `DBMod.scan_dats` facade | ✅ Cohesive — self-contained scan |
| `emulation.py` | Emulator facade: process lifecycle, VGM socket mgmt, `emurun` state, delegates prep/extraction to extracted modules | `Emulation.__init__`, `prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `find_roms`, `find_nonmame_roms`, `extract_rom`, `extract_chd`, `play_vgm`, `play_random_vgm`, `play_vgm_thread`, `play_random_vgm_thread`, `send_vgmaction`, `start_managed_process`, `wait_for_completion`, `run`, `terminate`, `kill`, `after_run`, `ProcessRunner`, `ProcessState`, `ProcessStatus`, `ProcessLaunchError` | `subprocess`, `socket`, `threading`, `zipfile`, `os`, `shutil`, `umsa_core.process`, `vgm_header`, `support`, `launch_preparer`, `rom_finder`, `rom_extractor`, `chd_extractor`, `vgm_player`, `vgm_socket` | Subprocess (MAME, chdman, vgmplay), Net (Lua socket), FS (ROM/CHD discovery via delegates), Parse (VGM header via delegates) | **No** | GUI: `gui.py` (`self.emulation`), `emulator_launcher.py`, `retroplayer_cache.py` | ✅ Facade (592 lines, down from 1200) — delegates to `LaunchPreparer`, `RomFinder`, `RomExtractor`, `ChdExtractor`, `VgmPlayer`, `VgmSocketServer` |
| `emulator_repository.py` | `status.db` emulator config (`EmulatorRepository`) | `create_emulator_tables`, `EmulatorRepository.get_emulators`, `get_emulator`, `save_emulator`, `connect_emulator`, `delete_emulator_connection`, `delete_emulator` | `sqlite3`, `umsa_core.sqlite` | DB (read/write `status.db`), Schema | No | Core: `database.py` (facade), `gui.py` (via `ggdb`) | ✅ Cohesive — single DB domain |
| `exodos_artwork.py` | eXoDOS artwork extraction from ZIP archives | `extract_exodos_artwork`, `ExodosArtworkExtractor` | `zipfile`, `os`, `pathlib`, `artwork_repository` | FS (read zips, extract), DB (write `artwork.db`) | No | Core: `exodos_scanner.py` | ✅ Cohesive — single extraction concern |
| `exodos_parser.py` | Parse eXoDOS metadata (XML/INI) | `ExodosParser.parse`, `ExodosParser.__init__` | `xml.etree.ElementTree`, `configparser` | Parse (XML/INI) | No | Core: `exodos_scanner.py` | ✅ Cohesive — single parser |
| `exodos_scanner.py` | Scan workflow for eXoDOS | `ExodosScanner.scan`, `ExodosScanner.__init__` | `os`, `exodos_parser`, `exodos_artwork`, `dat_repository`, `artwork_repository`, `scan_coordinator` | FS (walk), DB (write `dat.db`/`artwork.db`), ScanLock | No | GUI: `gui.py` via `DBMod.scan_exodos_to_db` facade | ✅ Cohesive — self-contained scan |
| `chd_extractor.py` | CHD extraction, cancellation and cleanup | `ChdExtractor.extract_chd`, `CHDExtractionCancelled`, `CHDExtractionError` | `subprocess`, `os`, `pathlib`, `umsa_core.process` | Subprocess (chdman), FS (extraction output), Orchestrate (cancellation) | **No** | Core: `LaunchPreparer`, `Emulation` | ✅ Cohesive — single extraction concern |
| `launch_preparer.py` | Emulator-specific launch preparation (`prepare_mame_run`, `prepare_exodos_run`, `prepare_marp_run`, `other_emulator`, `demul`, `fsuae`, `flycast`) | `LaunchPreparer` class with prep methods | `umsa_core.rom_finder`, `rom_extractor`, `chd_extractor`, `vgm_header`, `process`, `game_repository` | Orchestrate (prep), Parse (VGM header via delegate), FS (ROM/CHD via delegates) | **No** | Core: `Emulation` (facade) | ✅ Cohesive — single prep concern |
| `rom_extractor.py` | ZIP extraction and ROM-specific post-processing | `RomExtractor.extract_rom` | `zipfile`, `os`, `pathlib`, `umsa_core.process` | FS (extract), Parse (NES header) | **No** | Core: `LaunchPreparer`, `Emulation` | ✅ Cohesive — single extraction concern |
| `rom_finder.py` | ROM and non-MAME file discovery | `RomFinder.find_roms`, `RomFinder.find_nonmame_roms` | `os`, `zipfile`, `pathlib`, `umsa_core.process` | FS (search), Parse (MAME ini) | **No** | Core: `LaunchPreparer`, `Emulation` | ✅ Cohesive — single discovery concern |
| `vgm_player.py` | VGM playback logic, header parsing, candidate loop, run preparation | `VgmPlayer.prepare_vgm_run`, `VgmPlayer.play_vgm`, `VgmPlayer.play_random_vgm`, `VgmPlayer.play_random_vgm_thread` | `umsa_core.vgm_header`, `vgm_socket`, `rom_finder`, `game_repository`, `process` | Net (Lua socket via `vgm_socket`), Parse (VGM header), FS (ROM discovery), Subprocess (MAME) | **No** | Core: `Emulation` (facade) | ✅ Cohesive — single VGM playback concern |
| `vgm_socket.py` | VGM TCP transport lifecycle, Lua log protocol, connection acceptance, command sending, log frame parsing | `VgmSocketServer` class with `start_server`, `wait_for_connection`, `send_command`, `close_client`, `close_server` | `socket`, `threading`, `subprocess`, `umsa_core.vgm_header` | Net (TCP), Subprocess (process-exit detection) | **No** | Core: `Emulation` (facade), `VgmPlayer` | ✅ Cohesive — single socket transport concern |
| `gamelist_filter.py` | Explicit-state filter/query composition (Kodi-free) | `GamelistFilter` (dataclass), `define_filter`, `execute_statement`, `software_query`, `source_query`, `category_query`, `year_query`, `players_query`, `swl_query`, `maker_query` | `sqlite3`, `umsa_core.sqlite` | DB (read `umsa.db`), Parse (SQL composition) | **No** | Core: `database.py` (facade) | ✅ Cohesive — pure query logic |
| `game_repository.py` | Read-only `umsa.db` game metadata (`GameRepository`) | `GameRepository` (18 methods: lookups, search, series, machines, parts, devices, shared features) | `sqlite3`, `umsa_core.sqlite` | DB (read `umsa.db`) | **No** | Core: `database.py` (facade), `gamelist_filter` (via `DBMod` facades), `emulation.py` (via `ggdb`) | ✅ Cohesive — single DB domain |
| `gb64_parser.py` | Parse GameBase64 metadata | `GB64Parser.parse`, `GB64Parser.__init__` | `csv`, `os` | Parse (CSV) | No | Core: `gb64_scanner.py` | ✅ Cohesive — single parser |
| `gb64_scanner.py` | Scan workflow for GameBase64 | `GB64Scanner.scan`, `GB64Scanner.__init__` | `os`, `gb64_parser`, `dat_repository`, `artwork_repository`, `scan_coordinator` | FS (walk), DB (write `dat.db`/`artwork.db`), ScanLock | No | GUI: `gui.py` via `DBMod.scan_gb64_to_db` facade | ✅ Cohesive — self-contained scan |
| `history_import.py` | One-time legacy file import (`lastgames.txt`, `filter_*.txt`) | `run_legacy_import`, `retry_import`, `discover_legacy_paths`, `ImportResult` | `os`, `json`, `sqlite3`, `umsa_core.history_repository`, `data_paths`, `sqlite` | FS (read legacy files), DB (write `status.db`) | **No** | Core: `database.py` (facade), GUI: `addon.py` (`retry_import`), `gui.py` (startup) | ✅ Cohesive — single migration concern |
| `history_repository.py` | `status.db` history tables (`gui_lastgames`, `filter_selections`, `screensaver_history`, `status_meta`) | `create_history_tables`, `HistoryRepository` (lastgames, filter, screensaver, marker), `normalize_set_id` | `sqlite3`, `umsa_core.sqlite` | DB (read/write `status.db`), Schema | **No** | Core: `database.py` (facade), Screensaver: `ui.py` (via `ggdb`), `history_import.py` | ✅ Cohesive — single DB domain |
| `logging.py` | Logger indirection (`log`, `set_log`) | `log`, `set_log` | — | — | **No** | All Core modules | ✅ Trivial — indirection only |
| `paths.py` | Batocera mapping loader | `load_batocera_mapping` | `json`, `os` | FS (read JSON) | **No** | GUI: `gui.py`, `settings_adapter.py` | ✅ Trivial — single loader |
| `persistence.py` | Legacy text-file persistence (`lastgames.txt`, `filter_*.txt`, `lastsaver.txt`) | `load_filter`, `save_filter`, `load_lastsaver`, `load_software_list`, `save_software_list` | `os` | FS (read/write text files) | **No** | GUI: `gui.py` (startup/shutdown — now migrating to `status.db`) | ✅ Cohesive — legacy persistence |
| `process.py` | Subprocess ownership (`ProcessRunner`, `ProcessState`, `ProcessStatus`, `ProcessLaunchError`) | `ProcessRunner`, `ProcessState`, `ProcessStatus`, `ProcessLaunchError` | `subprocess`, `dataclasses`, `enum` | Subprocess (wrap `Popen`) | **No** | Core: `emulation.py` | ✅ Cohesive — pure process wrapper |
| `scan_coordinator.py` | Cross-scanner lock coordination | `ScanBusyError`, `ScanLockContext`, `scan_coordinator` | `threading`, `time`, `contextlib` | Orchestrate (lock) | **No** | Core: all scanners, `database.py` (`run_scan_with_progress`) | ✅ Cohesive — single lock service |
| `settings.py` | Shared settings constants (`FILTER_CATEGORIES`, `SharedSettings`) | `FILTER_CATEGORIES`, `SharedSettings` (dataclass) | `dataclasses` | — | **No** | Core: `database.py`, `gui.py` (via adapter) | ✅ Trivial — constants |
| `sqlite.py` | SQLite connection factories + Row contract | `connect_sqlite`, `connect_sqlite_readonly`, `require_row_connection` | `sqlite3`, `os`, `urllib.request` | DB (connections) | **No** | All Core modules with DB access | ✅ Cohesive — single connection factory |
| `status_migrations.py` | `status.db` schema migration (v0→1) | `CURRENT_VERSION`, `MIGRATIONS`, `apply_migrations` | `sqlite3`, `status_repository`, `emulator_repository`, `history_repository` | DB (DDL, `PRAGMA user_version`) | **No** | Core: `database.py` (`_open_persistent_databases`) | ✅ Cohesive — single migration |
| `status_repository.py` | `status.db` play history + media (`StatusRepository`) | `create_status_tables`, `StatusRepository.get_status_for_set`, `get_further_media`, `get_latest_by_set_ids`, `write_status_after_play`, `save_further_media` | `sqlite3`, `umsa_core.sqlite` | DB (read/write `status.db`), Schema | **No** | Core: `database.py` (facade), `gui.py` (via `ggdb`) | ✅ Cohesive — single DB domain |
| `support.py` | External search helpers | `marp_search`, `marp_download`, `youtube_search` | `urllib.request`, `json`, `gzip`, `xml.etree.ElementTree` | Net (HTTP), Parse (XML/JSON) | **No** | GUI: `gui.py`, `emulation.py` | ✅ Cohesive — external APIs |
| `umsa_db_download.py` | Database download + extraction (Phase 4.9a) | `download_and_update_umsa_db` | `pathlib`, `zipfile`, `io.BytesIO`, `urllib.request` | Net (download), FS (extract) | **No** | Core: `database.py` (re-export); GUI: `umsa_gui/scan_orchestrator.py` (via `umsa_core.database`); tests import the module directly | ✅ Cohesive — standalone download; no SQL |
| `vgm_header.py` | VGM header parsing + playback plan | `VGMHeader`, `PlaybackPlan`, `parse_vgm_header`, `calculate_playback_plan` | `struct`, `gzip`, `io`, `dataclasses` | Parse (binary VGM/VGZ) | **No** | Core: `emulation.py`, `database.py` (facade), GUI: `gui.py` | ✅ Cohesive — pure parser |

---

## Kodi-Import Compliance (Boundary Tests)

All 38 modules under `lib/umsa_core/` **pass** the architecture boundary test: zero `import xbmc*` statements. The single allowed Kodi-importing module in the core add-on is `lib/umsa_core_kodi.py` (adapter).

---

## Modules with Reusable Functionality (Avoid Duplication)

| Functionality | Module | Use Instead Of |
|---------------|--------|----------------|
| Artwork path resolution | `artwork.resolve_artwork_path` | Re-implementing in GUI/Screensaver |
| Artwork categorization/aspect | `artwork.categorize_art_type`, `check_image_aspect` | Duplicate logic in `gui.py`/`ui.py` |
| VGM header parsing | `vgm_header.parse_vgm_header`, `calculate_playback_plan` | Ad-hoc parsing in GUI |
| Process management | `process.ProcessRunner` | Raw `subprocess.Popen` in `emulation.run()` fallback |
| SQLite connections | `sqlite.connect_sqlite(_readonly)` | Direct `sqlite3.connect` |
| Filter composition | `gamelist_filter.GamelistFilter`, `define_filter`, `execute_statement` | Inline SQL in GUI |
| Scan coordination | `scan_coordinator.ScanLockContext` | Ad-hoc threading locks |
| Settings/constants | `settings.FILTER_CATEGORIES`, `SharedSettings` | Hardcoded values |
| Data paths | `data_paths.CoreDataPaths` | Hardcoded paths |

---

## Modules That Could Be Consolidated (Post-Boundary Clarification)

| Candidate | Reason | Constraint |
|-----------|--------|------------|
| `artwork.py` + `artwork_repository.py` | Both deal with artwork; but one is helpers, other is DB — keep separate | DB vs. pure logic boundary |
| `dat_parser.py` + `dat_repository.py` | Parser + repository for same domain — keep separate | Parser is stateless, repo owns DB |
| `exodos_parser.py` + `exodos_artwork.py` + `exodos_scanner.py` | All eXoDOS — scanner orchestrates parser + artwork extractor | Scanner is workflow, others are utilities |
| `gb64_parser.py` + `gb64_scanner.py` | Same pattern | Keep separate |
| `history_import.py` + `history_repository.py` | Import uses repository — keep separate | Import is one-time, repo is ongoing |
| `persistence.py` | Legacy text-file ops — will be removed after migration completes | Keep until migration verified |

---

## Summary

- **35/38 modules** are clean, single-responsibility, Kodi-free, with clear boundaries
- **3 modules** need attention: `database.py` (~1857 lines, Phase 4.9 target), `emulation.py` (592 lines, facade with delegates), `artwork_scanner.py`/`dat_scanner.py`/`exodos_scanner.py`/`gb64_scanner.py` (similar pattern, could share base class but not urgent)
- No duplicate abstractions found — existing modules cover all Core domains
- Package layout respects Kodi-addon packaging (flat `lib/umsa_core/`); no subdirectories needed

---

## Phase 4.9.1 re-audit (2026-10-24, HEAD `9b62f4b`)

This section records current-state verification; it does not replace the catalog above.

- `database.py` remains ~1857 lines with no Phase 4.9 extraction beyond 4.9a.
- `umsa_db_download.py` was verified in the current tree and the row above was corrected:
  it imports only `pathlib`, `zipfile`, `io.BytesIO` and `urllib.request`; it contains no
  SQL or `data_paths` import. Its production caller is `umsa_gui/scan_orchestrator.py`
  through the `umsa_core.database` re-export.
- `scan_progress.py`, `game_labels.py` and `cmdline.py` **do not exist** at this HEAD.
- Candidate verdicts: `scan_progress.py` (justified, pure move plus re-export),
  `split_gamename` into `game_labels.py` (justified), `create_cmdline` into `cmdline.py`
  (justified), `get_best_machine_for_set` / `get_cmd_line_options` / mixed queries
  (keep in `DBMod`), `parse_recommended_games` / `build_filter_lists` (defer).
- Focused verification: 87 tests passed (`test_database`, `test_run_scan_with_progress`,
  `test_scan_coordinator`, `test_cmd_line_options`, `test_umsa_db_download`,
  `test_architecture_boundaries`).

Full detail: [`docs/database_refactor/phase_4_9_1_inventory.md`](../database_refactor/phase_4_9_1_inventory.md).