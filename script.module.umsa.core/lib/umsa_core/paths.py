"""Path mapping utilities."""


def load_batocera_mapping(mapping_file: str) -> dict[str, str]:
    """Load Batocera directory structure mapping from file.

    Args:
        mapping_file: Path to batocera-dir-struct-map.txt

    Returns:
        Dict mapping MAME source/swl names to Batocera directory names.
        Format: {'mame_source': 'batocera_dir', 'swl_name.xml': 'batocera_dir'}
    """
    mapping: dict[str, str] = {}
    try:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()
                if not line or line[0] == '#':
                    continue
                if ':' not in line:
                    continue
                bato, fmame = line.split(':', 1)
                for mame_name in fmame.split(','):
                    mame_name = mame_name.strip()
                    if mame_name and mame_name not in mapping:
                        mapping[mame_name] = bato.strip()
    except OSError:
        # File not found or unreadable - return empty mapping
        pass
    return mapping
