import { useRef, type FormEvent } from 'react';
import { Button, Input } from './ui';

export function UrlInput({
  value,
  onChange,
  onSubmit,
  loading,
  onUpload,
  uploadDisabled,
  uploadAccept,
  busyLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  onUpload?: (file: File) => void;
  uploadDisabled?: boolean;
  uploadAccept?: string;
  busyLabel?: string;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Paste YouTube URL here"
        className="min-h-12 flex-1"
      />
      <Button type="submit" disabled={loading} className="min-h-12 px-5">
        {loading ? busyLabel ?? 'Analyzing...' : 'Analyze Video →'}
      </Button>
      {onUpload ? (
        <>
          <Button
            type="button"
            disabled={loading || uploadDisabled}
            onClick={() => fileInputRef.current?.click()}
            className="min-h-12 border-surface-600 bg-surface-800 px-4 text-slate-200 hover:border-accent-500/40 hover:bg-surface-700"
          >
            Upload video
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept={uploadAccept ?? 'video/*,.mkv,.avi,.mov,.webm,.m4v'}
            aria-label="Select a video file"
            className="sr-only"
            tabIndex={-1}
            disabled={loading || uploadDisabled}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(file);
              event.currentTarget.value = '';
            }}
          />
        </>
      ) : null}
    </form>
  );
}
