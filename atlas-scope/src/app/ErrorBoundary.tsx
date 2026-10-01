/**
 * ErrorBoundary.tsx — one failed panel must not end the investigation.
 *
 * Each surface is wrapped separately rather than the app being wrapped once. A single top-level
 * boundary converts any render throw anywhere into a blank document, which in an evidence tool is
 * the worst available failure: the reader loses the finding they were reading, the trace they were
 * following AND the selection that got them there, and has nothing on screen to say why. Scoped
 * boundaries keep the rails, the fabric and the URL intact, so the investigation survives and only
 * the broken region is replaced.
 *
 * The replacement names the region and prints the error verbatim. A generic apology would make a
 * renderer defect indistinguishable from an absence of data, which is the same class of lie this
 * product exists to refuse: not rendering is not the same as nothing being there.
 */
import { Component, Fragment, type ErrorInfo, type ReactNode } from "react";

import "./App.css";

export interface ErrorBoundaryProps {
  /** Named in the replacement copy, e.g. "the priority queue". A phrase, not an id. */
  surface: string;
  children: ReactNode;
  /**
   * Called once per caught error. The shell uses it to push the failure into the assertive live
   * region — a screen-reader user gets no visual cue that a region was replaced.
   */
  onError?: (surface: string, error: Error) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
  /** Bumped by the retry control. Changing it re-mounts the subtree, so a transient failure — a
   *  race against data that has since arrived — genuinely gets a second attempt rather than
   *  re-rendering the same broken element tree. */
  attempt: number;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null, attempt: 0 };

  static getDerivedStateFromError(error: unknown): Partial<ErrorBoundaryState> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    /* Kept on the console with its component stack. The on-screen copy is for the reader; this is
       for whoever has to fix it, and dropping it would mean the only record of the stack is a
       frame that has already been unmounted. */
    console.error(`[atlas-scope] ${this.props.surface} failed to render`, error, info.componentStack);
    this.props.onError?.(this.props.surface, error);
  }

  private retry = (): void => {
    this.setState((s) => ({ error: null, attempt: s.attempt + 1 }));
  };

  override render(): ReactNode {
    const { error, attempt } = this.state;
    /* A keyed Fragment, not a wrapper element: the rails and the stage are grid and flex parents,
       and an extra box between them and their panel would change the layout of every surface in
       order to serve an error path that is normally idle. */
    if (error === null) return <Fragment key={attempt}>{this.props.children}</Fragment>;

    return (
      <div className="surface-error" role="alert">
        <h2 className="surface-error__title">{this.props.surface} stopped rendering</h2>
        <p className="surface-error__body">
          This region hit an error while drawing itself. Nothing else in the investigation was
          changed: the selection, the query, the trace and every other panel are as you left them.
          What is missing here is the drawing of the data, not the data.
        </p>
        <pre className="surface-error__detail">{error.message}</pre>
        <button type="button" className="surface-error__retry" onClick={this.retry}>
          Draw this region again
        </button>
      </div>
    );
  }
}

export default ErrorBoundary;
