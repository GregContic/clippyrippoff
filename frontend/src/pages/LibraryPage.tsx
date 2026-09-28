import { useEffect, useState } from 'react';
import { deleteLibraryFile, listLibrary } from '../api/client';
import type { LibraryItem } from '../api/types';
import { LibraryGrid } from '../components/LibraryGrid';
import { Card } from '../components/ui';

export function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [error, setError] = useState<string | null>(null);

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
      {error ? <Card className="border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</Card> : null}
      <LibraryGrid items={items} onDelete={(filename) => { void handleDelete(filename); }} />
    </div>
  );
}
