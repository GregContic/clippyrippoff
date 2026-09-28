import type { Candidate } from '../api/types';
import { Button, Card, EmptyState } from './ui';
import { CandidateCard } from './CandidateCard';

export function CandidateGrid({
  candidates,
  selectedIds,
  onToggle,
  onSelectAll,
  onClear,
  onPreview,
  onEdit,
  onRender,
  busy,
  renderStatusById,
}: {
  candidates: Candidate[];
  selectedIds: number[];
  onToggle: (candidateId: number) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onPreview: (candidate: Candidate) => void;
  onEdit: (candidate: Candidate) => void;
  onRender: () => void;
  busy?: boolean;
  renderStatusById?: Record<number, string | null | undefined>;
}) {
  if (!candidates.length) {
    return <EmptyState title="No candidates yet" description="The existing detector has not returned any clip suggestions for this video." />;
  }

  return (
    <div className="space-y-5">
      <Card className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-base font-semibold text-white">{candidates.length} candidates found</div>
          <div className="text-sm text-slate-400">Select clips to render locally on this machine.</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={onSelectAll}>Select All</Button>
          <Button type="button" variant="ghost" onClick={onClear}>Clear</Button>
          <Button type="button" onClick={onRender} disabled={!selectedIds.length || busy}>
            Render Selected ({selectedIds.length})
          </Button>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {candidates.map((candidate) => (
          <CandidateCard
            key={candidate.id}
            candidate={candidate}
            selected={selectedIds.includes(candidate.id)}
            onToggle={() => onToggle(candidate.id)}
            onPreview={() => onPreview(candidate)}
            onEdit={() => onEdit(candidate)}
            renderStatus={renderStatusById?.[candidate.id] ?? null}
          />
        ))}
      </div>
    </div>
  );
}
