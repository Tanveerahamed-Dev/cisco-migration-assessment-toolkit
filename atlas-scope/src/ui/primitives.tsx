/**
 * primitives.tsx — the component vocabulary every other surface is built from.
 *
 * Six other agents consume this file and will not read its implementation, so the public props
 * are deliberately small and obvious. Three properties hold across every component here:
 *
 *   1. REAL SEMANTICS. A button is a <button>. A switch is role="switch". A tab strip implements
 *      the APG tabs pattern with roving tabindex. Nothing is a div with a click handler.
 *   2. NO MEANING IN COLOUR ALONE. SeverityBadge, StateDot, Band, Toggle and NotObserved each
 *      carry a glyph SHAPE and the literal word in addition to their token colour, so they
 *      survive a greyscale capture and a colour-blind reader (WCAG 1.4.1, acceptance D8).
 *   3. ABSENCE IS NOT HEALTH. `null` means NOT OBSERVED. `NotObserved` is the one renderer for
 *      it, and `orNotObserved()` is the one way to reach that renderer. Nothing in this app may
 *      turn a missing datum into a blank cell, a zero, a dash, or a green tick.
 *
 * Determinism: nothing here calls Math.random() or Date.now() on a path that affects what is
 * drawn, so two capture runs are byte-identical (acceptance F6).
 */
