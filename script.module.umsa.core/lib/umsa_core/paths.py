"""Batocera folder mapping of MAME drivers and software lists."""


def load_batocera_mapping(mapping_file: str) -> dict[str, str]:
    """Return ``{driver source or '<swl>.xml': Batocera folder}`` from the mapping file.

    Lines are ``<folder>:<name>,<name>…``; the first mapping of a name wins.
    A missing or unreadable file gives ``{}``.
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
        pass
    return mapping
