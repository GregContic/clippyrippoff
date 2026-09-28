import { useEffect, useState } from 'react';
import { getSettings } from '../api/client';
import type { Settings } from '../api/types';
import { Card } from '../components/ui';
import { formatDuration } from '../lib/format';

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((response) => setSettings(response))
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Unable to load settings.'));
  }, []);

  if (error) {
    return <Card className="border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</Card>;
  }

  if (!settings) {
    return <Card className="p-6 text-sm text-slate-400">Loading settings...</Card>;
  }

  return (
    <Card className="p-6">
      <div className="space-y-4">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Read-only configuration</div>
          <h2 className="mt-2 text-2xl font-semibold text-white">Core engine settings</h2>
          <p className="mt-2 text-sm text-slate-400">Settings editing will be added later.</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <SettingCard label="Whisper model" value={settings.whisper_model} />
          <SettingCard label="Minimum clip duration" value={formatDuration(settings.clip_min_seconds)} />
          <SettingCard label="Maximum clip duration" value={formatDuration(settings.clip_max_seconds)} />
          <SettingCard label="Candidate count" value={String(settings.max_candidates)} />
          <SettingCard label="Context before" value={formatDuration(settings.context_before_seconds)} />
          <SettingCard label="Context after" value={formatDuration(settings.context_after_seconds)} />
          <SettingCard label="Merge gap" value={formatDuration(settings.candidate_merge_gap_seconds)} />
          <SettingCard label="Quiet boundary" value={formatDuration(settings.boundary_quiet_seconds)} />
        </div>
      </div>
    </Card>
  );
}

function SettingCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
      <div className="text-xs uppercase tracking-[0.22em] text-slate-500">{label}</div>
      <div className="mt-2 text-sm font-semibold text-white">{value}</div>
    </div>
  );
}