import {
  Children,
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentPropsWithRef,
  type CSSProperties,
  type FocusEventHandler,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEventHandler,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import type { BandPresentation } from "../core/band-qualification";
import { T8_coverageLine } from "../core/claims";
import { ribCountQualifier } from "../forwarding/rib-completeness";
import type { Cite as CitePath, OpStatus, Severity } from "../core/types";
import {
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconCite,
  IconClose,
  IconCopy,
  IconNotObserved,
  SEVERITY_ICON,
  STATE_ICON,
} from "./icons";
/* The one owner of focus return (acceptance D3). A dependency-free DOM leaf, so importing it from
   the primitives layer creates no cycle. */
import { handOffFocus, releaseFocusFrom, returnFocus, useReleaseFocusOnHide, type Successor } from "../app/focus-return";
import "./primitives.css";

const cx = (...parts: (string | false | null | undefined)[]): string =>
  parts.filter(Boolean).join(" ");

/** Everything a focus trap and a roving tabindex agree counts as reachable. */
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"]),[contenteditable="true"],summary';

/** `hidden` subtrees are out of the accessibility tree, so they are out of the tab order too. */
const visible = (el: HTMLElement): boolean => el.closest("[hidden]") === null;

const focusablesIn = (root: HTMLElement | null): HTMLElement[] =>
  root ? [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(visible) : [];

/* ══ absence ═══════════════════════════════════════════════════════════════
   The most important thing in this file. Read the header of tokens.css for the visual contract:
   dashed edge, 45-degree hatch, the literal words, plus the collector's reason when we have one.
   Three independent channels so it survives greyscale, colour-blindness and a screen reader. */

/**
 * The engine writes its own absence marker into free-text fields, e.g.
 * `[NOT OBSERVED] - no 'show track' evidence; object tracking NOT assessed`. Seventeen fields in
 * the compiled snapshot carry it. Rendering that string raw would put a machine marker in front
 * of a reader; stripping it silently would delete the reason. We parse it and keep the reason.
 */
const ABSENCE_MARKER = /^\s*\[NOT\s+OBSERVED\]\s*[-–—:]?\s*(.*)$/is;

export interface NotObservedProps {
  /** The datum that is missing, e.g. "CRC errors". Used for the accessible sentence. */
  what?: string;
  /** Why it is missing, when the collector said. Rendered verbatim — never paraphrased. */
  why?: string | null;
  /** Dense-cell form: glyph plus the short words, no reason text. */
  compact?: boolean;
  /** The citation for the record the value would have come from. */
  cite?: CitePath;
  onOpenCite?: (cite: CitePath) => void;
  className?: string;
}

/**
 * The canonical renderer for a value we did not collect. It is never an empty node, never a dash,
 * never a blank cell: a reader must be able to tell "we looked and it was zero" from "we never
 * looked", and this is the only component in the app that says the second thing.
 */
export function NotObserved({
  what,
  why,
  compact = false,
  cite,
  onOpenCite,
  className,
}: NotObservedProps): ReactElement {
  const reason = typeof why === "string" && why.trim() !== "" ? why.trim() : null;
  return (
    <span
      className={cx("ui-notobs", compact && "ui-notobs--compact", className)}
      data-unobserved="true"
    >
      <IconNotObserved className="ui-notobs__glyph" />
      {/* The WORDS are never hidden, in either form. `compact` drops the reason and tightens the
          padding; it does not turn the mark into a glyph a reader has to decode. A dense cell
          showing only a dashed box is one bad guess away from reading as a checkbox. */}
      {what ? <span className="visually-hidden">{`${what}: `}</span> : null}
      <span className="ui-notobs__text">not observed</span>
      {reason && compact ? (
        <span className="visually-hidden">{` Reason: ${reason}`}</span>
      ) : null}
      {/* The reason's own box separates it visually; the hidden dash separates it in the TEXT, so a
          screen reader or a copy does not read "not observedno RIB was collected". */}
      {reason && !compact ? <span className="visually-hidden">{" — "}</span> : null}
      {reason && !compact ? <span className="ui-notobs__why">{reason}</span> : null}
      {!compact && cite && onOpenCite ? <Cite cite={cite} onOpen={onOpenCite} /> : null}
    </span>
  );
}

/**
 * True when a value is real evidence rather than an absence. Use it for denominators: counting
 * `values.filter(isObserved).length` against `values.length` is how a coverage figure stays
 * honest. Empty and whitespace-only strings count as absence because the engine emits them for
 * fields it could not fill, and NaN counts as absence because it is never a measurement.
 */
export function isObserved(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return value.trim() !== "" && !ABSENCE_MARKER.test(value);
  return true;
}

/**
 * The one way any surface renders a possibly-absent value. Every other agent calls this instead
 * of writing `value ?? "—"`, which is how the treatment is kept from drifting apart across six
 * surfaces built in parallel.
 *
 *   orNotObserved(port.crcErrors, (n) => n.toLocaleString(), { what: "CRC errors" })
 *
 * Absence is: null, undefined, NaN, an empty or whitespace-only string, and the engine's own
 * `[NOT OBSERVED] - reason` marker — whose reason is carried through to the reader rather than
 * being swallowed.
 */
export function orNotObserved<T>(
  value: T | null | undefined,
  render?: (v: NonNullable<T>) => ReactNode,
  opts?: Omit<NotObservedProps, "why"> & { why?: string | null },
): ReactNode {
  if (typeof value === "string") {
    const marked = ABSENCE_MARKER.exec(value);
    if (marked) return <NotObserved {...opts} why={marked[1] ?? opts?.why ?? null} />;
  }
  if (!isObserved(value)) return <NotObserved {...opts} />;
  const v = value as NonNullable<T>;
  return render ? render(v) : String(v);
}

/* ══ text utilities ════════════════════════════════════════════════════════ */

export function VisuallyHidden({ children }: { children: ReactNode }): ReactElement {
  return <span className="visually-hidden">{children}</span>;
}

/**
 * A live region. Mount it once per surface and change `message` to announce. `assertive`
 * interrupts the user and is reserved for errors — a polite region is right for everything else.
 * The node is always present: a live region created at announce time is not announced.
 */
export function LiveRegion({
  message,
  assertive = false,
}: {
  message: string;
  assertive?: boolean;
}): ReactElement {
  return (
    <div
      className="visually-hidden"
      role={assertive ? "alert" : "status"}
      aria-live={assertive ? "assertive" : "polite"}
      aria-atomic="true"
    >
      {message}
    </div>
  );
}

/* ══ buttons ═══════════════════════════════════════════════════════════════ */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

interface ButtonCommon {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading glyph. Decorative: the accessible name comes from the button's text. */
  icon?: ReactNode;
}

export interface ButtonProps extends ComponentPropsWithRef<"button">, ButtonCommon {
  /** Required. An unlabelled button is an IconButton, which demands an explicit name. */
  children: ReactNode;
}

/**
 * `type` defaults to "button". A bare <button> inside a form defaults to submit, which is how a
 * filter control ends up reloading the page.
 */
export function Button({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className,
  type = "button",
  ...rest
}: ButtonProps): ReactElement {
  return (
    <button
      {...rest}
      type={type}
      data-variant={variant}
      data-size={size}
      className={cx("ui-btn", className)}
    >
      {icon ? <span className="ui-btn__icon">{icon}</span> : null}
      <span className="ui-btn__label">{children}</span>
    </button>
  );
}

export interface IconButtonProps
  extends Omit<ComponentPropsWithRef<"button">, "children" | "aria-label">,
    ButtonCommon {
  /** Mandatory: this is the button's only accessible name. A tooltip is not a substitute. */
  label: string;
  icon: ReactNode;
  /** Render the label next to the glyph as well. */
  showLabel?: boolean;
}

export function IconButton({
  label,
  icon,
  showLabel = false,
  variant = "ghost",
  size = "md",
  className,
  type = "button",
  ...rest
}: IconButtonProps): ReactElement {
  return (
    <button
      {...rest}
      type={type}
      aria-label={showLabel ? undefined : label}
      data-variant={variant}
      data-size={size}
      className={cx("ui-btn", !showLabel && "ui-btn--icon", className)}
    >
      <span className="ui-btn__icon">{icon}</span>
      {showLabel ? <span className="ui-btn__label">{label}</span> : null}
    </button>
  );
}

/* ══ chips, badges, dots ═══════════════════════════════════════════════════ */

export interface ChipProps {
  children: ReactNode;
  /** Makes the chip's body a button — for a query token that re-opens its editor. */
  onClick?: () => void;
  /** Adds a separate remove control. Never merged with onClick: two actions, two targets. */
  onRemove?: () => void;
  /** Accessible name for the remove control, e.g. "Remove severity filter Critical". */
  removeLabel?: string;
  /**
   * Where focus goes when removing this chip leaves no other control in its group — typically the
   * field whose scope the chip was part of. Before that, focus goes to the next chip in the group,
   * else the previous one; after it, to the group's label or region. The remove control takes
   * ITSELF out of the page, so without a hand-off focus falls to <body> (acceptance D3; owned by
   * `handOffFocus` in src/app/focus-return.ts).
   */
  removeSuccessor?: Successor;
  tone?: "neutral" | "accent";
  mono?: boolean;
  title?: string;
}

export function Chip({
  children,
  onClick,
  onRemove,
  removeLabel,
  removeSuccessor,
  tone = "neutral",
  mono = false,
  title,
}: ChipProps): ReactElement {
  return (
    <span className={cx("ui-chip", mono && "ui-chip--mono")} data-tone={tone} title={title}>
      {onClick ? (
        <button type="button" className="ui-chip__body" onClick={onClick}>
          {children}
        </button>
      ) : (
        <span className="ui-chip__body">{children}</span>
      )}
      {onRemove ? (
        <button
          type="button"
          className="ui-chip__remove"
          onClick={(e) => handOffFocus(e.currentTarget, onRemove, removeSuccessor === undefined ? [] : [removeSuccessor])}
          aria-label={removeLabel ?? "Remove"}
        >
          <IconClose />
        </button>
      ) : null}
    </span>
  );
}

const SEVERITY_INITIAL: Readonly<Record<Severity, string>> = {
  Critical: "C",
  High: "H",
  Medium: "M",
  Low: "L",
  Info: "I",
};

/**
 * Severity as three simultaneous channels: token colour, a distinct glyph silhouette, and the
 * word itself. In `compact` form the word shrinks to its initial and the full word moves into the
 * accessible name — the SHAPE is never dropped, because it is the channel that survives both a
 * greyscale capture and colour-blindness.
 */
export function SeverityBadge({
  severity,
  compact = false,
  className,
}: {
  severity: Severity;
  compact?: boolean;
  className?: string;
}): ReactElement {
  const Glyph = SEVERITY_ICON[severity];
  return (
    <span
      className={cx("ui-sev", compact && "ui-sev--compact", className)}
      data-severity={severity}
    >
      {/*
       * ONE IDIOM PER COLUMN.
       *
       * The full badge keeps the brief's distinct severity shapes: at 13px an octagon, a triangle
       * and a rotated square are genuinely different silhouettes and they are the reason the badge
       * survives a greyscale capture.
       *
       * The COMPACT badge does not. In a 24px grid track the glyph renders at roughly 7px, where
       * the octagon and the circle are the same dot and the triangle is a different idiom sitting
       * beside them — the shape channel stops carrying information and starts reading as two kinds
       * of icon in one column. So the compact badge drops the glyph and keeps the INITIAL, which is
       * legible at that size and is still a non-colour channel: WCAG 1.4.1 is satisfied by text
       * here rather than by a shape too small to resolve. The word remains the accessible name.
       */}
      {compact ? null : <Glyph className="ui-sev__glyph" />}
      <span className="ui-sev__text" aria-hidden={compact || undefined}>
        {compact ? SEVERITY_INITIAL[severity] : severity}
      </span>
      {compact ? <span className="visually-hidden">{`${severity} severity`}</span> : null}
    </span>
  );
}

/** Anything the engine did not spell `up` or `down` is unknown — never optimistically up. */
export const normalizeState = (s: OpStatus | null | undefined): "up" | "down" | "unknown" =>
  s === "up" ? "up" : s === "down" ? "down" : "unknown";

/**
 * Operational state as a glyph whose SHAPE differs per state — filled disc, filled square, dashed
 * ring — so `down` and `unknown` are not two colours of the same dot. The literal state word is
 * always in the accessible name and optionally on screen.
 *
 * An unrecognised status string (the model types `OpStatus` as `string`) renders as unknown and
 * keeps the literal value in its accessible name, so a new engine value shows up as "unknown" and
 * not as "up".
 */
export function StateDot({
  state,
  showLabel = false,
  className,
}: {
  state: OpStatus | null | undefined;
  showLabel?: boolean;
  className?: string;
}): ReactElement {
  const kind = normalizeState(state);
  const literal = typeof state === "string" && state.trim() !== "" ? state : "unknown";
  const Glyph = STATE_ICON[kind];
  return (
    <span className={cx("ui-state", className)} data-state={kind}>
      <Glyph className="ui-state__glyph" />
      {showLabel ? <span className="ui-state__text">{literal}</span> : null}
      {showLabel ? null : <span className="visually-hidden">{`state ${literal}`}</span>}
    </span>
  );
}

/**
 * A health band. `null` is the common case in this data and it is NOT a passing grade: three
 * devices carry no band at all, and they render as not-observed rather than as Good.
 */
/**
 * A health band pill. It takes the band owner's PRESENTATION (core/band-qualification.ts
 * `presentBand`), never a raw band: a favourable band on a device whose score partly measures
 * missing evidence prints "Excellent (partial)" in the neutral ink with a dashed outline and names
 * the gaps in its tooltip. The word "partial" carries the qualification, so it survives greyscale
 * and forced colours; the neutral ink and dashed edge only reinforce it (B1).
 */
export function Band({
  band,
  cite,
  onOpenCite,
  className,
}: {
  band: BandPresentation | null | undefined;
  cite?: CitePath;
  onOpenCite?: (cite: CitePath) => void;
  className?: string;
}): ReactNode {
  if (!band || band.legendKey === "none") {
    return (
      <NotObserved
        what="health band"
        why="the device was not scored in this snapshot"
        compact
        {...(cite ? { cite } : {})}
        {...(onOpenCite ? { onOpenCite } : {})}
      />
    );
  }
  return (
    <span
      className={cx("ui-band", band.qualified && "ui-band--partial", className)}
      data-band={band.legendKey}
      {...(band.qualified
        ? {
            "data-band-partial": "",
            title: band.sentence,
            style: { "--band-fill": `var(${band.colorToken})`, borderStyle: "dashed" } as CSSProperties,
          }
        : {})}
    >
      {band.label}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }): ReactElement {
  return <kbd className="ui-kbd">{children}</kbd>;
}

/* ══ form controls ═════════════════════════════════════════════════════════ */

export interface FieldProps {
  label: ReactNode;
  htmlFor: string;
  hint?: ReactNode;
  hintId?: string;
  error?: ReactNode;
  errorId?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

export function Field({
  label,
  htmlFor,
  hint,
  hintId,
  error,
  errorId,
  required = false,
  children,
  className,
}: FieldProps): ReactElement {
  return (
    <div className={cx("ui-field", className)}>
      <Label htmlFor={htmlFor} required={required}>
        {label}
      </Label>
      {children}
      {hint ? (
        <p className="ui-field__hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="ui-field__error" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function Label({
  htmlFor,
  required = false,
  children,
}: {
  htmlFor: string;
  required?: boolean;
  children: ReactNode;
}): ReactElement {
  return (
    <label className="ui-label" htmlFor={htmlFor}>
      {children}
      {/* "required" is a word, not an asterisk: an asterisk alone is a colour-free but
          meaning-free marker that screen readers read as "star". */}
      {required ? <span className="ui-label__req"> (required)</span> : null}
    </label>
  );
}

export interface InputProps extends Omit<ComponentPropsWithRef<"input">, "id"> {
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  mono?: boolean;
  id?: string;
}

export function Input({
  label,
  hint,
  error,
  mono = false,
  id,
  className,
  required,
  ...rest
}: InputProps): ReactElement {
  const auto = useId();
  const inputId = id ?? auto;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const described = cx(hint ? hintId : "", error ? errorId : "").trim();
  return (
    <Field
      label={label}
      htmlFor={inputId}
      {...(hint ? { hint, hintId } : {})}
      {...(error ? { error, errorId } : {})}
      required={required ?? false}
    >
      <input
        {...rest}
        id={inputId}
        required={required}
        aria-describedby={described === "" ? undefined : described}
        aria-invalid={error ? true : undefined}
        className={cx("ui-input", mono && "ui-input--mono", className)}
      />
    </Field>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<ComponentPropsWithRef<"select">, "id" | "children"> {
  label: string;
  options: readonly SelectOption[];
  hint?: ReactNode;
  id?: string;
}

export function Select({
  label,
  options,
  hint,
  id,
  className,
  ...rest
}: SelectProps): ReactElement {
  const auto = useId();
  const selectId = id ?? auto;
  const hintId = `${selectId}-hint`;
  return (
    <Field label={label} htmlFor={selectId} {...(hint ? { hint, hintId } : {})}>
      <div className="ui-select">
        <select
          {...rest}
          id={selectId}
          aria-describedby={hint ? hintId : undefined}
          className={cx("ui-select__el", className)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <IconChevronDown className="ui-select__chev" />
      </div>
    </Field>
  );
}

/**
 * A switch. The knob POSITION and a check/dash glyph carry the state alongside the colour, so it
 * is readable with the hue removed.
 */
export function Toggle({
  label,
  checked,
  onChange,
  disabled = false,
  describedBy,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  describedBy?: string;
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={describedBy}
      disabled={disabled}
      className="ui-switch"
      onClick={() => onChange(!checked)}
    >
      <span className="ui-switch__track" aria-hidden="true">
        <span className="ui-switch__knob">{checked ? <IconCheck /> : null}</span>
      </span>
      <span className="ui-switch__label">{label}</span>
    </button>
  );
}

/* ══ tabs (APG) ════════════════════════════════════════════════════════════ */

export interface TabItem {
  id: string;
  label: ReactNode;
  /**
   * `undefined` renders no count. `null` renders the not-observed mark — a tab whose denominator
   * is unknown must not show a blank where a number belongs.
   */
  count?: number | null;
}

export interface TabsProps {
  /** Stable prefix for the generated tab and panel ids. Pass the same value to TabPanel. */
  id: string;
  /** Accessible name for the tab list, e.g. "Evidence". */
  label: string;
  items: readonly TabItem[];
  value: string;
  onChange: (id: string) => void;
  /**
   * "automatic" selects on arrow (APG's preference when panels are cheap — ours are synchronous).
   * "manual" moves focus only and selects on Enter/Space.
   */
  activation?: "automatic" | "manual";
  className?: string;
}

export function Tabs({
  id,
  label,
  items,
  value,
  onChange,
  activation = "automatic",
  className,
}: TabsProps): ReactElement {
  const listRef = useRef<HTMLDivElement>(null);

  const focusTab = useCallback((index: number) => {
    const tabs = [...(listRef.current?.querySelectorAll<HTMLElement>('[role="tab"]') ?? [])];
    tabs[index]?.focus();
  }, []);

  /* A11Y AUDIT FIX, 2026-09-21. There used to be a `TabItem.disabled`, rendered as the NATIVE
     `disabled` attribute, and `enabled` was the subset the arrow keys rove over.
     Measured on the device pane (`review/_audit_a11y_tabs.mjs`): `dp-tab-acl` carried
     `disabled=""`, so it was out of the tab order AND skipped by this roving — ten ArrowRights
     cycled routing→findings→raw→summary→ports and never once landed on it. Its label
     ("ACL — no ACL collected") is the only place that surface states the coverage gap, so a
     keyboard or screen-reader user could not reach the fact at all.

     The state those tabs were expressing was never "disabled". A tab whose panel renders a
     NotObserved explanation is a working tab with an absence behind it — which is exactly how the
     sibling routing tab ("no RIB collected") already behaved, un-disabled and reachable. So the
     concept is gone rather than softened: every tab is in the roving cycle, every tab activates,
     and the absence is carried by the label and by the panel. There is no `aria-disabled` either,
     because a control that works must not claim it does not.  */
  const order = items;

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    /* The tab under FOCUS, which in manual activation is not the selected one. Reading `value`
       here instead would make Enter re-select the tab the user just moved away from — the whole
       point of manual activation is that focus and selection have separated. */
    const focusedId = (): string | null => {
      const el = (e.target as HTMLElement | null)?.closest?.('[role="tab"]') ?? null;
      const all = [...(listRef.current?.querySelectorAll<HTMLElement>('[role="tab"]') ?? [])];
      const i = el ? all.indexOf(el as HTMLElement) : -1;
      return i === -1 ? null : (items[i]?.id ?? null);
    };
    const here = focusedId() ?? value;
    const step = (delta: number): void => {
      if (order.length === 0) return;
      const at = order.findIndex((t) => t.id === here);
      const base = at === -1 ? 0 : at;
      const next = order[(base + delta + order.length) % order.length];
      if (!next) return;
      const pos = items.findIndex((t) => t.id === next.id);
      focusTab(pos);
      if (activation === "automatic") onChange(next.id);
    };
    const jump = (target: TabItem | undefined): void => {
      if (!target) return;
      focusTab(items.findIndex((t) => t.id === target.id));
      if (activation === "automatic") onChange(target.id);
    };
    switch (e.key) {
      case "ArrowRight":
        e.preventDefault();
        step(1);
        break;
      case "ArrowLeft":
        e.preventDefault();
        step(-1);
        break;
      case "Home":
        e.preventDefault();
        jump(order[0]);
        break;
      case "End":
        e.preventDefault();
        jump(order[order.length - 1]);
        break;
      case "Enter":
      case " ":
        /* preventDefault stops the browser turning this keydown into a click on the same button,
           which would fire onChange a second time. */
        if (activation === "manual" && here) {
          e.preventDefault();
          onChange(here);
        }
        break;
      default:
        break;
    }
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      className={cx("ui-tabs", className)}
      onKeyDown={onKeyDown}
    >
      {items.map((t) => {
        const selected = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`${id}-tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`${id}-panel-${t.id}`}
            /* Roving tabindex: exactly one tab is in the tab order, and Tab from it lands on the
               panel rather than walking every tab. */
            tabIndex={selected ? 0 : -1}
            className="ui-tab"
            onClick={() => onChange(t.id)}
          >
            <span className="ui-tab__label">{t.label}</span>
            {t.count === undefined ? null : t.count === null ? (
              <NotObserved what="count" compact className="ui-tab__count" />
            ) : (
              <span className="ui-tab__count">{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({
  id,
  tabId,
  active,
  children,
  className,
}: {
  /** Must match the `id` given to Tabs. */
  id: string;
  tabId: string;
  active: boolean;
  children: ReactNode;
  className?: string;
}): ReactElement {
  const panelRef = useRef<HTMLDivElement>(null);
  /* A panel hidden by its owner (a link or a command changing the tab) while focus is inside it hands
     focus to the tab strip's selected tab — never to <body>. */
  useReleaseFocusOnHide(panelRef, active, () => {
    const own = document.getElementById(`${id}-tab-${tabId}`);
    const selected = own?.closest('[role="tablist"]')?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    return [selected, own];
  });
  return (
    <div
      ref={panelRef}
      role="tabpanel"
      id={`${id}-panel-${tabId}`}
      aria-labelledby={`${id}-tab-${tabId}`}
      hidden={!active}
      /* APG: the panel itself is focusable so Tab from the tab strip reaches the content even
         when the panel's first element is plain text. */
      tabIndex={0}
      className={cx("ui-tabpanel", className)}
    >
      {children}
    </div>
  );
}

/* ══ disclosure ════════════════════════════════════════════════════════════ */

export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  open: controlled,
  onOpenChange,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}): ReactElement {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const open = controlled ?? uncontrolled;
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const regionRef = useRef<HTMLDivElement>(null);
  /* A region closed by its owner while focus is inside it hands focus to its own trigger. */
  useReleaseFocusOnHide(regionRef, open, () => [triggerRef.current]);
  const toggle = (): void => {
    const next = !open;
    if (controlled === undefined) setUncontrolled(next);
    onOpenChange?.(next);
  };
  return (
    <div className={cx("ui-disclosure", className)} data-open={open}>
      <button
        ref={triggerRef}
        type="button"
        className="ui-disclosure__trigger"
        aria-expanded={open}
        aria-controls={`${id}-region`}
        onClick={toggle}
      >
        <IconChevronRight className="ui-disclosure__chev" />
        <span className="ui-disclosure__summary">{summary}</span>
      </button>
      <div ref={regionRef} id={`${id}-region`} role="region" hidden={!open} className="ui-disclosure__region">
        {children}
      </div>
    </div>
  );
}

/* ══ overlays ══════════════════════════════════════════════════════════════ */

type TriggerLike = {
  "aria-describedby"?: string;
  "aria-expanded"?: boolean;
  "aria-haspopup"?: "dialog";
  "aria-controls"?: string;
  onMouseEnter?: MouseEventHandler<HTMLElement>;
  onMouseLeave?: MouseEventHandler<HTMLElement>;
  onFocus?: FocusEventHandler<HTMLElement>;
  onBlur?: FocusEventHandler<HTMLElement>;
  onClick?: MouseEventHandler<HTMLElement>;
};

interface Rect {
  top: number;
  left: number;
  bottom: number;
  width: number;
}

const rectOf = (el: HTMLElement | null): Rect =>
  el
    ? (() => {
        const r = el.getBoundingClientRect();
        return { top: r.top, left: r.left, bottom: r.bottom, width: r.width };
      })()
    : { top: 0, left: 0, bottom: 0, width: 0 };

function Portal({ children }: { children: ReactNode }): ReactNode {
  if (typeof document === "undefined") return null;
  return createPortal(children, document.body);
}

/**
 * A tooltip. Three rules it exists to satisfy:
 *   - reachable by KEYBOARD as well as pointer (WCAG 1.4.13 hoverable/focusable);
 *   - dismissible with Escape without moving focus (1.4.13);
 *   - never the only source of an accessible name — it is wired with aria-describedby, and the
 *     trigger is required to carry its own name. An IconButton's `label` is not optional for
 *     exactly this reason.
 * The content stays up while the pointer is over the tooltip itself, so a link or a long string
 * inside it can actually be read.
 */
export function Tooltip({
  content,
  children,
  placement = "top",
}: {
  content: ReactNode;
  children: ReactElement<Partial<TriggerLike>>;
  placement?: "top" | "bottom";
}): ReactElement {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<Rect>({ top: 0, left: 0, bottom: 0, width: 0 });
  const anchorRef = useRef<HTMLSpanElement>(null);
  const dismissed = useRef(false);
  const overTip = useRef(false);

  const show = useCallback(() => {
    if (dismissed.current) return;
    setRect(rectOf(anchorRef.current?.firstElementChild as HTMLElement | null));
    setOpen(true);
  }, []);
  const hide = useCallback(() => {
    if (overTip.current) return;
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      /* 1.4.13: dismissible WITHOUT moving focus. The flag keeps it dismissed until the pointer
         leaves and focus moves on, so Escape is not undone by the mouse still sitting there. */
      dismissed.current = true;
      /* Consumed: the app's global Escape (keyboard.ts skips a defaultPrevented key) must not also close
         the drawer or a transient in the same keystroke. */
      e.preventDefault();
      setOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open]);

  const child = Children.only(children);
  const p = child.props;
  const trigger = cloneElement(child, {
    "aria-describedby": open ? id : p["aria-describedby"],
    onMouseEnter: (e) => {
      p.onMouseEnter?.(e);
      show();
    },
    onMouseLeave: (e) => {
      p.onMouseLeave?.(e);
      dismissed.current = false;
      hide();
    },
    onFocus: (e) => {
      p.onFocus?.(e);
      show();
    },
    onBlur: (e) => {
      p.onBlur?.(e);
      dismissed.current = false;
      overTip.current = false;
      setOpen(false);
    },
  } satisfies Partial<TriggerLike>);

  return (
    <span className="ui-tt-anchor" ref={anchorRef}>
      {trigger}
      {open ? (
        <Portal>
          <div
            role="tooltip"
            id={id}
            className="ui-tooltip"
            data-placement={placement}
            style={
              {
                "--tt-top": `${placement === "top" ? rect.top : rect.bottom}px`,
                "--tt-left": `${rect.left + rect.width / 2}px`,
              } as CSSProperties
            }
            onMouseEnter={() => {
              overTip.current = true;
            }}
            onMouseLeave={() => {
              overTip.current = false;
              setOpen(false);
            }}
          >
            {content}
          </div>
        </Portal>
      ) : null}
    </span>
  );
}

/* ══ coverage under an overlay (acceptance B7) ═════════════════════════════
   B7 states coverage "permanently and visibly", and the status bar is where it lives. An overlay
   can take it off the screen: MEASURED 2026-09-25 (390/320/768/1440/1920 px, both themes), with
   the palette or the keyboard reference open `elementFromPoint` over every figure returned the
   dialog's scrim or footer at EVERY width, and at 390/320 a priority-queue popover sat over the
   whole group. So every surface built on Dialog or Popover states the figures itself, read from
   the owner of the permanent line — never a copy of the numbers. It is rendered by the primitives,
   not by their consumers, so an overlay added tomorrow carries it without anyone remembering to. */

let figuresOnce: readonly string[] | null = null;

/**
 * The coverage figures an overlay states, as segments of the owner's line (`T8_coverageLine`,
 * core/claims.ts). A RIB count without its completeness qualifier reads as that many WHOLE tables,
 * so the qualifier from forwarding/rib-completeness.ts rides on the RIB segment exactly as it does
 * on the status bar — and if the owner's line ever stops carrying a RIB segment, the qualifier is
 * appended as its own segment rather than silently dropped.
 */
export function coverageFigures(): readonly string[] {
  /* Read once. `fabric` is a static import, so there is nothing for the figures to go stale
     against, and opening an overlay must not read the dataset: the palette's open is a visibility
     toggle over an index that already exists (E3/J5; CommandPalette.test.tsx "opens over an index
     that already exists" counts the reads, and reading the line per open was 2 of them). */
  if (figuresOnce !== null) return figuresOnce;
  figuresOnce = withRibQualifier(T8_coverageLine().split(" · "), ribCountQualifier());
  return figuresOnce;
}

/** The RIB segment carries the qualifier; with no RIB segment the qualifier is its own. Pure. */
export function withRibQualifier(parts: readonly string[], qualifier: string): string[] {
  if (qualifier === "") return [...parts];
  let placed = false;
  const out = parts.map((p) => {
    if (placed || !p.startsWith("RIBs ")) return p;
    placed = true;
    return `${p} ${qualifier}`;
  });
  return placed ? out : [...out, `RIBs ${qualifier}`];
}

/**
 * The coverage line an overlay carries. Prose, never a control: it adds no tab stop to a focus
 * trap (D1/D3), and it is not a live region — a dialog's content is read when the dialog is.
 * Styled in src/ui/primitives.css (`.ui-overlay-cov`), with the primitives that render it.
 */
export function CoverageStatement(): ReactElement {
  const figures = coverageFigures();
  return (
    <p className="ui-overlay-cov" data-overlay-coverage="">
      <span className="ui-overlay-cov__key">coverage</span>{" "}
      {figures.map((f, i) => (
        <span key={f}>
          <span className="ui-overlay-cov__fig">{f}</span>
          {i === figures.length - 1 ? null : (
            <span className="ui-overlay-cov__dot" aria-hidden="true">
              {" · "}
            </span>
          )}
        </span>
      ))}
    </p>
  );
}

/**
 * A non-modal popover: the page behind stays live and readable, which is the whole point of a
 * continuous investigation surface. Escape and an outside click close it and return focus to the
 * trigger. Use Dialog when the user genuinely must deal with the thing before continuing.
 */
export function Popover({
  label,
  trigger,
  children,
  open: controlled,
  onOpenChange,
  align = "start",
}: {
  label: string;
  trigger: ReactElement<Partial<TriggerLike>>;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  align?: "start" | "end";
}): ReactElement {
  const id = useId();
  const [uncontrolled, setUncontrolled] = useState(false);
  const open = controlled ?? uncontrolled;
  const anchorRef = useRef<HTMLSpanElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<Rect>({ top: 0, left: 0, bottom: 0, width: 0 });

  const setOpen = useCallback(
    (next: boolean) => {
      if (controlled === undefined) setUncontrolled(next);
      onOpenChange?.(next);
    },
    [controlled, onOpenChange],
  );

  useEffect(() => {
    if (!open) return;
    setRect(rectOf(anchorRef.current?.firstElementChild as HTMLElement | null));
    const owns = (t: EventTarget | null): boolean =>
      t instanceof Node && (panelRef.current?.contains(t) === true || anchorRef.current?.contains(t) === true);
    /* CAPTURE phase. In the bubble phase any component under focus that handles Escape itself and
       stops propagation (a grid, the query input) swallowed it, and the popover stayed open over
       the content (A11Y critic 2026-09-21, D3). Focus returns to the trigger only when it was
       still inside the popover or on the trigger — never pulled back from somewhere else. */
    const onKey = (e: KeyboardEvent): void => {
      /* The panel is portalled to the end of <body>, so its DOM position is not its reading
         position. MEASURED (A11Y critic, D3): Tab past the last checkbox of "More display options"
         went to <body> and then to "Skip to the fabric" at the top of the page, dialog still open.
         Tab order is restored to where the panel sits VISUALLY — straight after its trigger:
         Tab off the last control closes the panel and continues with the next tab stop after the
         trigger; Shift+Tab off the first control goes back to the trigger. */
      if (e.key === "Tab" && !e.altKey && !e.ctrlKey && !e.metaKey) {
        const panel = panelRef.current;
        const triggerNode = anchorRef.current?.firstElementChild as HTMLElement | null;
        if (panel === null || triggerNode === null || !panel.contains(document.activeElement)) return;
        const inside = focusablesIn(panel).filter((el) => el.tabIndex >= 0);
        const first = inside[0];
        const last = inside[inside.length - 1];
        if (e.shiftKey) {
          if (first !== undefined && document.activeElement !== first) return;
          e.preventDefault();
          triggerNode.focus();
          return;
        }
        if (last !== undefined && document.activeElement !== last) return;
        const order = focusablesIn(document.body).filter(
          (el) => el.tabIndex >= 0 && !panel.contains(el) && el.getClientRects().length > 0,
        );
        const next = order.find(
          (el) => el !== triggerNode && (triggerNode.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0 && !triggerNode.contains(el),
        );
        e.preventDefault();
        setOpen(false);
        (next ?? triggerNode).focus();
        return;
      }
      if (e.key !== "Escape") return;
      e.stopPropagation();
      const hadFocus = owns(document.activeElement);
      setOpen(false);
      if (hadFocus) (anchorRef.current?.firstElementChild as HTMLElement | null)?.focus();
    };
    const onDown = (e: MouseEvent): void => {
      if (owns(e.target)) return;
      setOpen(false);
    };
    /* A non-modal popover closes when focus leaves it (trigger + panel), as a disclosure does:
       left open behind the user's Tab it sat over the content with nothing on screen tied to it. */
    const onFocusIn = (e: FocusEvent): void => {
      if (owns(e.target)) return;
      setOpen(false);
    };
    /* The panel is placed from the trigger's rect, which a viewport resize moves. MEASURED (D3 rung
       crossing, 768 -> 390): kept at its open-time coordinates, "More"'s panel sat wholly off screen with
       focus inside it. Re-measure once per frame while it is open. */
    let frame = 0;
    const onResize = (): void => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setRect(rectOf(anchorRef.current?.firstElementChild as HTMLElement | null)));
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("focusin", onFocusIn);
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("focusin", onFocusIn);
      window.removeEventListener("resize", onResize);
    };
  }, [open, setOpen]);

  /* Focus moves INTO the panel as it opens — onto its first control, or, when it holds only text
     (an explanation toggle), onto the panel itself, so the dialog's name and its content are
     announced. MEASURED before (A11Y critic, D3): "Why the two tables are counted separately"
     opened a role=dialog while focus stayed on the trigger with no aria-controls, so a screen
     reader heard "expanded" and nothing of what had opened. Escape / Tab still return exactly as
     for a panel with controls (the key handler treats the panel as inside). */
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    (focusablesIn(panel)[0] ?? panel)?.focus({ preventScroll: true });
  }, [open]);

  /* An end-aligned panel is pulled left of its trigger by its own width, which the anchor rect
     cannot know; a trigger near the left edge put the panel's first characters off-screen
     (measured: left -6.7 px on "More display options"). Nudge it back inside an 8 px gutter.
     The RIGHT edge is the mirror case: a start-aligned panel under a trigger near the right edge
     ran past the screen (measured 2026-09-25: the queue's "What the collection gap means" panel
     reached x 908 in a 768 px viewport, cutting off its text and its coverage line). It is pulled
     back left by its overflow — but never so far that its START leaves the screen, because a
     panel wider than the viewport is read from its first character. */
  /* And the BOTTOM edge: the height cap below keeps a 160 px floor so a panel stays usable, which
     is more than the room left under a trigger low on a short screen. MEASURED 2026-09-25 at
     320x568: trigger at y 420-436, panel run to y 600 — over the status bar's coverage group, its
     own coverage line (B7) cut off by the screen edge. A panel that does not fit below opens ABOVE
     the trigger when there is more room there, and is otherwise capped to the room below; either
     way it ends inside the viewport, so its last line (the coverage statement) is on screen. */
  useEffect(() => {
    const panel = panelRef.current;
    if (!open || panel === null) return;
    place(panel);
    /* THE COVERAGE LINE NEVER COVERS THE FOCUSED CONTROL. MEASURED (phase 3.5 repair, D3 rung crossing, release
       build, 1920x800): with the queue's "Display" panel open, "Narrow the Category column" focused sat at y
       763-787 under the sticky coverage line (y 744-787) — focus scrolls a control into the panel's scrollport,
       and the line covers that scrollport's bottom. The panel states the line's height (`--pop-cov-h`, read by
       `.ui-popover`'s bottom scroll padding in primitives.css, which focus scrolling and scrollIntoView honour),
       and every re-placement brings the focused control clear of it. */
    const cov = panel.querySelector<HTMLElement>(".ui-overlay-cov");
    panel.style.setProperty("--pop-cov-h", `${cov?.offsetHeight ?? 0}px`);
    const a = document.activeElement;
    if (a instanceof HTMLElement && a !== panel && panel.contains(a)) a.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [open, rect]);

  /** Place the panel inside the viewport (the effect above runs it on open and on every re-measure). */
  function place(panel: HTMLDivElement): void {
    panel.style.marginLeft = "";
    panel.style.top = "";
    panel.style.maxHeight = "";
    const box = panel.getBoundingClientRect();
    const GUTTER = 8;
    const viewport = document.documentElement.clientWidth || window.innerWidth;
    let shift = 0;
    if (box.right > viewport - GUTTER) shift = viewport - GUTTER - box.right;
    if (box.left + shift < GUTTER) shift = GUTTER - box.left;
    if (shift !== 0) panel.style.marginLeft = `${shift > 0 ? Math.ceil(shift) : Math.floor(shift)}px`;

    const viewportH = document.documentElement.clientHeight || window.innerHeight;
    const marginTop = Number.parseFloat(getComputedStyle(panel).marginTop) || 0;
    /* A TRIGGER OUTSIDE THE VIEWPORT (MEASURED, phase 3.5, the D3 rung crossing: the queue's "Display" panel
       open at 390x900, resized to 768 — the page's scroll reset and the trigger re-measured at y 1037, below a
       900 px viewport; the panel "opened above" it with a 1020 px cap, ran to y 1032, and the focused control
       had no part on screen). The panel is anchored at the viewport edge the trigger left by: brought down to
       the gutter when the trigger is above the viewport, measured from the bottom gutter when it is below. */
    let panelTop = box.top;
    if (panelTop < GUTTER) {
      panel.style.top = `${GUTTER - marginTop}px`;
      panelTop = GUTTER;
    }
    if (panelTop + box.height <= viewportH - GUTTER) return;
    const below = Math.floor(viewportH - GUTTER - panelTop);
    const anchorTop = Math.min(rect.top, viewportH - GUTTER);
    const above = Math.floor(anchorTop - GUTTER - marginTop * 2);
    if (above > below) {
      /* The height it WANTS, not the height the floor-capped layout gave it. */
      const natural = Math.max(box.height, panel.scrollHeight + (box.height - panel.clientHeight));
      const h = Math.min(natural, above);
      panel.style.maxHeight = `${above}px`;
      panel.style.top = `${Math.max(GUTTER - marginTop, Math.floor(anchorTop - marginTop * 2 - h))}px`;
    } else {
      panel.style.maxHeight = `${Math.max(0, below)}px`;
    }
  }

  const p = trigger.props;
  const triggerEl = cloneElement(trigger, {
    "aria-expanded": open,
    "aria-haspopup": "dialog",
    ...(open ? { "aria-controls": id } : {}),
    onClick: (e) => {
      p.onClick?.(e);
      setOpen(!open);
    },
  } satisfies Partial<TriggerLike>);

  return (
    <span className="ui-pop-anchor" ref={anchorRef}>
      {triggerEl}
      {open ? (
        <Portal>
          <div
            ref={panelRef}
            role="dialog"
            aria-label={label}
            aria-modal="false"
            id={id}
            tabIndex={-1}
            className="ui-popover"
            data-align={align}
            style={
              {
                "--pop-top": `${rect.bottom}px`,
                "--pop-left": `${align === "start" ? rect.left : rect.left + rect.width}px`,
                /* Never past the bottom of the viewport: a panel opened low on the page kept its
                   70vh cap and hung off-screen, its last controls unreachable by pointer. */
                ...(typeof window === "undefined"
                  ? {}
                  : { "--pop-maxh": `${Math.max(160, Math.round(window.innerHeight - rect.bottom - 16))}px` }),
              } as CSSProperties
            }
          >
            {children}
            <CoverageStatement />
          </div>
        </Portal>
      ) : null}
    </span>
  );
}

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Where focus lands on open. Defaults to the first focusable element in the dialog. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** The command palette wants the full width; a confirmation does not. */
  width?: "sm" | "md" | "lg";
  className?: string;
  /**
   * While CLOSED, render the frame anyway — inert and hidden from assistive technology — so the
   * browser styles, lays out and RASTERISES it before the real first open. See `DialogFrame`.
   * `"raster"`: drawn at an opacity below one colour step, so it is really rasterised. `"parked"`:
   * also `visibility: hidden` — kept in the document, painting nothing, so the real open only flips
   * attributes on nodes that already exist. Ignored while `open`: an open dialog is always the
   * ordinary, exposed one.
   */
  prewarm?: DialogPrewarm;
}

/** How a CLOSED dialog's frame is pre-rendered, if at all (see `DialogFrame`). */
export type DialogPrewarm = false | "raster" | "parked";

/**
 * How a pre-warm frame is drawn. NOT opacity 0: a layer at zero opacity is never rasterised, so
 * the GPU never compiles the programs the first real open will need (measured, cold first Ctrl+K
 * at 1280x800: p95 152 ms at opacity 0 against 64 ms at 0.001). 0.001 is below one 8-bit colour
 * step, so nothing is seen; pointer-events none so nothing is hit.
 */
const RASTER_STYLE: CSSProperties = { opacity: 0.001, pointerEvents: "none" };
/**
 * A parked frame paints nothing (`visibility: hidden` — which also removes it from the
 * accessibility tree a second time over) but keeps its boxes, so the first real open is an
 * attribute flip on laid-out nodes, not a mount: no DOM to create, no first layout to force.
 */
const PARKED_STYLE: CSSProperties = { ...RASTER_STYLE, visibility: "hidden" };
const prewarmAttrs = (mode: "raster" | "parked") =>
  ({
    "aria-hidden": true,
    inert: true,
    "data-dialog-prewarm": mode,
    style: mode === "parked" ? PARKED_STYLE : RASTER_STYLE,
  }) as const;

export interface DialogFrameProps {
  /** The `useId()` the title and description ids derive from. */
  id: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width: "sm" | "md" | "lg";
  className?: string | undefined;
  onClose: () => void;
  /** A mode: the invisible, inert, unexposed pre-warm rendering. False: the real dialog. */
  prewarm: DialogPrewarm;
  panelRef?: RefObject<HTMLDivElement | null>;
  scrimRef?: RefObject<HTMLDivElement | null>;
}

/**
 * A dialog's PRESENTATION: the scrim, the panel and its head, body, foot and coverage statement.
 * No behaviour — focus, the key trap and the inert page belong to `Dialog`.
 *
 * WHY IT IS SPLIT OUT (acceptance E2/E3, the first Ctrl+K after load, 2026-09-26). A closed Dialog
 * renders nothing, so the first open built the palette's DOM inside the keydown and then paid, for
 * the first time, the style and layout of that subtree (forced by `focus()`) and the GPU's first
 * compile of the programs its paint needs: p95 320 ms and a 51-83 ms keydown task, against a warm
 * p95 of 64. The same markup rendered beforehand, with `prewarm`, pays those first-time costs off
 * the interaction's path: `"raster"` while the GPU draws it once, then `"parked"` (painting nothing)
 * until the real open turns those very nodes into the dialog. What a pre-warm frame must not be is
 * ANYTHING a user or assistive
 * technology can meet: it is `aria-hidden` and `inert` on both the scrim and the panel, it takes no
 * pointer, it carries no `role="dialog"`/`aria-modal` (so no harness, audit or AT query mistakes it
 * for an open dialog), and the scrim has no close handler. Only the frame's own content is inside
 * it; the consumer decides what that content exposes while pre-warming.
 */
export function DialogFrame({
  id,
  title,
  description,
  children,
  footer,
  width,
  className,
  onClose,
  prewarm,
  panelRef,
  scrimRef,
}: DialogFrameProps): ReactNode {
  return (
    <Portal>
      <div ref={scrimRef} className="ui-dialog__scrim" {...(prewarm ? prewarmAttrs(prewarm) : { onMouseDown: onClose })} />
      <div
        ref={panelRef}
        {...(prewarm
          ? prewarmAttrs(prewarm)
          : {
              role: "dialog",
              "aria-modal": "true" as const,
              "aria-labelledby": `${id}-title`,
              ...(description ? { "aria-describedby": `${id}-desc` } : {}),
              tabIndex: -1,
            })}
        data-width={width}
        className={cx("ui-dialog", className)}
      >
        <div className="ui-dialog__head">
          <h2 className="ui-dialog__title" id={`${id}-title`}>
            {title}
          </h2>
          <IconButton label="Close dialog" icon={<IconClose />} onClick={onClose} size="sm" />
        </div>
        {description ? (
          <p className="ui-dialog__desc" id={`${id}-desc`}>
            {description}
          </p>
        ) : null}
        <div className="ui-dialog__body">{children}</div>
        {footer ? <div className="ui-dialog__foot">{footer}</div> : null}
        <CoverageStatement />
      </div>
    </Portal>
  );
}

const LIVE_REGION = "[aria-live], [role=\"status\"], [role=\"alert\"], [role=\"log\"]";
/** A dialog frame drawn or parked before its first open (`prewarmAttrs`): its inert is the dialog's own. */
const DIALOG_PREWARM = "[data-dialog-prewarm]";

/**
 * Make everything outside `keep` inert, EXCEPT live regions. Returns the undo. `aria-modal` alone
 * is not honoured by every screen reader: a virtual cursor could walk out of the dialog into the
 * page behind it (acceptance D3). Whole subtrees are made inert where they hold no live region;
 * a subtree that does hold one is descended into so the announcement channel (`#sr-status`)
 * keeps speaking while a dialog is open — the palette reports what a command did through it.
 * Only elements this call made inert are released, so a pre-existing `inert` survives.
 */
export function inertOutside(keep: readonly Element[]): () => void {
  if (typeof document === "undefined") return () => {};
  const made: HTMLElement[] = [];
  const visit = (el: Element): void => {
    if (keep.some((k) => k === el || el.contains(k) || k.contains(el))) {
      // An ancestor of the dialog: descend so its other branches are still covered.
      if (keep.some((k) => el !== k && el.contains(k))) for (const c of Array.from(el.children)) visit(c);
      return;
    }
    if (el.matches(LIVE_REGION)) return;
    if (el.hasAttribute("inert")) {
      /* A dialog's own pre-warm frame: its inert is the dialog's, lifted when it opens. Never descended
         into -- marking its children one by one left them inert inside the open dialog. (A dialog layer
         underneath another is an open dialog's node, so it is kept above and never reaches here.) */
      if (el.matches(DIALOG_PREWARM)) return;
      /* Anyone else's inert (a hidden rail, made inert by useReleaseFocusOnHide) can be LIFTED while this
         cover is held: the rail shown with a modal still open. Its own attribute is not ours to hold or
         release, so its children are covered instead -- a live region among them still speaks -- and
         showing it exposes nothing behind the modal (verifier R6 VR2-1). */
      for (const c of Array.from(el.children)) visit(c);
      return;
    }
    if (el.querySelector(LIVE_REGION) !== null) {
      for (const c of Array.from(el.children)) visit(c);
      return;
    }
    // The ATTRIBUTE, not the `inert` property: the property reflects it in browsers, but an
    // environment without the property (jsdom) would take an expando and prove nothing.
    if (el instanceof HTMLElement && el.tagName !== "SCRIPT") {
      /* An inert ancestor drops the focus it holds to <body> with no code of ours running (this can land
         while focus is still here: a dialog that has not taken focus yet). Release it first, into the
         dialog on top (the last kept node is its panel); a no-op when focus is elsewhere. */
      releaseFocusFrom(el, null, keep.filter((k): k is HTMLElement => k instanceof HTMLElement).reverse());
      el.setAttribute("inert", "");
      made.push(el);
    }
  };
  for (const c of Array.from(document.body.children)) visit(c);
  return () => {
    for (const el of made) el.removeAttribute("inert");
  };
}

/* ══ the dialog stack (acceptance D1/D3, WCAG 2.4.11) ════════════════════════
   More than one modal can be open: the palette's mod+k is deliberately live behind a modal
   (keyboard.ts `eligible`), so Ctrl+K from the keyboard reference opens the palette OVER it. Which
   one the user sees used to be an accident. Both dialogs sat at `--z-dialog`, so paint order was
   DOM order — and the palette's frame is parked in <body> before its first open (DialogFrame), so it
   came EARLIER than a keyboard reference opened later and was drawn beneath it, focus inside it, out
   of sight (verifier round 2, E2/E3, 2026-09-27: probe screenshots, bodyIndex 2 vs 4). Each dialog
   also held its own document key listener, so one Escape could reach both, and a dialog's page-wide
   `inert`, deferred to after the first paint, could land AFTER a later dialog opened and cover it.

   One owner decides all of it, from the order dialogs were OPENED — never from the order they were
   mounted, parked or pre-warmed in:
     - the top layer is the dialog opened most recently; its scrim and panel carry `--dialog-layer`
       (and `data-dialog-layer`) = its depth, and primitives.css derives both z-indexes from it;
     - every open dialog under it is `inert` (made so here, released here when it is on top again);
     - one capture-phase key listener hands keys to the top layer ONLY (Escape, the Tab trap);
     - the page-wide inert keeps every open dialog, whichever dialog's deferred inert lands first, and
       a close passes it to the dialog still open (it is released only with the last one); a dialog
       closing from under another does not pull focus out of it. */

interface DialogLayer {
  /** The scrim and panel, captured at open (a pre-warmed frame's nodes ARE the ones that open). */
  readonly nodes: readonly HTMLElement[];
  /** The dialog's key handling (Escape, the Tab trap). Only the top layer's is called. */
  onKey: (e: KeyboardEvent) => void;
  /** The nodes the stack made inert while this layer was underneath another; null when on top. */
  underneath: HTMLElement[] | null;
  /** Undo of this dialog's page-wide inert (`inertOutside`), once it has been applied. */
  page: (() => void) | null;
  /** Set as it leaves the stack: whether it was the top layer then. */
  leftAsTop: boolean;
}

const dialogStack: DialogLayer[] = [];
const LAYER_PROP = "--dialog-layer";
const LAYER_ATTR = "data-dialog-layer";

function onTopLayerKey(e: KeyboardEvent): void {
  dialogStack[dialogStack.length - 1]?.onKey(e);
}

/** The nodes of every open dialog: what the page-wide inert never touches. A layer underneath is made
    inert by `restack`, as a whole; the page-wide inert must not also hold its descendants, or it could
    not pass to the new top without leaving that dialog's insides inert (verifier R6 round 1, V3). */
function stackNodes(): HTMLElement[] {
  return dialogStack.flatMap((l) => [...l.nodes]);
}

/** Give every layer its depth, make everything under the top inert, and the top live. */
function restack(): void {
  const top = dialogStack.length - 1;
  dialogStack.forEach((layer, i) => {
    for (const el of layer.nodes) {
      el.style.setProperty(LAYER_PROP, String(i));
      el.setAttribute(LAYER_ATTR, String(i));
    }
    if (i < top) {
      if (layer.underneath === null) {
        layer.underneath = layer.nodes.filter((el) => !el.hasAttribute("inert"));
        /* Ctrl+K from inside the keyboard reference: focus can still be in the layer going under. Hand it
           to the new top's panel before the layer turns inert (a no-op when focus is elsewhere). */
        const topNodes = [...(dialogStack[top]?.nodes ?? [])].reverse();
        for (const el of layer.underneath) {
          releaseFocusFrom(el, null, topNodes);
          el.setAttribute("inert", "");
        }
      }
    } else if (layer.underneath !== null) {
      for (const el of layer.underneath) el.removeAttribute("inert");
      layer.underneath = null;
    }
  });
}

function releasePage(layer: DialogLayer): void {
  const undo = layer.page;
  layer.page = null;
  undo?.();
}

function pushLayer(layer: DialogLayer): void {
  if (dialogStack.length === 0 && typeof document !== "undefined") document.addEventListener("keydown", onTopLayerKey, true);
  dialogStack.push(layer);
  restack();
}

function removeLayer(layer: DialogLayer): void {
  const at = dialogStack.indexOf(layer);
  if (at < 0) return;
  layer.leftAsTop = at === dialogStack.length - 1;
  dialogStack.splice(at, 1);
  if (layer.underneath !== null) for (const el of layer.underneath) el.removeAttribute("inert");
  layer.underneath = null;
  for (const el of layer.nodes) {
    el.style.removeProperty(LAYER_PROP);
    el.removeAttribute(LAYER_ATTR);
  }
  /* The page-wide inert is the STACK's while any dialog is open, whichever layer's deferred inert
     happened to land first (verifier R6 round 1, V3: the upper one's could land before the lower
     one's, which then found the page already inert and held nothing, so closing the upper one left
     the dialog still open over a live page). A departing layer's cover therefore passes to the new
     top — the same elements, never released and re-applied, so a close costs no page-wide restyle —
     and is released only when the last dialog leaves, here, before any focus is restored (an inert
     element refuses focus). The cover never holds a dialog's nodes or anything inside them: it keeps
     every open dialog (stackNodes) and never descends into a subtree that is already inert (a layer
     underneath, a pre-warm frame), so passing it on leaves the new top wholly live and a pre-warm
     frame's own inert alone. */
  const top = dialogStack[dialogStack.length - 1];
  const cover = layer.page;
  layer.page = null;
  if (top === undefined || cover === null) cover?.();
  else {
    const held = top.page;
    top.page =
      held === null
        ? cover
        : () => {
            held();
            cover();
          };
  }
  restack();
  if (dialogStack.length === 0 && typeof document !== "undefined") document.removeEventListener("keydown", onTopLayerKey, true);
}

/**
 * A modal dialog: focus is trapped while it is open, Escape closes it, and focus returns to
 * whatever invoked it (WCAG 2.4.3 / 2.1.2, acceptance D3). The page behind is made `inert`
 * (see `inertOutside`) so assistive technology that ignores `aria-modal` cannot wander into it;
 * live regions are exempt so announcements still reach the user.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  initialFocus,
  width = "md",
  className,
  prewarm = false,
}: DialogProps): ReactNode {
  const id = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const scrimRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<DialogLayer | null>(null);

  /* On the dialog stack from the commit that opens it, before it is painted: its layer, and the
     inert of every dialog under it, are in place in the same frame as the dialog itself. */
  useLayoutEffect(() => {
    if (!open) return;
    const layer: DialogLayer = {
      nodes: [scrimRef.current, panelRef.current].filter((el): el is HTMLDivElement => el !== null),
      onKey: () => {},
      underneath: null,
      page: null,
      leftAsTop: false,
    };
    layerRef.current = layer;
    /* The opener is read HERE, before the stack moves anything: pushing this layer makes the dialog under
       it inert, and releases focus out of it first (into this dialog), so a later read would record this
       dialog's own panel as the place to return to. */
    returnTo.current = document.activeElement as HTMLElement | null;
    pushLayer(layer);
    return () => removeLayer(layer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const layer = layerRef.current;
    const target = initialFocus?.current ?? focusablesIn(panelRef.current)[0] ?? panelRef.current;
    target?.focus();
    /* INERT AFTER THE FIRST PAINT (perf audit E3, J5 "open the palette", 2026-09-22; design brief
       §7 row 5 — "opening is a visibility toggle" — and "no task on the main thread exceeds 50 ms").
       `inert` on the page behind invalidates the style of the whole application (~4,200 elements),
       and applied here, inside the keydown that opened the dialog, that restyle was forced by the
       next layout read in the same task. MEASURED (release build, headed, prototype-wrapped timers):
       the palette's scrollIntoView took 30-116 ms right after inert was set, and the Ctrl+K keydown
       ran a 54-130 ms animation frame on 20 of 20 opens, 82 ms of it forced style and layout.
       Reordering (inert, then focus) only moved the same restyle into focus() — measured, no gain.
       So the page is made inert on the first task AFTER the dialog has been presented: the restyle
       still happens, once, but off the interaction's path to its next paint.
       What that one frame leaves open, and why it is safe: focus is already inside the dialog (set
       above, synchronously), `aria-modal` is on the panel from its first render, Tab is trapped by
       the keydown handler below, and the scrim takes every pointer. A close before the inert lands
       cancels it, so nothing is ever left inert. Without requestAnimationFrame (no rendering) there
       is no paint to wait for and the page is made inert at once; and because rAF does not run in a
       window that is not presenting (measured: a minimised or occluded window), a 100 ms fallback
       timer bounds the gap whether or not a frame is ever drawn. */
    /* The page-wide inert leaves every open dialog to the stack: deferred, it can land after a later
       dialog opened over this one, or before the one under it (see the dialog stack). */
    const applyInert = (): void => {
      if (layer === null || layer.page !== null || !dialogStack.includes(layer)) return;
      layer.page = inertOutside(stackNodes());
    };
    let raf: number | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let fallback: ReturnType<typeof setTimeout> | null = null;
    if (typeof requestAnimationFrame === "function") {
      fallback = setTimeout(() => {
        fallback = null;
        applyInert();
      }, 100);
      /* rAF runs before the frame's style and paint; the timeout after it runs once that frame is done. */
      raf = requestAnimationFrame(() => {
        raf = null;
        timer = setTimeout(() => {
          timer = null;
          applyInert();
        }, 0);
      });
    } else {
      applyInert();
    }
    return () => {
      if (raf !== null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(raf);
      if (timer !== null) clearTimeout(timer);
      if (fallback !== null) clearTimeout(fallback);
      /* Release BEFORE restoring focus: an inert element refuses focus. (On a close the stack has
         already released it, in the layout phase; this covers a re-run while still open.) */
      if (layer !== null) releasePage(layer);
      /* Restore on close AND on unmount: a dialog whose parent is removed while it is open would
         otherwise leave focus on <body>, which silently resets keyboard navigation to the top.
         Not when it closed from UNDER another dialog: focus is in the one still open, on top. */
      const onTop = layer === null || (dialogStack.includes(layer) ? dialogStack[dialogStack.length - 1] === layer : layer.leftAsTop);
      if (onTop) returnFocus(returnTo.current, null);
    };
  }, [open, initialFocus]);

  useEffect(() => {
    const layer = layerRef.current;
    if (!open || layer === null) return;
    /* Handed keys by the dialog stack's one listener, and only while this dialog is the top layer:
       one Escape closes one dialog, and Tab never wraps into a dialog underneath. */
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusablesIn(panelRef.current);
      if (items.length === 0) {
        e.preventDefault();
        panelRef.current?.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panelRef.current?.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    layer.onKey = onKey;
    return () => {
      if (layer.onKey === onKey) layer.onKey = () => {};
    };
  }, [open, onClose]);

  if (!open && !prewarm) return null;

  /* The same element tree open, rasterising or parked, so a pre-warm frame that is mounted when the
     real open arrives is UPDATED into the real dialog (its attributes flip) rather than replaced —
     the same DOM nodes, already styled and laid out — and the behaviour effects above, keyed on
     `open` alone, never run for a pre-warm. */
  return (
    <DialogFrame
      id={id}
      title={title}
      description={description}
      footer={footer}
      width={width}
      className={className}
      onClose={onClose}
      prewarm={open ? false : prewarm}
      panelRef={panelRef}
      scrimRef={scrimRef}
    >
      {children}
    </DialogFrame>
  );
}

/* ══ toolbar (APG) ═════════════════════════════════════════════════════════ */

/**
 * An APG toolbar: the whole group is ONE tab stop and arrows move between its controls. Without
 * this, a nine-button toolbar costs nine Tab presses to walk past, which is what makes a dense
 * tool exhausting to drive from the keyboard.
 *
 * Children need no extra props — every focusable descendant participates. Opt one out with
 * `data-toolbar-skip`.
 */
export function Toolbar({
  label,
  orientation = "horizontal",
  children,
  className,
}: {
  label: string;
  orientation?: "horizontal" | "vertical";
  children: ReactNode;
  className?: string;
}): ReactElement {
  const ref = useRef<HTMLDivElement>(null);

  const items = useCallback(
    (): HTMLElement[] =>
      focusablesIn(ref.current).filter((el) => !el.hasAttribute("data-toolbar-skip")),
    [],
  );

  /* No dependency array on purpose: children can change on any render (a filter appears, a chip
     is removed) and the roving tabindex must follow them. The body is a handful of attribute
     writes over a handful of nodes. */
  useEffect(() => {
    const list = items();
    if (list.length === 0) return;
    const active = document.activeElement as HTMLElement | null;
    const current = list.findIndex((el) => el === active);
    const keep = current === -1 ? 0 : current;
    list.forEach((el, i) => {
      el.tabIndex = i === keep ? 0 : -1;
    });
  });

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    const horizontal = orientation === "horizontal";
    const next = horizontal ? "ArrowRight" : "ArrowDown";
    const prev = horizontal ? "ArrowLeft" : "ArrowUp";
    const list = items();
    if (list.length === 0) return;
    const at = list.findIndex((el) => el === document.activeElement);
    const go = (i: number): void => {
      const el = list[(i + list.length) % list.length];
      if (!el) return;
      list.forEach((o) => {
        o.tabIndex = o === el ? 0 : -1;
      });
      el.focus();
    };
    if (e.key === next) {
      e.preventDefault();
      go(at + 1);
    } else if (e.key === prev) {
      e.preventDefault();
      go(at - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      go(0);
    } else if (e.key === "End") {
      e.preventDefault();
      go(list.length - 1);
    }
  };

  return (
    <div
      ref={ref}
      role="toolbar"
      aria-label={label}
      aria-orientation={orientation}
      className={cx("ui-toolbar", className)}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>
  );
}

/* ══ quantities ════════════════════════════════════════════════════════════ */

export type Tone = "neutral" | "accent" | "up" | "down" | "unknown" | "critical" | "high";

/**
 * A labelled quantity with a bar. `null` renders as not-observed: a meter at zero and a meter we
 * never read look identical unless we say so, and that is the exact failure this app exists to
 * avoid.
 */
export function Meter({
  label,
  value,
  max = 100,
  min = 0,
  unit,
  tone = "neutral",
  format,
}: {
  label: string;
  value: number | null | undefined;
  max?: number;
  min?: number;
  unit?: string;
  tone?: Tone;
  format?: (v: number) => string;
}): ReactElement {
  const id = useId();
  if (!isObserved(value)) {
    return (
      <div className="ui-meter" data-unobserved="true">
        <span className="ui-meter__label" id={id}>
          {label}
        </span>
        <NotObserved what={label} compact />
      </div>
    );
  }
  const v = value as number;
  const clamped = Math.min(Math.max(v, min), max);
  const pct = max === min ? 0 : ((clamped - min) / (max - min)) * 100;
  const text = `${format ? format(v) : String(v)}${unit ? ` ${unit}` : ""}`;
  return (
    <div className="ui-meter" data-tone={tone}>
      <span className="ui-meter__label" id={id}>
        {label}
      </span>
      <span
        className="ui-meter__track"
        role="meter"
        aria-labelledby={id}
        aria-valuenow={v}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuetext={text}
      >
        <span className="ui-meter__fill" style={{ inlineSize: `${pct}%` }} />
      </span>
      <span className="ui-meter__value">{text}</span>
    </div>
  );
}

/**
 * A bare proportion bar for use inside a row that already states the number in text. It is
 * aria-hidden by design: announcing the same figure twice makes a dense table unusable with a
 * screen reader.
 */
export function Bar({
  value,
  max,
  tone = "neutral",
}: {
  value: number;
  max: number;
  tone?: Tone;
}): ReactElement {
  const pct = max <= 0 ? 0 : Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <span className="ui-bar" data-tone={tone} aria-hidden="true">
      <span className="ui-bar__fill" style={{ inlineSize: `${pct}%` }} />
    </span>
  );
}

/**
 * An inline sparkline, hand-rolled SVG, no library.
 *
 * A `null` sample is a GAP plus a tick on the baseline — never interpolated across and never
 * drawn as zero. Interpolating over a missing sample invents a measurement, which is the same
 * defect as a blank cell reading as healthy, just harder to spot.
 */
export function Sparkline({
  values,
  label,
  width = 64,
  height = 16,
}: {
  values: readonly (number | null)[];
  label: string;
  width?: number;
  height?: number;
}): ReactElement {
  const observed = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (observed.length === 0) {
    return <NotObserved what={label} compact />;
  }
  const lo = Math.min(...observed);
  const hi = Math.max(...observed);
  const span = hi - lo;
  const pad = 1.5;
  const n = values.length;
  const x = (i: number): number => (n <= 1 ? width / 2 : (i / (n - 1)) * (width - 2 * pad) + pad);
  const y = (v: number): number =>
    span === 0 ? height / 2 : height - pad - ((v - lo) / span) * (height - 2 * pad);

  const segments: string[] = [];
  let run: string[] = [];
  const gaps: number[] = [];
  values.forEach((v, i) => {
    if (typeof v === "number" && Number.isFinite(v)) {
      run.push(`${x(i).toFixed(2)},${y(v).toFixed(2)}`);
    } else {
      gaps.push(x(i));
      if (run.length > 0) segments.push(run.join(" "));
      run = [];
    }
  });
  if (run.length > 0) segments.push(run.join(" "));

  const missing = values.length - observed.length;
  const summary = `${label}: ${observed.length} of ${values.length} samples observed, low ${lo}, high ${hi}${
    missing > 0 ? `, ${missing} not observed` : ""
  }`;

  return (
    <svg
      className="ui-spark"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={summary}
    >
      {gaps.map((gx) => (
        <line
          key={`gap-${gx}`}
          className="ui-spark__gap"
          x1={gx}
          x2={gx}
          y1={height - pad}
          y2={height - pad - 3}
        />
      ))}
      {segments.map((pts) => (
        <polyline key={pts.slice(0, 24)} className="ui-spark__line" points={pts} />
      ))}
    </svg>
  );
}

/* ══ misc ══════════════════════════════════════════════════════════════════ */

/**
 * Copy a value, with the outcome announced in a live region rather than as a disappearing toast.
 * Failure is reported, not swallowed: a clipboard write can be refused by permissions or absent
 * entirely, and a copy button that silently does nothing is worse than one that says so.
 */
export function Copyable({
  value,
  label,
  mono = true,
  digest = false,
}: {
  value: string;
  /** What is being copied, for the button's accessible name, e.g. "snapshot sha256". */
  label: string;
  mono?: boolean;
  /**
   * The value is a DIGEST (a sha256): one token with no boundary to break at, longer than its
   * column, and read character by character. It is shown whole and wraps inside its box instead of
   * being cut by an ellipsis (see `.ui-copyable--digest` in primitives.css).
   */
  digest?: boolean;
}): ReactElement {
  const [status, setStatus] = useState("");
  const copy = useCallback(() => {
    const write = navigator.clipboard?.writeText?.(value);
    if (!write) {
      setStatus(`Could not copy ${label}. Select the text and copy it manually.`);
      return;
    }
    write.then(
      () => setStatus(`Copied ${label}`),
      () => setStatus(`Could not copy ${label}. Select the text and copy it manually.`),
    );
  }, [value, label]);
  return (
    <span className={cx("ui-copyable", digest && "ui-copyable--digest")}>
      <span className={cx("ui-copyable__value", mono && "ui-copyable__value--mono")}>{value}</span>
      <IconButton label={`Copy ${label}`} icon={<IconCopy />} size="sm" onClick={copy} />
      <LiveRegion message={status} />
    </span>
  );
}

/**
 * An empty state must say WHY it is empty. "No results" is indistinguishable from "we did not
 * look", and in this product those are opposite claims — so `reason` is required, not optional.
 */
export function Empty({
  title,
  reason,
  action,
  className,
}: {
  title: string;
  reason: string;
  action?: ReactNode;
  className?: string;
}): ReactElement {
  return (
    <div className={cx("ui-empty", className)}>
      <p className="ui-empty__title">{title}</p>
      <p className="ui-empty__reason">{reason}</p>
      {action ? <div className="ui-empty__action">{action}</div> : null}
    </div>
  );
}

/**
 * A static placeholder block. Deliberately NOT animated: the trace packet marker is the only
 * looping animation that runs in this product (design brief 4.8), and a shimmering skeleton would
 * be a second one with no information behind it.
 */
export function Skeleton({
  lines = 1,
  width = "100%",
  height,
}: {
  lines?: number;
  width?: string;
  height?: string;
}): ReactElement {
  return (
    <div className="ui-skeleton" aria-hidden="true">
      {Array.from({ length: Math.max(1, lines) }, (_, i) => (
        <span
          key={i}
          className="ui-skeleton__line"
          style={{ inlineSize: i === lines - 1 && lines > 1 ? "62%" : width, blockSize: height }}
        />
      ))}
    </div>
  );
}

/**
 * A citation, rendered as the affordance that opens the raw record in the Inspector. Every
 * displayed claim in this application carries one (acceptance B6), so this is the most-repeated
 * control in the product: it stays small, monospace and quiet until hovered or focused.
 *
 * It takes an `onOpen` callback and does not import the Inspector — the Inspector is a surface,
 * and a primitive that reached into one would couple this file to half the app.
 */
/**
 * An identifier path with a <wbr> after every separator (`.` `_` `/` `-` `:`). CSS offers no
 * break opportunity at `.` or `_`, so a path longer than its column either overflows or — under an
 * `overflow-wrap` licence — splits between two letters ("acls.core1.PROTECT_SERV / ERS[3]",
 * acceptance C2-1, measured at 1440 px). This gives it sanctioned breaks at identifier boundaries
 * only; `textContent` and the accessible name are unchanged.
 */
function identifierBreaks(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let run = "";
  let k = 0;
  for (const ch of text) {
    run += ch;
    if (ch === "." || ch === "_" || ch === "/" || ch === "-" || ch === ":") {
      out.push(run, <wbr key={k++} />);
      run = "";
    }
  }
  if (run !== "") out.push(run);
  return out;
}

export function Cite({
  cite,
  onOpen,
  label,
  className,
}: {
  cite: CitePath;
  onOpen: (cite: CitePath) => void;
  /** Overrides the visible text; the citation path stays in the accessible name. */
  label?: string;
  className?: string;
}): ReactElement {
  return (
    <button
      type="button"
      className={cx("ui-cite", className)}
      onClick={() => onOpen(cite)}
      aria-label={`Open source record ${cite}`}
    >
      <IconCite className="ui-cite__glyph" />
      <span className="ui-cite__path">{identifierBreaks(label ?? cite)}</span>
    </button>
  );
}
