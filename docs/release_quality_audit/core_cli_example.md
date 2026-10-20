# Standalone `umsa_core` CLI Example — Feasibility & Design

**Audited:** 2026-10-21  
**Status:** Not implemented — feasibility confirmed, design proposed  
**Goal:** Demonstrate `umsa_core` usage from a regular Python script outside Kodi

---

## Feasibility Assessment

| Criterion | Assessment | Evidence |
|-----------|------------|----------|
| **Kodi-free imports** | ✅ Yes | `umsa_core` package has zero Kodi imports (enforced by architecture boundary tests) |
| **Public API availability** | ✅ Yes | `connect_sqlite`, `GameRepository`, `CoreDataPaths`, `parse_vgm_header`, etc. exported in `__init__.py` |
| **Database access** | ✅ Yes | `connect_sqlite()` / `connect_sqlite_readonly()` accept plain file paths |
| **Configuration** | ⚠️ Partial | `CoreDataPaths` requires profile dir; `get_core_settings()` needs Kodi adapter |
| **Testability** | ✅ Yes | All Core modules testable without Kodi (CI runs without Kodi) |

**Verdict:** **Feasible** for read-only operations (game search, metadata lookup, VGM parsing). Write operations and settings require Kodi context or manual configuration.

---

## Prerequisites

### 1. Python Environment
```bash
# Python 3.10+ (for union syntax X | Y)
python3 -c "import sys; print(sys.version)"
```

### 2. Core Package on PYTHONPATH
```bash
export PYTHONPATH="/path/to/script.umsa.mame.surfer/script.module.umsa.core/lib:$PYTHONPATH"
```

### 3. Downloaded UMSA Database
```bash
# Database files must exist (downloaded via Kodi add-on or manually)
# Required: umsa.db (read-only, attaches artwork.db, dat.db)
ls -la /path/to/umsa_profile/
# umsa.db  artwork.db  dat.db  status.db
```

### 4. Dependencies (from `requirements-dev.txt`)
```bash
pip install pytest pytest-cov ruff mypy Pillow
# Kodistubs NOT needed for Core-only usage
```

---

## Proposed Example: Game Search CLI

### Location
```
script.module.umsa.core/examples/search_game.py
```

### Functionality
```bash
# Search for a game by name
python search_game.py --db /path/to/umsa_profile/umsa.db "metal slug"

# Output:
# Found 3 games:
#   ID: 18768 | Name: Metal Slug | Year: 1996 | Maker: SNK | SWL: mame
#   ID: 18769 | Name: Metal Slug 2 | Year: 1998 | Maker: SNK | SWL: mame
#   ID: 18770 | Name: Metal Slug X | Year: 1999 | Maker: SNK | SWL: mame

# Get details for a specific game
python search_game.py --db /path/to/umsa_profile/umsa.db --id 18768

# Output:
# Game: Metal Slug (ID: 18768)
#   Year: 1996
#   Maker: SNK
#   Category: Shooter
#   Players: 2
#   Software List: mame
#   Machines: 3 (metal slug, metal slug 2, metal slug x)
#   Artwork: 12 images (snap, cover, flyer, ...)
#   VGM: Yes (vgmplay)
```

### Implementation Sketch

```python
#!/usr/bin/env python3
"""Standalone UMSA Core game search example."""

import argparse
import sys
from pathlib import Path

# Ensure Core package is importable
# sys.path.insert(0, "/path/to/script.module.umsa.core/lib")

from umsa_core import (
    connect_sqlite_readonly,
    CoreDataPaths,
    GameRepository,
    parse_vgm_header,
    calculate_playback_plan,
)


def search_games(db_path: Path, query: str) -> list[dict]:
    """Search games by name substring."""
    conn = connect_sqlite_readonly(db_path)
    conn.row_factory = conn.row_factory  # Keep default (tuple) or set sqlite3.Row
    repo = GameRepository(conn)
    
    # Use existing search method
    results, pos, count = repo.search_single(query)
    # Or use get_searchresults from DBMod facade pattern
    # For standalone, we can replicate the search logic
    
    conn.close()
    return results


def get_game_details(db_path: Path, game_id: int) -> dict:
    """Get full metadata for a game."""
    conn = connect_sqlite_readonly(db_path)
    repo = GameRepository(conn)
    
    # Get basic info
    game_info = repo.get_info_by_set_and_swl(setname, swlname)
    # Get machines
    machines, _ = repo.get_machines(swl_name)
    # Get artwork
    # Get VGM status
    
    conn.close()
    return {
        "id": game_id,
        "name": game_info["name"],
        "year": game_info["year"],
        "maker": game_info["maker"],
        # ...
    }


def main():
    parser = argparse.ArgumentParser(description="UMSA Core Game Search")
    parser.add_argument("--db", required=True, type=Path, help="Path to umsa.db")
    parser.add_argument("--id", type=int, help="Game ID to show details")
    parser.add_argument("query", nargs="?", help="Search query (name substring)")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    if args.id:
        details = get_game_details(args.db, args.id)
        print(f"Game: {details['name']} (ID: {details['id']})")
        print(f"  Year: {details['year']}")
        print(f"  Maker: {details['maker']}")
        # ...
    elif args.query:
        results = search_games(args.db, args.query)
        print(f"Found {len(results)} games:")
        for r in results:
            print(f"  ID: {r['id']} | Name: {r['name']} | Year: {r['year']} | Maker: {r['maker']} | SWL: {r['swl_name']}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## Core APIs Available for CLI Use

| Module | Key Exports | CLI Use Case |
|--------|-------------|--------------|
| `umsa_core.sqlite` | `connect_sqlite()`, `connect_sqlite_readonly()` | DB connection |
| `umsa_core.data_paths` | `CoreDataPaths` | Path resolution (manual) |
| `umsa_core.game_repository` | `GameRepository` | Game search, metadata |
| `umsa_core.dat_repository` | `DatRepository` | DAT file parsing |
| `umsa_core.artwork_repository` | `ArtworkRepository` | Artwork lookup |
| `umsa_core.vgm_header` | `parse_vgm_header()`, `calculate_playback_plan()` | VGM analysis |
| `umsa_core.process` | `ProcessRunner` | Process management (if needed) |
| `umsa_core.support` | `marp_search()`, `youtube_search()` | External search (needs network) |

---

## Minimal Test Requirements

### Unit Tests (No Kodi, No DB)
```bash
# Test VGM header parsing
.venv-debian-vm/bin/python -m pytest tests/test_vgm_header.py -v

