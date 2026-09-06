"""phoneframes: preview a local web app at phone and tablet sizes, side by side.

A zero-dependency reverse proxy that strips the headers which block iframing
(``X-Frame-Options`` and CSP ``frame-ancestors``) plus a browser harness that
lays out pages as device-sized frames with layout diagnostics and live reload.

Development tool only. It binds to 127.0.0.1 and must never be exposed.
"""

__version__ = "0.1.0"

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
HARNESS_PATH = "/__phoneframes"

#: Findings ``phoneframes check --fail-on`` can select.
CHECK_KINDS = ("overflow", "taps", "text")
