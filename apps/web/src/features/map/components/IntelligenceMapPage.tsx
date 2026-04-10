import { useMemo } from 'react';
import { MapFilterPanel, type MapMarkerItem } from './MapFilterPanel';
import { useAlertsQuery } from '@/features/alerts/api/alertsQueries';
import { useLeadsQuery } from '@/features/leads/api/leadsQueries';
import { useWatchesListQuery } from '@/features/watches/api/watchesQueries';
import { MapCanvas } from './MapCanvas';
import { useMapState } from '../hooks/useMapState';

/** Default center (Washington DC) and zoom */
const DEFAULT_CENTER: [number, number] = [38.9, -77.0];
const DEFAULT_ZOOM = 4;

/**
 * Deterministic lat/lng from a string id.
 * Real data would come from the API; this generates stable positions for demo.
 */
function hashToCoord(id: string, base: number, range: number): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return base + (((hash % 1000) + 1000) % 1000) / 1000 * range;
}

export function IntelligenceMapPage() {
  const {
    layers,
    severityFilters,
    selectedItem,
    bounds,
    handleLayerToggle,
    handleSeverityToggle,
    handleClearSelection,
    handleMarkerClick,
    setBounds,
  } = useMapState();

  const { data: alertsData } = useAlertsQuery({ limit: 200 });
  const { data: leadsData } = useLeadsQuery({ limit: 200 });
  const { data: watchesData } = useWatchesListQuery({ limit: 200 });

  const markers: MapMarkerItem[] = useMemo(() => {
    const items: MapMarkerItem[] = [];

    if (alertsData?.items) {
      for (const alert of alertsData.items) {
        items.push({
          id: alert.id,
          type: 'alerts',
          title: alert.title,
          severity: alert.severity,
          lat: hashToCoord(alert.id, 25, 25),
          lng: hashToCoord(alert.id + 'lng', -120, 60),
          timestamp: alert.last_fired_at,
          summary: alert.summary,
        });
      }
    }

    if (leadsData?.items) {
      for (const lead of leadsData.items) {
        items.push({
          id: lead.id,
          type: 'leads',
          title: lead.title,
          severity: lead.severity ?? 'medium',
          lat: hashToCoord(lead.id, 25, 25),
          lng: hashToCoord(lead.id + 'lng', -120, 60),
          timestamp: lead.last_updated_at,
          summary: lead.summary,
        });
      }
    }

    if (watchesData?.items) {
      for (const watch of watchesData.items) {
        items.push({
          id: watch.id,
          type: 'watches',
          title: watch.name,
          severity: watch.severity_threshold ?? 'low',
          lat: hashToCoord(watch.id, 25, 25),
          lng: hashToCoord(watch.id + 'lng', -120, 60),
          timestamp: watch.created_at,
        });
      }
    }

    return items;
  }, [alertsData, leadsData, watchesData]);

  const filteredMarkers = useMemo(() => {
    return markers.filter((m) => {
      if (!layers[m.type]) return false;
      if (severityFilters.length > 0 && !severityFilters.includes(m.severity)) return false;
      return true;
    });
  }, [markers, layers, severityFilters]);

  return (
    <div className="flex flex-col h-full" data-testid="intelligence-map-page">
      {/* Header */}
      <div className="px-6 py-4 border-b border-outline-variant/10 flex-shrink-0">
        <h1 className="text-2xl font-headline font-semibold text-on-surface flex items-center gap-2">
          <span
            className="material-symbols-outlined text-primary"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            public
          </span>
          Intelligence Map
        </h1>
        <p className="mt-1 text-sm text-on-surface-variant">
          Geospatial view of intelligence activity.
        </p>
      </div>

      {/* Main content: FilterPanel + MapCanvas */}
      <div className="flex flex-1 overflow-hidden">
        <MapFilterPanel
          layers={layers}
          onLayerToggle={handleLayerToggle}
          severityFilters={severityFilters}
          onSeverityToggle={handleSeverityToggle}
          selectedItem={selectedItem}
          onClearSelection={handleClearSelection}
        />

        {/* Map area */}
        <div className="flex-1 flex flex-col relative">
          <MapCanvas
            markers={filteredMarkers}
            onMarkerClick={handleMarkerClick}
            onBoundsChange={setBounds}
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
          />

          {/* Geo bounds display */}
          {bounds && (
            <div
              className="absolute bottom-4 left-4 z-[1000] bg-surface-container/80 backdrop-blur-sm border border-outline-variant/20 rounded px-2.5 py-1.5 text-[10px] font-mono text-on-surface-variant"
              data-testid="geo-bounds-display"
            >
              {bounds}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
