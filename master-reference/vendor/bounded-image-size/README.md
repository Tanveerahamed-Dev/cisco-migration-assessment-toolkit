# Atlas bounded image metadata

This local package is the fail-closed `image-size` replacement used only by
the Vinext build. It accepts a bounded `Uint8Array`, validates the fixed PNG
signature and IHDR structure/checksum, or recognizes a case-sensitive,
quote-balanced and terminated SVG root marker within a fixed 512-byte prefix.
That marker is not a complete SVG validator or sanitizer. Every other image
family is rejected.

The deliberately narrow surface removes the advisory-named HEIF, JXL and ICNS
parsers from Vinext's dependency edge; JP2 and JPEG are independently
unsupported as well. It bounds parser work after Vinext has supplied a buffer,
but it does not bound Vinext's earlier file read. It does not claim general
image-format compatibility, parse SVG dimensions, establish external VEX
authority, or remediate the separate image parser bundled inside Next. Source
contracts reject static image imports and metadata-route image files until a
format has an explicitly bounded owner and hostile watchdog coverage.
