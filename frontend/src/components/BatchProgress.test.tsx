import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { BatchResponse } from '../api/types';
import { BatchProgress } from './BatchProgress';

afterEach(cleanup);

function makeBatch(status: string): BatchResponse {
  return {
    batch_id: 'batch-1',
    project_id: 'video-1',
    parent_job_id: 'job-1',
    status,
    percent: 62,
    child_job_ids: ['child-1', 'child-2', 'child-3'],
    children: [
      { job_id: 'child-1', status: 'completed', percent: 100, candidate_id: 2, output_url: '/media/clip.mp4' },
      { job_id: 'child-2', status: 'failed', percent: 35, candidate_id: 3, error: 'Render failed.' },
      { job_id: 'child-3', status: 'interrupted', percent: 10, candidate_id: 4, error: 'Worker restarted.' },
    ],
    target_duration_seconds: 30,
    minimum_spacing_seconds: 5,
    created_at: '2026-10-14T00:00:00Z',
  };
}

describe('BatchProgress', () => {
  it.each([
    ['queued', 'Queued'],
    ['running', 'Running'],
    ['completed', 'Completed'],
    ['partially_completed', 'Partially completed'],
    ['failed', 'Failed'],
    ['interrupted', 'Interrupted'],
  ])('shows the %s parent status', (status, label) => {
    render(<BatchProgress batch={makeBatch(status)} />);
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent?.startsWith(`${label} ·`) === true)).toBeTruthy();
  });

  it('shows clip counts, links, child failures, and polling recovery guidance', () => {
    render(
      <BatchProgress
        batch={makeBatch('partially_completed')}
        pollingError="Temporary network failure."
        onRetryPolling={() => undefined}
      />,
    );

    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent?.includes('1/3 clips completed') === true)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open clip' }).getAttribute('href')).toContain('/media/clip.mp4');
    expect(screen.getByText('Render failed.')).toBeTruthy();
    expect(screen.getByText(/will retry automatically/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh status' })).toBeTruthy();
  });
});