# Test Core data structures
.venv-debian-vm/bin/python -c "
from umsa_core import VGMHeader, calculate_playback_plan, parse_vgm_header
print('Core imports OK')
"
```

### Integration Tests (Requires DB)
```bash
# Test with real umsa.db
.venv-debian-vm/bin/python -c "
import sys
sys.path.insert(0, 'script.module.umsa.core/lib')
from umsa_core import connect_sqlite_readonly, GameRepository
conn = connect_sqlite_readonly('/path/to/umsa.db')
repo = GameRepository(conn)
results, pos, count = repo.search_single('metal slug')
print(f'Found {count} games')
for r in results[:3]:
    print(f'  {r[\"id\"]}: {r[\"name\"]} ({r[\"year\"]})')
conn.close()
"
```

### Test File Location
```
script.module.umsa.core/examples/
├── search_game.py          # Main CLI example
├── test_search_game.py     # Unit tests
└── README.md               # Usage docs
```

---

## Acceptance Criteria for Example

| Criterion | Verification |
|-----------|--------------|
| **Imports work without Kodi** | `python -c "import sys; sys.path.insert(0, '.../lib'); import umsa_core"` succeeds |
| **Read-only DB connection** | `connect_sqlite_readonly()` works with real `umsa.db` |
| **Game search returns results** | `GameRepository.search_single()` returns expected data |
| **No Kodi imports in example** | `grep -r "xbmc" examples/` returns nothing |
| **Runnable from command line** | `python search_game.py --db umsa.db "metal slug"` produces output |
| **Documented prerequisites** | README.md explains DB download, PYTHONPATH setup |

---

## Documentation Needed

### `examples/README.md`
```markdown
# UMSA Core Examples

## Prerequisites
1. Python 3.10+
2. Downloaded UMSA database (`umsa.db`, `artwork.db`, `dat.db`)
3. Core package on PYTHONPATH

## Quick Start
```bash
export PYTHONPATH="/path/to/script.module.umsa.core/lib:$PYTHONPATH"
python search_game.py --db /path/to/umsa_profile/umsa.db "metal slug"
```

## Database Setup
The UMSA database is normally downloaded by the Kodi add-on. To use these examples:
1. Install the UMSA MAME Surfer add-on in Kodi
2. Run the add-on once to download the database
3. Copy the database files from Kodi's userdata:
   `~/.kodi/userdata/addon_data/script.module.umsa.core/`
4. Point `--db` to the `umsa.db` file in that directory
```

---

## Limitations & Future Work

| Limitation | Workaround |
|------------|------------|
| No Kodi settings access | Hardcode paths or use config file |
| No write access to `status.db` | Read-only by design for CLI |
| No automatic DB download | Manual copy from Kodi profile |
| Settings-dependent paths | Pass explicitly via CLI args |

---

## Status

| Item | Status |
|------|--------|
| Feasibility confirmed | ✅ |
| Design proposed | ✅ |
| Implementation | ⏳ Not started |
| Tests | ⏳ Not started |
| Documentation | ⏳ Not started |

---

## Recommendation

**Priority:** P2 (Post-release or parallel)

**Rationale:** Low risk, high value for developers and users wanting to integrate UMSA data. Demonstrates Core's Kodi-independence concretely.

**First Step:** Create `script.module.umsa.core/examples/search_game.py` with basic search, add to `docs/release-plan.md` as P2 item.