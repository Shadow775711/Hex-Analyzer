// src/components/ErrorBoundary.jsx — a render error in one tab (e.g. an unexpected server
// response) shows a message instead of blanking the whole app
import React from 'react';

export default class ErrorBoundary extends React.Component {
  state = { error: null, resetKey: undefined };

  static getDerivedStateFromError(error) {
    return { error };
  }

  // new data (resetKey) → try rendering again
  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) return { error: null, resetKey: props.resetKey };
    return null;
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="alert alert--error" role="alert">
          Something went wrong displaying this view.
        </div>
      );
    }
    return this.props.children;
  }
}
