import type { LibraryItem } from '../api/types';
import { resolveMediaUrl } from '../api/client';
import { formatDate, formatDuration, formatBytes } from '../lib/format';
import { Button, Card, EmptyState } from './ui';

export function LibraryGrid({
  items,
  onDelete,
  reviewFilter = 'all',
}: {
  items: LibraryItem[];
  onDelete: (filename: string) => void;
  reviewFilter?: string;
}) {
  const visibleItems = reviewFilter === 'all' ? items : items.filter((item) => item.review_status === reviewFilter);
  if (!visibleItems.length) {
    return <EmptyState title="No shorts yet" description="Rendered clips from output/shorts/ will show up here." />;
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {visibleItems.map((item) => (
        <Card key={item.filename} className="overflow-hidden">
          <div className="bg-surface-950">
            <video src={resolveMediaUrl(item.url) ?? item.url} controls preload="metadata" className="aspect-video w-full bg-surface-950 object-cover" />
          </div>
          <div className="space-y-4 p-4">
            <div>
              <div className="truncate text-sm font-semibold text-white">{item.filename}</div>
              <div className="mt-1 text-sm text-slate-400">{formatDuration(item.duration)} • {formatBytes(item.size_bytes)}</div>
              <div className="mt-1 text-xs text-slate-500">{formatDate(item.created_at)}</div>
              <div className={`mt-2 text-xs font-semibold uppercase tracking-[0.16em] ${item.review_status === 'approved' ? 'text-success-100' : item.review_status === 'needs_changes' ? 'text-warning-200' : 'text-slate-400'}`}>{item.review_status === 'needs_changes' ? 'Needs Changes' : item.review_status === 'approved' ? 'Approved' : 'Pending Review'}</div>
            </div>
            <div className="flex gap-2">
              <a href={resolveMediaUrl(item.url) ?? item.url} target="_blank" rel="noreferrer" className="inline-flex flex-1 items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-sky-400/40 hover:bg-slate-700/80">
                Open
              </a>
              <Button type="button" variant="danger" className="flex-1" onClick={() => onDelete(item.filename)}>
                Delete
              </Button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
