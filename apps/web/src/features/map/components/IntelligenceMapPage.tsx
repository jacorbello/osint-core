import { useMemo } from 'react';
import { MapFilterPanel, type MapMarkerItem } from './MapFilterPanel';
import { useEventsListQuery } from '@/features/events/api/eventsQueries';
import { MapCanvas } from './MapCanvas';
import { useMapState } from '../hooks/useMapState';

/** Default center (Washington DC) and zoom */
const DEFAULT_CENTER: [number, number] = [38.9, -77.0];
const DEFAULT_ZOOM = 4;

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

  const { data: eventsData } = useEventsListQuery({ limit: 500 });

  const markers: MapMarkerItem[] = useMemo(() => {
    if (!eventsData?.items) return [];

    return eventsData.items
      .filter((event) => event.latitude != null && event.longitude != null)
      .map((event) => ({
        id: event.id,
        type: 'events' as const,
        title: event.title ?? 'Untitled event',
        severity: event.severity ?? 'medium',
        lat: event.latitude!,
        lng: event.longitude!,
        timestamp: event.occurred_at ?? event.ingested_at,
        summary: event.summary,
      }));
  }, [eventsData]);

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
