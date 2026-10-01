/**
 * dataset/refusal.ts — what the boot line says when the page cannot show its dataset, or cannot load at
 * all. It is imported statically by src/main.tsx (the entry chunk), so it imports nothing and stays
 * small.
 *
 * Every failure is a CODED, plain-language refusal, never an uncoded "could not load":
 *   - the dataset door's refusals (DatasetBootError, dataset/boot.ts) keep every issue's code and
 *     message — the validator's, the compiler's, or the door's own (E_HUB_*, E_STORE_*, E_WORKER …);
 *   - any other error that states a code at the head of its message (`E_NO_DATASET: …` from
 *     dataset/select.ts, `E_DATASET_SEALED: …` from dataset/slot.ts) keeps that code and its sentence;
 *   - anything else (the application chunk did not load, a mount threw) is E_APP_LOAD.
 * The first code is also kept on the element (`data-dataset-error`) for tests and support.
 */
const CODE_HEAD = /^(E_[A-Z0-9_]+):\s*/;
const sentence = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** The refusal for `err`: its first code, and the sentence(s) the boot line shows. */
export function describeRefusal(err: unknown): { code: string; text: string } {
  const refusal = err as { name?: unknown; title?: unknown; issues?: { code: string; message: string }[] } | null;
  if (refusal !== null && typeof refusal === "object" && refusal.name === "DatasetBootError" && typeof refusal.title === "string" && Array.isArray(refusal.issues)) {
    return {
      code: refusal.issues[0]?.code ?? "E_APP_LOAD",
      text: `${refusal.title}. ${refusal.issues.map((i) => `${sentence(i.message)} [${i.code}]`).join(" ")}`,
    };
  }
  const message = err instanceof Error ? err.message : "";
  const head = CODE_HEAD.exec(message);
  if (head !== null) {
    const code = head[1]!;
    return { code, text: `Atlas Scope could not load. ${sentence(message.slice(head[0].length))} [${code}]` };
  }
  return {
    code: "E_APP_LOAD",
    text: "Atlas Scope could not load: the application did not start. Reload the page; if it fails again, the build is incomplete. [E_APP_LOAD]",
  };
}

/**
 * Replace the boot line with the refusal. The boot line is a status paragraph with no focusable
 * content, written before the application mounts (once it has, the line is gone and there is nothing to
 * replace), so replacing its text cannot take focus from anything.
 */
export function showDatasetRefusal(boot: Element, err: unknown): void {
  const { code, text } = describeRefusal(err);
  boot.setAttribute("aria-busy", "false");
  boot.setAttribute("role", "alert");
  boot.setAttribute("data-dataset-error", code);
  boot.textContent = text;
}
