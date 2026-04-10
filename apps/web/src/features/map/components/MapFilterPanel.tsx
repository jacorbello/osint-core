import { cn } from '@/lib/utils/cn';
import { getSeverityColor } from '@/lib/utils/severity';
import { formatRelativeTime } from '@/lib/utils/format';
import type { SeverityEnum } from '@/types/api/common';

export type LayerType = 'alerts' | 'leads' | 'watches' | 'signals';

export interface MapMarkerItem {
  id: string;
  type: LayerType;
  title: string;
  severity: SeverityEnum;
  lat: number;
  lng: number;
  timestamp: string;
  summary?: string | null;
}

interface MapFilterPanelProps {
  layers: Record<LayerType, boolean>;
  onLayerToggle: (layer: LayerType) => void;
  severityFilters: SeverityEnum[];
  onSeverityToggle: (severity: SeverityEnum) => void;
  selectedItem: MapMarkerItem | null;
  onClearSelection: () => void;
}

const LAYER_CONFIG: { type: LayerType; label: string; icon: string; color: string }[] = [
  { type: 'alerts', label: 'Alerts', icon: 'warning', color: 'text-error' },
  { type: 'leads', label: 'Leads', icon: 'person_search', color: 'text-primary' },
  { type: 'watches', label: 'Watches', icon: 'visibility', color: 'text-tertiary' },
  { type: 'signals', label: 'Signals', icon: 'sensors', color: 'text-secondary' },
];

const SEVERITY_OPTIONS: SeverityEnum[] = ['critical', 'high', 'medium', 'low'];

function getTypeRoute(type: LayerType): string {
  switch (type) {
    case 'alerts':
      return '/alerts';
    case 'leads':
      return '/leads';
    case 'watches':
      return '/watches';
    default:
      return '/';
  }
}

export function MapFilterPanel({
  layers,
  onLayerToggle,
  severityFilters,
  onSeverityToggle,
  selectedItem,
  onClearSelection,
}: MapFilterPanelProps) {
  return (
    <div
      className="w-[240px] flex-shrink-0 bg-surface-container-low border-r border-outline-variant/10 flex flex-col h-full overflow-y-auto"
      data-testid="map-filter-panel"
    >
      {/* Layers section */}
      <div className="p-4 border-b border-outline-variant/10">
        <h3 className="text-[9px] font-bold uppercase tracking-widest text-outline mb-3">
          Layers
        </h3>
        <div className="flex flex-col gap-1.5">
          {LAYER_CONFIG.map(({ type, label, icon, color }) => (
            <button
              key={type}
              onClick={() => onLayerToggle(type)}
              className={cn(
                'flex items-center gap-2 px-2.5 py-1.5 rounded text-xs transition-colors text-left',
                layers[type]
                  ? 'bg-surface-container-high text-on-surface'
                  : 'text-on-surface-variant/50 hover:bg-surface-container'
              )}
              data-testid={`layer-toggle-${type}`}
              aria-pressed={layers[type]}
            >
              <span
                className={cn(
                  'material-symbols-outlined text-base',
                  layers[type] ? color : 'text-on-surface-variant/40'
                )}
                style={{ fontVariationSettings: layers[type] ? "'FILL' 1" : "'FILL' 0" }}
              >
                {icon}
              </span>
              <span className="flex-1">{label}</span>
              <span
                className={cn(
                  'w-2 h-2 rounded-full transition-colors',
                  layers[type] ? 'bg-primary' : 'bg-outline-variant/30'
                )}
              />
            </button>
          ))}
        </div>
      </div>

      {/* Severity section */}
      <div className="p-4 border-b border-outline-variant/10">
        <h3 className="text-[9px] font-bold uppercase tracking-widest text-outline mb-3">
          Severity
        </h3>
        <div className="flex flex-wrap gap-1.5">
          {SEVERITY_OPTIONS.map((severity) => {
            const active = severityFilters.includes(severity);
            return (
              <button
                key={severity}
                onClick={() => onSeverityToggle(severity)}
                className={cn(
                  'px-2 py-1 rounded text-[10px] font-bold uppercase transition-colors',
                  active
                    ? getSeverityColor(severity)
                    : 'bg-surface-container text-on-surface-variant/50 hover:bg-surface-container-high'
                )}
                data-testid={`severity-filter-${severity}`}
                aria-pressed={active}
              >
                {severity}
              </button>
            );
          })}
        </div>
      </div>

      {/* Selection detail */}
      <div className="p-4 flex-1">
        <h3 className="text-[9px] font-bold uppercase tracking-widest text-outline mb-3">
          Selection
        </h3>
        {selectedItem ? (
          <div className="space-y-3" data-testid="selection-detail">
            <div className="flex items-start justify-between gap-2">
              <span
                className={cn(
                  'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase',
                  getSeverityColor(selectedItem.severity)
                )}
              >
                {selectedItem.severity}
              </span>
              <button
                onClick={onClearSelection}
                className="text-on-surface-variant/50 hover:text-on-surface transition-colors"
                aria-label="Clear selection"
                data-testid="clear-selection"
              >
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <div>
              <p className="text-sm font-medium text-on-surface" data-testid="selection-title">
                {selectedItem.title}
              </p>
              <p className="text-[10px] text-on-surface-variant mt-0.5 uppercase font-bold">
                {selectedItem.type}
              </p>
            </div>
            {selectedItem.summary && (
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {selectedItem.summary}
              </p>
            )}
            <p className="text-[10px] text-outline">
              {formatRelativeTime(selectedItem.timestamp)}
            </p>
            <a
              href={`${getTypeRoute(selectedItem.type)}/${selectedItem.id}`}
              className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors font-medium"
              data-testid="open-detail-link"
            >
              Open
              <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </a>
          </div>
        ) : (
          <p className="text-xs text-on-surface-variant/50" data-testid="no-selection">
            Click a marker to view details
          </p>
        )}
      </div>
    </div>
  );
}
