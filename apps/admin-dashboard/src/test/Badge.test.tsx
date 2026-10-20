import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge } from '../components/common/Badge';

describe('Badge Component', () => {
  it('renders status text correctly', () => {
    render(<Badge status="healthy" />);
    expect(screen.getByText('healthy')).toBeInTheDocument();
  });

  it('renders custom label when provided', () => {
    render(<Badge status="active" label="نشط ومفعل" />);
    expect(screen.getByText('نشط ومفعل')).toBeInTheDocument();
  });

  it('applies emerald styles for healthy or active status', () => {
    const { container } = render(<Badge status="active" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('emerald');
  });

  it('applies rose styles for failed or error status', () => {
    const { container } = render(<Badge status="failed" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('rose');
  });

  it('applies amber styles for pending status', () => {
    const { container } = render(<Badge status="pending" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('amber');
  });
});
