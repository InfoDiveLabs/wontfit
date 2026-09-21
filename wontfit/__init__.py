"""wontfit: see your running app at phone and tablet widths, side by side.

A zero-dependency reverse proxy that strips the headers which block iframing
(``X-Frame-Options`` and CSP ``frame-ancestors``) plus a browser harness that
lays out pages as device-sized frames and says what does not fit: horizontal
overflow with the element that caused it, tap targets under 44x44 CSS px, and
text under 12px. The same checks run headlessly in CI via ``wontfit check``.

Development tool only. It binds to 127.0.0.1 and must never be exposed.
"""

__version__ = "0.2.2"

#: Device presets: key -> (human name, CSS width px).
#: Widths are the CSS viewport widths reported by the devices, not physical pixels.
PRESETS = {
    "se": ("iPhone SE", 375),
    "iphone15": ("iPhone 15", 393),
    "iphone15plus": ("iPhone 15 Plus", 430),
    "pixel8": ("Pixel 8", 412),
    "fold": ("Galaxy Fold", 344),
    "ipadmini": ("iPad Mini", 744),
    "ipad": ("iPad", 820),
    "laptop": ("Laptop", 1280),
}

#: Path prefix reserved for the harness and its endpoints. Anything else is proxied.
HARNESS_PATH = "/__wontfit"

#: Findings ``wontfit check --fail-on`` can select.
CHECK_KINDS = ("overflow", "taps", "text")
