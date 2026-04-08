import { render, screen } from '@testing-library/react';
import { Button } from '@/components/ui/Button';

describe('Button', () => {
  it('renders children text', () => {
    render(<Button>Run test</Button>);

    expect(screen.getByRole('button', { name: 'Run test' })).toBeInTheDocument();
  });
});
