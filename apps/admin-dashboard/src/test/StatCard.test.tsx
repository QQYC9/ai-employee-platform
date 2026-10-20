import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatCard } from '../components/common/StatCard';
import { Bot } from 'lucide-react';

describe('StatCard Component', () => {
  it('renders title and numerical value correctly', () => {
    render(
      <StatCard
        title="إجمالي الوكلاء"
        value={42}
        subtitle="وكيل نشط"
        icon={Bot}
      />
    );
    expect(screen.getByText('إجمالي الوكلاء')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('وكيل نشط')).toBeInTheDocument();
  });

  it('renders trend value with positive highlight', () => {
    render(
      <StatCard
        title="معدل النجاح"
        value="98%"
        icon={Bot}
        trend={{ value: '+5%', isPositive: true }}
      />
    );
    const trendElem = screen.getByText('+5%');
    expect(trendElem).toBeInTheDocument();
    expect(trendElem.className).toContain('emerald');
  });
});
