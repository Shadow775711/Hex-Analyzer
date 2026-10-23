// Matchers like toBeInTheDocument() and DOM cleanup after each test
// (without `globals: true` Testing Library does not do it by itself)
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup);
