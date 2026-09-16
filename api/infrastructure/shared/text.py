def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def prefix_within_utf16_limit(text: str, limit: int) -> int:
    units = 0
    for index, character in enumerate(text):
        character_units = 2 if ord(character) > 0xFFFF else 1
        if units + character_units > limit:
            return index
        units += character_units
    return len(text)


def chunk_text(text: str, limit: int) -> list[str]:
    if utf16_length(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while utf16_length(remaining) > limit:
        split_at = prefix_within_utf16_limit(remaining, limit)
        newline_at = remaining.rfind("\n", 0, split_at)
        if newline_at >= 0:
            split_at = newline_at + 1
        if split_at == 0:
            split_at = 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks
