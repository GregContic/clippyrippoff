import type { Candidate } from '../api/types';
import { Button, EmptyState } from './ui';
import { CandidateCard } from './CandidateCard';

export function CandidateGrid({
  candidates,
  selectedIds,
  onToggle,
  onSelectAll,
  onClear,
  onPreview,
  onRender,
  busy,
}: {
  candidates: Candidate[];
  selectedIds: number[];
  onToggle: (candidateId: number) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onPreview: (candidate: Candidate) => void;
  onRender: () => void;
  busy?: boolean;
}) {
  if (!candidates.length) {
    return <EmptyState title="No candidates yet" description="The existing detector has not returned any clip suggestions for this video." />;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/80 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-lg font-semibold text-white">{candidates.length} candidates found</div>
          <div className="text-sm text-slate-400">Select clips to render locally on this machine.</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={onSelectAll}>Select All</Button>
          <Button type="button" variant="ghost" onClick={onClear}>Clear</Button>
          <Button type="button" onClick={onRender} disabled={!selectedIds.length || busy}>
            Render Selected ({selectedIds.length})
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {candidates.map((candidate) => (
          <CandidateCard
            key={candidate.id}
            candidate={candidate}
            selected={selectedIds.includes(candidate.id)}
            onToggle={() => onToggle(candidate.id)}
            onPreview={() => onPreview(candidate)}
          />
        ))}
      </div>
    </div>
  );
}
