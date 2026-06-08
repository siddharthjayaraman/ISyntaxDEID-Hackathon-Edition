"""ASCII-art startup banner for the ISyntaxDEID hackathon.

The logo mirrors the project's tile mark: a grid of tiles with a "T" picked
out in light squares and the signature missing bottom-right corner.
"""

# D = solid (dark) tile, L = light tile, "." = empty (missing corner).
_GRID = [
	"DDDDD",
	"DLLLD",
	"DDLDD",
	"DDLDD",
	"DDDD.",
]
_GLYPH = {"D": "████", "L": "░░░░", ".": "    "}

# Title lines shown to the right of the logo (one entry per logo text row).
_TITLE = [
	"",
	"",
	"I S y n t a x D E I D",
	"─────────────────────",
	"Hackathon Edition",
	"local .isyntax  →  .zarr.zip",
	"",
	"goal: minimise per-slide",
	"      conversion time",
	"",
]


def _logo_lines() -> list[str]:
	lines: list[str] = []
	for row in _GRID:
		block = " ".join(_GLYPH[c] for c in row)
		lines.append(block)  # each tile row is two text rows tall (≈ square)
		lines.append(block)
	return lines


def render_banner() -> str:
	logo = _logo_lines()
	width = max(len(s) for s in logo)
	out = []
	for i, logo_line in enumerate(logo):
		title = _TITLE[i] if i < len(_TITLE) else ""
		out.append(f"{logo_line.ljust(width)}    {title}".rstrip())
	return "\n".join(out)


def print_banner() -> None:
	print(render_banner())
	print()  # blank line after the banner


if __name__ == "__main__":
	print_banner()
