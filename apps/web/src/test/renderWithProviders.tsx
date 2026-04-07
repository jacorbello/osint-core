import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react';
import { MemoryRouter, type MemoryRouterProps } from 'react-router-dom';
import type { ReactElement, ReactNode } from 'react';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

interface TestProvidersProps {
  children: ReactNode;
}

function TestProviders({ children }: TestProvidersProps) {
  const queryClient = createTestQueryClient();
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return render(ui, {
    wrapper: TestProviders,
    ...options,
  });
}

interface RenderWithRouterAndProvidersOptions
  extends Omit<RenderOptions, 'wrapper'> {
  router?: Pick<MemoryRouterProps, 'initialEntries' | 'initialIndex'>;
}

export function renderWithRouterAndProviders(
  ui: ReactElement,
  options?: RenderWithRouterAndProvidersOptions
) {
  const initialEntries = options?.router?.initialEntries ?? ['/'];
  const initialIndex = options?.router?.initialIndex;

  return renderWithProviders(
    <MemoryRouter initialEntries={initialEntries} initialIndex={initialIndex}>
      {ui}
    </MemoryRouter>,
    options
  );
}
