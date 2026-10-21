import { Component, type ErrorInfo, type ReactNode } from "react";
import { T } from "../content/texts";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }
  render() {
    if (this.state.failed)
      return (
        <main className="auth-page">
          <div className="auth-column">
            <h1 className="auth-brand">{T.app_name}</h1>
            <p>{T.err_server}</p>
            <button
              className="primary-submit"
              onClick={() => location.reload()}
            >
              {T.btn_retry}
            </button>
          </div>
        </main>
      );
    return this.props.children;
  }
}
