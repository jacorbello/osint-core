import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PlaceholderPage } from './PlaceholderPage';

describe('PlaceholderPage', () => {
  it('renders title and default description', () => {
    renderWithProviders(<PlaceholderPage icon="source" title="Sources" />);

    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('Coming soon')).toBeInTheDocument();
  });

  it('renders the provided icon', () => {
    renderWithProviders(<PlaceholderPage icon="source" title="Sources" />);

    expect(screen.getByText('source')).toBeInTheDocument();
  });

  it('renders a custom description', () => {
    renderWithProviders(
      <PlaceholderPage
        icon="hub"
        title="Entities"
        description="Entity resolution coming in Phase 3"
      />,
    );

    expect(screen.getByText('Entity resolution coming in Phase 3')).toBeInTheDocument();
  });

  it('renders the intelligence cycle phase badge when provided', () => {
    renderWithProviders(
      <PlaceholderPage icon="source" title="Sources" phase="Collection" />,
    );

    expect(screen.getByText('Collection')).toBeInTheDocument();
  });

  it('does not render a phase badge when phase is not provided', () => {
    const { container } = renderWithProviders(
      <PlaceholderPage icon="source" title="Sources" />,
    );

    expect(container.querySelector('.bg-surface-container')).not.toBeInTheDocument();
  });
});
