import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalysisProgress } from './AnalysisProgress';

describe('AnalysisProgress', () => {
  it('shows one highlight-detection step for the detecting and ranking stages', () => {
    render(<AnalysisProgress stage="ranking" status="running" />);

    expect(screen.getAllByText('Detecting & Ranking Highlights')).toHaveLength(1);
    expect(screen.getByText('Active')).toBeTruthy();
  });
});
