import { Component, type ReactNode } from 'react';
import { T } from '../content/texts';

/** Сбой отрисовки: вместо белой страницы — err_server и «Повторить» (03-behavior.md, 13) */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="crash">
        <p>{T.err_server}</p>
        <button type="button" className="pill pill--primary" onClick={() => window.location.reload()}>
          {T.btn_retry}
        </button>
      </div>
    );
  }
}
