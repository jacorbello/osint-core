import { useState } from 'react';
import { cn } from '@/lib/utils/cn';
import { IconButton } from '@/components/ui/IconButton';

interface CopyableIdProps {
  id: string;
  className?: string;
  short?: boolean;
}

export function CopyableId({ id, className, short = true }: CopyableIdProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const displayId = short ? `${id.slice(0, 8)}...${id.slice(-4)}` : id;

  return (
    <div className={cn('inline-flex items-center gap-2 font-mono text-sm', className)}>
      <span className="text-on-surface-variant">{displayId}</span>
      <IconButton
        size="sm"
        onClick={handleCopy}
        title={copied ? 'Copied!' : 'Copy to clipboard'}
        className="h-6 w-6"
      >
        <span className="material-symbols-outlined text-xs">
          {copied ? 'check' : 'content_copy'}
        </span>
      </IconButton>
    </div>
  );
}
