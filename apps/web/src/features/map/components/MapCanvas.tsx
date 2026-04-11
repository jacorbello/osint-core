import { useEffect } from 'react';
import { MapContainer, TileLayer, Marker, ZoomControl, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import type { MapMarkerItem, LayerType } from './MapFilterPanel';
import 'leaflet/dist/leaflet.css';
import './map.css';

/** Color-coded circle markers per data type */
const MARKER_COLORS: Record<LayerType, string> = {
  events: '#3b82f6',    // blue
};

function createIcon(type: LayerType): L.DivIcon {
  const color = MARKER_COLORS[type];
  return L.divIcon({
    className: 'custom-marker',
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid rgba(255,255,255,0.8);box-shadow:0 0 6px ${color}80;" data-marker-type="${type}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

const ICONS: Record<LayerType, L.DivIcon> = {
  events: createIcon('events'),
};

interface MapCanvasProps {
  markers: MapMarkerItem[];
  onMarkerClick: (item: MapMarkerItem) => void;
  onBoundsChange: (bounds: string) => void;
  center: [number, number];
  zoom: number;
}

function formatBounds(map: L.Map): string {
  const b = map.getBounds();
  const fmt = (n: number) => n.toFixed(2);
  return `${fmt(b.getSouth())}, ${fmt(b.getWest())} - ${fmt(b.getNorth())}, ${fmt(b.getEast())}`;
}

function BoundsTracker({ onBoundsChange }: { onBoundsChange: (bounds: string) => void }) {
  const map = useMapEvents({
    moveend: () => onBoundsChange(formatBounds(map)),
    zoomend: () => onBoundsChange(formatBounds(map)),
  });

  useEffect(() => {
    onBoundsChange(formatBounds(map));
  }, [map, onBoundsChange]);

  return null;
}

export function MapCanvas({ markers, onMarkerClick, onBoundsChange, center, zoom }: MapCanvasProps) {
  return (
    <MapContainer
      center={center}
      zoom={zoom}
      zoomControl={false}
      className="flex-1 w-full h-full"
      style={{ background: '#0a0a0a' }}
      data-testid="map-canvas"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        className="dark-tiles"
      />
      <ZoomControl position="topright" />
      <BoundsTracker onBoundsChange={onBoundsChange} />

      {markers.map((item) => (
        <Marker
          key={`${item.type}-${item.id}`}
          position={[item.lat, item.lng]}
          icon={ICONS[item.type]}
          eventHandlers={{
            click: () => onMarkerClick(item),
          }}
        />
      ))}
    </MapContainer>
  );
}
