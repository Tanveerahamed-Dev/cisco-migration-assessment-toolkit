/**
 * ShortcutHelp.tsx — the "?" overlay, and the always-mounted keyboard layer behind it.
 *
 * The sheet is GENERATED from the shortcut registry. That is the whole point of it: a
 * hand-maintained key list is wrong the first time somebody adds a binding, and then the product
 * is lying about itself in the one place a lost user goes. Every row here is a live binding, its
 * keys are formatted for the detected platform, and a binding that cannot act right now is shown
 * WITH its reason rather than dropped from the list.
 *
 * The component also mounts the PENDING-KEY INDICATOR, which must exist whether or not the sheet
 * is open and has nowhere else to live: a half-typed sequence (`g` …) has to be visible rather
 * than a silent mode the user has entered by accident.
 *
 * It does NOT mount a live region. The command announcement has exactly ONE owner — `#sr-status`
 * in App.tsx — for the same reason `sr-alert` and `sr-log` have one each: the same string placed
 * in two polite regions that update in the same tick is read out twice, and a screen-reader user
 * cannot tell a double announcement from two separate events. Measured before this was fixed:
 * pressing `m` wrote the identical refusal sentence into this component's region and into
 * `#sr-status` in one tick.
 *
 * Styles live in CommandPalette.css — one stylesheet for the whole keyboard surface.
 */
import { useMemo, useState, type ReactNode } from "react";

import { Button, Dialog, Input, Kbd } from "../ui/primitives";
import {
  SCOPE_LABEL,
  SCOPE_ORDER,
  formatShortcut,
  isMacPlatform,
  setHelpOpen,
  shortcutConflicts,
  shortcutText,
  useGlobalKeyboard,
  useHelpOpen,
  usePendingKeys,
  useShortcuts,
  type Shortcut,
  type ShortcutScope,
} from "./keyboard";
import "./CommandPalette.css";

interface Section {
  scope: ShortcutScope;
  groups: { group: string; items: Shortcut[] }[];
}

function KeyCaps({ keys }: { keys: string }): ReactNode {
  return (
    <span className="kb-help__keys" aria-hidden="true">
      {formatShortcut(keys).map((t, i) =>
        t.kind === "then" ? (
          <span key={`${t.text}-${i}`} className="kb-help__then">
            then
          </span>
        ) : (
          <Kbd key={`${t.text}-${i}`}>{t.text}</Kbd>
        ),
      )}
    </span>
  );
}

/**
 * A sequence in progress. Without it, pressing `g` puts the app into a mode with no on-screen
 * evidence at all — the next keystroke behaves differently for a reason the user cannot see.
 */
function PendingKeys(): ReactNode {
  const pending = usePendingKeys();
  if (pending.length === 0) return null;
  return (
    <div className="kb-pending" role="status">
      <span className="kb-pending__keys">
        {pending.map((k, i) => (
          <Kbd key={`${k}-${i}`}>{k}</Kbd>
        ))}
        <span className="kb-pending__caret" aria-hidden="true">
          &hellip;
        </span>
      </span>
      <span className="kb-pending__hint">waiting for the next key</span>
    </div>
  );
}

export function ShortcutHelp(): ReactNode {
  /* Ref-counted: mounting this layer is enough to make the keyboard model live, and asking for it
     here as well as in the palette is not a double install. */
  useGlobalKeyboard();

  const open = useHelpOpen();
  const registry = useShortcuts();
  const [filter, setFilter] = useState("");

  const sections = useMemo<Section[]>(() => {
    const term = filter.trim().toLowerCase();
    const match = (s: Shortcut): boolean =>
      term === "" ||
      s.label.toLowerCase().includes(term) ||
      s.group.toLowerCase().includes(term) ||
      s.keys.toLowerCase().includes(term) ||
      shortcutText(s.keys).toLowerCase().includes(term);

    return SCOPE_ORDER.map((scope) => {
      const inScope = registry.filter((s) => s.scope === scope && match(s));
      const groups: { group: string; items: Shortcut[] }[] = [];
      for (const s of inScope) {
        const existing = groups.find((g) => g.group === s.group);
        if (existing) existing.items.push(s);
        else groups.push({ group: s.group, items: [s] });
      }
      return { scope, groups };
    }).filter((sec) => sec.groups.length > 0);
  }, [registry, filter]);

  const conflicts = useMemo(() => shortcutConflicts(registry), [registry]);
  const total = registry.length;
  const shown = sections.reduce((n, s) => n + s.groups.reduce((m, g) => m + g.items.length, 0), 0);

  return (
    <>
      <PendingKeys />
      <Dialog
        open={open}
        onClose={() => setHelpOpen(false)}
        title="Keyboard shortcuts"
        width="lg"
        className="kb-help"
        footer={
          <div className="kb-help__foot">
            <span>
              {shown} of {total} registered bindings shown. Keys are drawn for{" "}
              {isMacPlatform() ? "macOS" : "Windows and Linux"}, detected from this browser.
            </span>
            <Button variant="secondary" size="sm" onClick={() => setHelpOpen(false)}>
              Close
            </Button>
          </div>
        }
      >
        <Input
          label="Filter shortcuts"
          value={filter}
          onChange={(e) => setFilter(e.currentTarget.value)}
          placeholder={"trace, camera, theme…"}
          autoComplete="off"
          spellCheck={false}
        />

        {sections.length === 0 ? (
          <p className="kb-help__empty">
            No binding matches &ldquo;{filter.trim()}&rdquo;. {total} shortcuts are registered; this
            list is generated from them, so an empty result means the binding does not exist rather
            than that it is undocumented.
          </p>
        ) : (
          sections.map((sec) => (
            <section className="kb-help__scope" key={sec.scope}>
              <h3 className="kb-help__scope-title">
                {SCOPE_LABEL[sec.scope]}
                <span className="kb-help__scope-note">
                  {sec.scope === "global"
                    ? "works wherever focus is, except inside a text field"
                    : "works while focus is in that surface"}
                </span>
              </h3>
              {sec.groups.map((g) => (
                <div className="kb-help__group" key={`${sec.scope}-${g.group}`}>
                  <h4 className="kb-help__group-title">{g.group}</h4>
                  <ul className="kb-help__list">
                    {g.items.map((s) => {
                      const reason = s.unavailable?.() ?? null;
                      return (
                        <li className="kb-help__row" key={s.id}>
                          <span className="kb-help__label">
                            {s.label}
                            <span className="visually-hidden">{`: ${shortcutText(s.keys)}`}</span>
                            {reason === null ? null : (
                              <span className="kb-help__reason">{reason}</span>
                            )}
                          </span>
                          <KeyCaps keys={s.keys} />
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </section>
          ))
        )}

        {conflicts.length === 0 ? null : (
          /* Shown, not swallowed: two bindings on one key means one of them is dead, and which one
             depends on registration order. The product tells on itself rather than shipping a key
             list that is quietly false. */
          <section className="kb-help__conflicts">
            <h3 className="kb-help__scope-title">Binding conflicts</h3>
            <ul className="kb-help__list">
              {conflicts.map((c) => (
                <li className="kb-help__row kb-help__row--conflict" key={`${c.kind}-${c.ids.join("+")}`}>
                  <span className="kb-help__label">{c.reason}</span>
                  <KeyCaps keys={c.keys} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </Dialog>
    </>
  );
}

export default ShortcutHelp;
