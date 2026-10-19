# P1-E: proxy_tools on the pinned Windows path — static evidence only

2026-10-19. Owner-directed inspection; no package import, test, dependency build,
installation, native renderer or lock/pin change. The existing browser remains.

## Named release block

**PROXY_TOOLS_010_LICENSE_CONFLICT — BLOCKED, unresolved.** proxy_tools 0.1.0
metadata says MIT, its source header says BSD, and its referenced LICENSE file
is absent. Dependency execution/build, wheel promotion and publication remain
held for the owner's decision. No applicable licence/copyright text is selected,
inferred, synthesized or written by this inspection.

Source archive: 2,978 bytes, SHA-256
`ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`.
One-based archive member references:

| Member | Line | Evidence |
|---|---:|---|
| `proxy_tools-0.1.0/PKG-INFO` | 8 | MIT metadata declaration |
| `proxy_tools-0.1.0/setup.py` | 14 | MIT setup declaration |
| `proxy_tools-0.1.0/proxy_tools/__init__.py` | 8 | BSD declaration; refers to LICENSE |
| Complete pinned archive | — | Referenced standalone LICENSE is absent |

The package source member is 6,409 bytes, SHA-256
`d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be`.
`portable/native_release_gate.py` owns the unconditional native promotion block;
native admission consumes it. JSON, environment and a selected wheel/text hash
cannot clear it. A build/publication authorization is not legal acceptance.
[Pinned archive metadata](https://pypi.org/pypi/proxy_tools/0.1.0/json).

## Does the unchanged Windows WebView2 path need it?

**Yes, as an import and installation dependency.** This does not establish that
every Atlas operation evaluates a Proxy object.

Inspected wheel: `pywebview-6.2.1-py3-none-any.whl`, SHA-256
`9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46`.
All 45 Python members were searched as text: 387,776 bytes total, largest 61,743
bytes; none exceeded the inspection bound.

| Exact pinned reference | Observation |
|---|---|
| Wheel `pywebview-6.2.1.dist-info/METADATA:69`, SHA-256 `8e7f87b5e50b992bc44d9f1dc03fb5218f0b6da5d6c4b9f21f93916bf44569c7` | Unconditional Requires-Dist proxy_tools, without a platform/extra marker. |
| Upstream `pyproject.toml:43`, blob `66ce930e976b0222c1eedff500dc8b28787cf343` | Same unconditional dependency; pythonnet at line 34 instead has a Windows marker. |
| `webview/__init__.py:24`, blob `6a3c9bb57ef84501c799142f439e6421857dfe77`, SHA-256 `53a631a579ce342fb45efbe4ef024b28deabb34f061bcf058fd818ce27aa7e80` | Imports module_property from proxy_tools before backend selection. |
| Same root module:88,96,104,149,512 | Five decorators apply it to OPEN_DIALOG, FOLDER_DIALOG, SAVE_DIALOG, DRAG_REGION_SELECTOR and screens. The first four are deprecated exports; screens initializes the GUI lazily and enumerates screens. |
| `webview/platforms/winforms.py:19`, blob `488233e864939a01d321230d073060a4dc5426c4` | Imports the webview root; choosing WinForms does not avoid package initialization. |
| `webview/platforms/edgechromium.py:15-16`, blob `0c8a3400151653355656fcc4fc499e69e21383f2` | Also imports the root; ordinary direct submodule import still initializes its package. |
| proxy_tools source member:178 and :56-66 | module_property aliases Proxy, which resolves its wrapped function lazily. A plain-function substitution is not established as equivalent. |

The three pywebview Python blobs above were computed from exact wheel member
bytes and matched against upstream commit
`2fc63cd6a92b8630c14f6d4dd73f9691591f8eea`. This is finite byte/source custody,
not publisher authentication or execution evidence.
[Root import/exports](https://github.com/r0x0r/pywebview/blob/2fc63cd6a92b8630c14f6d4dd73f9691591f8eea/webview/__init__.py#L24),
[dependency declaration](https://github.com/r0x0r/pywebview/blob/2fc63cd6a92b8630c14f6d4dd73f9691591f8eea/pyproject.toml#L43).

Only that root import textually references proxy_tools in the inspected Python
members; all five module_property decorator uses are there. This does not prove
runtime absence across dynamic lookup, external callers or native components.
It does not prove screens/public compatibility semantics can safely be dropped.

## Narrower route: candidate, not adopted

There is **no unchanged-package, full-dependency-install route** that omits it.
Selecting Edge/WinForms, excluding a frozen module or avoiding deprecated exports
does not remove the unconditional import or install dependency. `--no-deps`, an
sdist install and field metadata/source surgery remain forbidden.

A source-bounded candidate is a further disclosed Atlas adaptation of the same
pywebview 6.2.1 source: remove/replace those five proxy-backed exports with an
independently authored, reviewed Atlas surface using modern FileDialog/settings
and backend screen interfaces, then remove the unused import. It must not copy
the conflicted Proxy code. Public/export and lazy-screen compatibility is **not
verified**; this is evidence for owner/design review, not a compatible shim or
an implementation.

The original wheel still declares proxy_tools. A proxy_tools-free installation also
needs a reviewed adapted wheel with corresponding metadata, distinct disclosed
provenance/hash, immutable distribution, complete lock/SBOM and full native/frozen
proof. That route needs separate owner authority and exact source/metadata/output
review. It cannot be achieved by silently pruning the lock or SBOM. Replacing
pywebview with direct SDK hosting would be a different design choice, not selected.

No candidate overlay, declaration or pin was changed; no dependency build ran.
The proxy_tools route retains its named unresolved BLOCK even if a future,
separately approved closure proves it unnecessary. Removing a dependency would
not resolve its licence. Continue source implementation behind the browser.
