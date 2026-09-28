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
      {error ? <Card className="border-danger-500/30 bg-danger-500/10 p-4 text-sm text-danger-100">{error}</Card> : null}
      <LibraryGrid items={items} onDelete={(filename) => { void handleDelete(filename); }} />
    </div>
  );
}
