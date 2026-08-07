import type { ProjectionModule } from "./SourceExplorerTypes";

export const PROJECTION_MODULE_URL = "/atlas-projection/index.mjs";

let cachedProjection: Promise<ProjectionModule> | null = null;

export async function loadProjection(): Promise<ProjectionModule> {
  cachedProjection ??= import(
    /* @vite-ignore */ PROJECTION_MODULE_URL
  ) as Promise<ProjectionModule>;
  try {
    const loaded = await cachedProjection;
    if (
      !loaded.projection ||
      loaded.projection.status !== "complete" ||
      loaded.projection.releaseClass !== "exact_commit" ||
      loaded.projection.trackedWorktreeDirty
    ) {
      throw new Error("The projection module is not an exact clean-commit projection.");
    }
    return loaded;
  } catch (error) {
    cachedProjection = null;
    throw error;
  }
}

export function sourceHref(path: string, line?: number): string {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `/source/${encoded}${line ? `#L${line}` : ""}`;
}

export function dossierHref(kind: "symbol" | "data" | "test" | "workflow" | "claim", id: string): string {
  return `/${kind}/${encodeURIComponent(id)}`;
}

export function shortDigest(value: string | null | undefined, length = 12): string {
  return value ? value.slice(0, length) : "not emitted";
}

export function humanBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 ** 2).toFixed(1)} MiB`;
}
