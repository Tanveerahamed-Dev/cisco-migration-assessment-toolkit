import type { ProjectionIdentityModule, ProjectionModule } from "./SourceExplorerTypes";

export const PROJECTION_MODULE_URL = "/atlas-projection/index.mjs";
export const PROJECTION_IDENTITY_URL = "/atlas-projection/identity.mjs";

let cachedProjection: Promise<ProjectionModule> | null = null;
let cachedProjectionIdentity: Promise<ProjectionIdentityModule> | null = null;

export async function loadProjectionIdentity(): Promise<ProjectionIdentityModule> {
  cachedProjectionIdentity ??= import(
    /* @vite-ignore */ PROJECTION_IDENTITY_URL
  ) as Promise<ProjectionIdentityModule>;
  try {
    const loaded = await cachedProjectionIdentity;
    if (
      !loaded.identity ||
      loaded.identity.status !== "complete" ||
      loaded.identity.releaseClass !== "exact_commit" ||
      loaded.identity.trackedWorktreeDirty
    ) {
      throw new Error("The projection identity is not bound to an exact clean commit.");
    }
    return loaded;
  } catch (error) {
    cachedProjectionIdentity = null;
    throw error;
  }
}

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
