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
import type { Band as BandName, Cite as CitePath, OpStatus, Severity } from "../core/types";
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
  tone?: "neutral" | "accent";
  mono?: boolean;
  title?: string;
}

export function Chip({
  children,
  onClick,
  onRemove,
  removeLabel,
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
          onClick={onRemove}
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
export function Band({
  band,
  cite,
  onOpenCite,
  className,
}: {
  band: BandName | null | undefined;
  cite?: CitePath;
  onOpenCite?: (cite: CitePath) => void;
  className?: string;
}): ReactNode {
  if (!band) {
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
    <span className={cx("ui-band", className)} data-band={band}>
      {band}
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
  return (
    <div
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
  const toggle = (): void => {
    const next = !open;
    if (controlled === undefined) setUncontrolled(next);
    onOpenChange?.(next);
  };
  return (
    <div className={cx("ui-disclosure", className)} data-open={open}>
      <button
        type="button"
        className="ui-disclosure__trigger"
        aria-expanded={open}
        aria-controls={`${id}-region`}
        onClick={toggle}
      >
        <IconChevronRight className="ui-disclosure__chev" />
        <span className="ui-disclosure__summary">{summary}</span>
      </button>
      <div id={`${id}-region`} role="region" hidden={!open} className="ui-disclosure__region">
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
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
      (anchorRef.current?.firstElementChild as HTMLElement | null)?.focus();
    };
    const onDown = (e: MouseEvent): void => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t) || anchorRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, setOpen]);

  useEffect(() => {
    if (open) focusablesIn(panelRef.current)[0]?.focus();
  }, [open]);

  const p = trigger.props;
  const triggerEl = cloneElement(trigger, {
    "aria-expanded": open,
    "aria-haspopup": "dialog",
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
            className="ui-popover"
            data-align={align}
            style={
              {
                "--pop-top": `${rect.bottom}px`,
                "--pop-left": `${align === "start" ? rect.left : rect.left + rect.width}px`,
              } as CSSProperties
            }
          >
            {children}
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
}

/**
 * A modal dialog: focus is trapped while it is open, Escape closes it, and focus returns to
 * whatever invoked it (WCAG 2.4.3 / 2.1.2, acceptance D3). The trap is implemented on Tab rather
 * than by making the rest of the document inert, because `inert` would also stop a screen reader
 * from reading the investigation context the dialog is about.
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
}: DialogProps): ReactNode {
  const id = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    const target = initialFocus?.current ?? focusablesIn(panelRef.current)[0] ?? panelRef.current;
    target?.focus();
    return () => {
      /* Restore on close AND on unmount: a dialog whose parent is removed while it is open would
         otherwise leave focus on <body>, which silently resets keyboard navigation to the top. */
      returnTo.current?.focus();
    };
  }, [open, initialFocus]);

  useEffect(() => {
    if (!open) return;
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
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <Portal>
      <div className="ui-dialog__scrim" onMouseDown={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={description ? `${id}-desc` : undefined}
        tabIndex={-1}
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
      </div>
    </Portal>
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
}: {
  value: string;
  /** What is being copied, for the button's accessible name, e.g. "snapshot sha256". */
  label: string;
  mono?: boolean;
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
    <span className="ui-copyable">
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
 * looping animation in this product (design brief 4.8), and a shimmering skeleton would be a
 * second one with no information behind it.
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
      <span className="ui-cite__path">{label ?? cite}</span>
    </button>
  );
}
