import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ErrorBoundary from './ErrorBoundary';

function Boom({ data }) {
  return <span>{data.value.toFixed(1)}</span>; // crashes when data.value is missing
}

describe('ErrorBoundary', () => {
  // React (dev) logs caught render errors and re-dispatches them as window "error" events —
  // keep the test output clean
  const swallow = (e) => e.preventDefault();
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    window.addEventListener('error', swallow);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    window.removeEventListener('error', swallow);
  });

  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <Boom data={{ value: 1 }} />
      </ErrorBoundary>
    );
    expect(screen.getByText('1.0')).toBeInTheDocument();
  });

  it('a render error shows a message instead of blanking the app', () => {
    render(
      <div>
        <p>outside</p>
        <ErrorBoundary>
          <Boom data={{}} />
        </ErrorBoundary>
      </div>
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong displaying this view.');
    expect(screen.getByText('outside')).toBeInTheDocument();
  });

  it('new resetKey (new data) renders the children again', () => {
    const bad = {};
    const good = { value: 2 };
    const { rerender } = render(
      <ErrorBoundary resetKey={bad}>
        <Boom data={bad} />
      </ErrorBoundary>
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    rerender(
      <ErrorBoundary resetKey={good}>
        <Boom data={good} />
      </ErrorBoundary>
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('2.0')).toBeInTheDocument();
  });
});
