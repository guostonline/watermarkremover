"""Static image config derived from patternslabco.com analysis."""

# Dimensions
COVER_SIZE   = "1200x628"   # Featured/OG image (landscape)
INPOST_SIZE  = "800x533"    # In-post section images (3:2)

# Visual style injected into every image prompt
SITE_STYLE = (
    "warm minimalist sewing studio aesthetic, lifestyle photography, "
    "natural daylight from a window, soft peachy-rose (#C9A99A) and cream color palette, "
    "women crafting with fabric and sewing patterns, clean modern design, "
    "inviting and accessible mood, neutral linen textures"
)

def cover_prompt(topic: str) -> str:
    return (
        f"Featured blog cover image for an article about {topic}. "
        f"Horizontal composition {COVER_SIZE}px. "
        f"{SITE_STYLE}. "
        f"High-quality editorial photography, no text overlays."
    )

def section_prompt(section_heading: str, section_body_snippet: str) -> str:
    snippet = section_body_snippet[:120].strip()
    return (
        f"In-post blog image illustrating: {section_heading}. "
        f"Context: {snippet}. "
        f"Horizontal {INPOST_SIZE}px. "
        f"{SITE_STYLE}. "
        f"No text, no watermarks."
    )
