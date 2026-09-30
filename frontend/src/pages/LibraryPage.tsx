import { useEffect, useState } from 'react';
import { deleteLibraryFile, listLibrary } from '../api/client';
import type { LibraryItem } from '../api/types';
import { LibraryGrid } from '../components/LibraryGrid';
import { Card } from '../components/ui';

export function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState('all');

  async function load() {
    try {
      const response = await listLibrary();
      setItems(response.items);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to load library.');
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleDelete(filename: string) {
    await deleteLibraryFile(filename);
    await load();
  }

  return (
    <div className="space-y-5">
      {error ? <Card className="border-danger-500/30 bg-danger-500/10 p-4 text-sm text-danger-100">{error}</Card> : null}
      <Card className="flex flex-wrap items-center gap-3 p-4"><label className="text-sm text-slate-300">Review status <select value={reviewFilter} onChange={(event) => setReviewFilter(event.target.value)} className="ml-2 rounded-lg border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100"><option value="all">All renders</option><option value="approved">Approved</option><option value="pending_review">Pending Review</option><option value="needs_changes">Needs Changes</option></select></label></Card>
      <LibraryGrid items={items} reviewFilter={reviewFilter} onDelete={(filename) => { void handleDelete(filename); }} />
    </div>
  );
}
