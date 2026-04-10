import { useState, useEffect, useCallback } from 'react';
import { MapContainer, TileLayer, CircleMarker, useMapEvents } from 'react-leaflet';
import { useNavigate } from 'react-router-dom';
import 'leaflet/dist/leaflet.css';

const STORAGE_KEY = 'osint-minimap-collapsed';

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  type: 'alert' | 'lead' | 'watch';
}

const MARKER_COLORS: Record<MapMarker['type'], string> = {
  alert: '#ef4444',
  lead: '#3b82f6',
  watch: '#22c55e',
};

function getInitialCollapsed(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === null ? true : stored === 'true';
  } catch {
    return true;
  }
}

function ClickToNavigate() {
  const navigate = useNavigate();
  useMapEvents({
    click: () => {
      navigate('/map');
    },
  });
  return null;
}

interface MiniMapProps {
  markers?: MapMarker[];
}

export function MiniMap({ markers = [] }: MiniMapProps) {
  const [collapsed, setCollapsed] = useState(getInitialCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      // localStorage unavailable — ignore
    }
  }, [collapsed]);

  const toggle = useCallback(() => {
    setCollapsed((prev) => !prev);
  }, []);

  if (collapsed) {
    return (
      <div
        className="bg-surface-container-low rounded-lg border border-outline-variant/10 px-4 py-2.5 flex items-center justify-between cursor-pointer hover:bg-surface-container transition-colors"
        onClick={toggle}
        role="button"
        aria-expanded="false"
        aria-label="Expand map"
        data-testid="minimap-collapsed"
      >
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-base text-on-surface-variant">map</span>
          <span className="text-xs text-on-surface-variant">
            Map — {markers.length} active marker{markers.length !== 1 ? 's' : ''}
          </span>
        </div>
        <span className="material-symbols-outlined text-base text-on-surface-variant">
          expand_more
        </span>
      </div>
    );
  }

  return (
    <div
      className="bg-surface-container-low rounded-lg border border-outline-variant/10 overflow-hidden"
      data-testid="minimap-expanded"
    >
      {/* Header bar */}
      <div
        className="px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-surface-container transition-colors"
        onClick={toggle}
        role="button"
        aria-expanded="true"
        aria-label="Collapse map"
      >
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-base text-on-surface-variant">map</span>
          <span className="text-xs text-on-surface-variant">
            Map — {markers.length} active marker{markers.length !== 1 ? 's' : ''}
          </span>
        </div>
        <span className="material-symbols-outlined text-base text-on-surface-variant">
          expand_less
        </span>
      </div>

      {/* Map container */}
      <div className="h-[200px] relative minimap-dark-tiles" style={{ cursor: 'pointer' }}>
        {markers.length === 0 ? (
          <div
            className="h-full flex items-center justify-center"
            style={{ background: '#0a0a0a' }}
            data-testid="minimap-empty"
          >
            <p className="text-xs text-on-surface-variant/60">No geo data available</p>
          </div>
        ) : (
          <MapContainer
            center={[20, 0]}
            zoom={2}
            zoomControl={false}
            attributionControl={false}
            dragging={false}
            scrollWheelZoom={false}
            doubleClickZoom={false}
            touchZoom={false}
            style={{ height: '100%', width: '100%' }}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              className="leaflet-tile-dark"
            />
            <ClickToNavigate />
            {markers.map((marker) => (
              <CircleMarker
                key={marker.id}
                center={[marker.lat, marker.lng]}
                radius={5}
                pathOptions={{
                  fillColor: MARKER_COLORS[marker.type],
                  fillOpacity: 0.9,
                  color: MARKER_COLORS[marker.type],
                  weight: 1,
                }}
              />
            ))}
          </MapContainer>
        )}
      </div>

      {/* Dark tile CSS */}
      <style>{`
        .minimap-dark-tiles .leaflet-tile-dark {
          filter: brightness(0.6) invert(1) contrast(3) hue-rotate(200deg) saturate(0.3) brightness(0.7);
        }
      `}</style>
    </div>
  );
}
