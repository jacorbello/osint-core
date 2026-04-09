import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ActivityFeed } from './ActivityFeed';
import type { SSEFeedItem } from '@/features/stream/hooks/useSSEFeed';

const mockUseSSEFeed = vi.fn<() => { events: SSEFeedItem[]; connected: boolean }>();

vi.mock('@/features/stream/hooks/useSSEFeed', () => ({
  useSSEFeed: (...args: unknown[]) => mockUseSSEFeed(...(args as [])),
}));

function makeEvent(overrides: Partial<SSEFeedItem> = {}): SSEFeedItem {
  return {
    type: 'alert.updated',
    resource: 'alert',
    id: 'abc12345-6789-0000-0000-000000000000',
    timestamp: new Date().toISOString(),
    payload: {},
    receivedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe('ActivityFeed', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSSEFeed.mockReturnValue({ events: [], connected: true });
  });

  // --- No animate-pulse anywhere ---
  it('does not render any animate-pulse classes', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent()],
      connected: true,
    });

    const { container } = renderWithProviders(<ActivityFeed />);
    const pulseElements = container.querySelectorAll('[class*="animate-pulse"]');
    expect(pulseElements).toHaveLength(0);
  });

  // --- Connection status: dot + text without animation ---
  it('shows green connection dot when connected', () => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: true });
    renderWithProviders(<ActivityFeed />);

    const dot = screen.getByTestId('connection-dot');
    expect(dot.className).toContain('bg-success');
    expect(dot.className).not.toContain('animate');
  });

  it('shows red connection dot when disconnected', () => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: false });
    renderWithProviders(<ActivityFeed />);

    const dot = screen.getByTestId('connection-dot');
    expect(dot.className).toContain('bg-critical');
    expect(dot.className).not.toContain('animate');
  });

  it('shows "Disconnected" text when not connected', () => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: false });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  // --- Event rate displayed ---
  it('shows event rate when connected', () => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: true });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText(/events\/min/)).toBeInTheDocument();
  });

  // --- Event cards use new color tokens for left borders ---
  it('renders alert event card with critical border', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent({ type: 'alert.updated' })],
      connected: true,
    });
    renderWithProviders(<ActivityFeed />);

    const card = screen.getByTestId('event-card');
    expect(card.className).toContain('border-l-critical');
  });

  it('renders lead event card with primary border', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent({ type: 'lead.updated' })],
      connected: true,
    });
    renderWithProviders(<ActivityFeed />);

    const card = screen.getByTestId('event-card');
    expect(card.className).toContain('border-l-primary');
  });

  it('renders job event card with success border', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent({ type: 'job.updated' })],
      connected: true,
    });
    renderWithProviders(<ActivityFeed />);

    const card = screen.getByTestId('event-card');
    expect(card.className).toContain('border-l-success');
  });

  // --- Type badges render correctly ---
  it('renders ALERT badge for alert events', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent({ type: 'alert.updated' })],
      connected: true,
    });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText('ALERT')).toBeInTheDocument();
  });

  it('renders LEAD badge for lead events', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent({ type: 'lead.updated' })],
      connected: true,
    });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText('LEAD')).toBeInTheDocument();
  });

  it('renders JOB badge for job events', () => {
    mockUseSSEFeed.mockReturnValue({
      events: [makeEvent({ type: 'job.updated' })],
      connected: true,
    });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText('JOB')).toBeInTheDocument();
  });

  // --- SSE hook integration preserved ---
  it('calls useSSEFeed with the stream URL', () => {
    renderWithProviders(<ActivityFeed />);
    expect(mockUseSSEFeed).toHaveBeenCalled();
  });

  // --- Empty states ---
  it('shows "Waiting for events..." when connected with no events', () => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: true });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText('Waiting for events...')).toBeInTheDocument();
  });

  it('shows "Connecting..." when disconnected with no events', () => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: false });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText('Connecting...')).toBeInTheDocument();
  });

  // --- Relative timestamps ---
  it('displays events with relative timestamps', () => {
    const event = makeEvent({
      timestamp: new Date(Date.now() - 60_000).toISOString(),
    });
    mockUseSSEFeed.mockReturnValue({ events: [event], connected: true });
    renderWithProviders(<ActivityFeed />);

    expect(screen.getByText(/ago/)).toBeInTheDocument();
  });

  // --- Header text ---
  it('renders "Activity" as the header', () => {
    renderWithProviders(<ActivityFeed />);
    expect(screen.getByText('Activity')).toBeInTheDocument();
  });
});
