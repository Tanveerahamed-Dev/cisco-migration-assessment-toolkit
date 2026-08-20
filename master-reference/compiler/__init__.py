"""Offline whole-repository intelligence compiler for the Atlas master reference.

The compiler is deliberately a build-time projection.  It never imports the
assessment engine, opens a network connection, follows a symlink, or reads a
path outside the Git worktree supplied by the caller.
"""

from .compiler import CompilationError, compile_repository

__all__ = ["CompilationError", "compile_repository"]
