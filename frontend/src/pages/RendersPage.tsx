import { useEffect, useState } from 'react';
import { deleteRender, listRenders } from '../api/client';
import type { RenderJob } from '../api/types';
import { RenderQueue } from '../components/RenderQueue';
import { Card } from '../components/ui';

export function RendersPage() {
  const [jobs, setJobs] = useState<RenderJob[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const response = await listRenders();
        if (active) {
          setJobs(response);
        }
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : 'Unable to load render queue.');
        }
      }
    }

    void load();
    const interval = window.setInterval(() => {
      void load();
    }, 3000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  async function removeRender(renderId: string) {
    await deleteRender(renderId);
    const updated = await listRenders();
    setJobs(updated);
  }

  return (
    <div className="space-y-5">
      {error ? <Card className="border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</Card> : null}
      <RenderQueue jobs={jobs} onRemove={(renderId) => { void removeRender(renderId); }} />
    </div>
  );
}
