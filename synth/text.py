def latin(s: str) -> str:
    """Keep text inside cp1252 (WinAnsi), which ReportLab's built-in fonts can render."""
    return s.encode("cp1252", errors="replace").decode("cp1252")
