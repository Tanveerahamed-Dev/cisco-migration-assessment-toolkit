import { Component, ErrorInfo, ReactNode } from "react";

/**
 * WEBAP-01: the app mounted the route tree with NO error boundary, so any uncaught exception thrown during
 * render of a single panel (a malformed section from a hostile/partial upload) unmounted the WHOLE tree under
 * React 18 and white-screened the entire route. This boundary catches a render crash and shows a recoverable
 * error card instead of a blank page; the TopBar/nav stays outside it, and App keys it by location.pathname so
 * navigating to another route remounts it fresh.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("AssessHub render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="container">
          <div className="panel" role="alert" style={{ borderColor: "var(--crit)" }}>
            <h3 style={{ marginTop: 0 }}>Something went wrong rendering this view</h3>
            <p style={{ color: "var(--text-dim)" }}>
              {this.state.error.message || "An unexpected error occurred."}
            </p>
            <button className="btn" onClick={() => this.setState({ error: null })}>
              Try again
            </button>{" "}
            <button className="btn ghost" onClick={() => location.reload()}>
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
