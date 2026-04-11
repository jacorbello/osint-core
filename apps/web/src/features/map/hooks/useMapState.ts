import { useState, useCallback } from 'react';
import type { LayerType, MapMarkerItem } from '../components/MapFilterPanel';
import type { SeverityEnum } from '@/types/api/common';

export function useMapState() {
  const [layers, setLayers] = useState<Record<LayerType, boolean>>({
    events: true,
  });

  const [severityFilters, setSeverityFilters] = useState<SeverityEnum[]>([]);
  const [selectedItem, setSelectedItem] = useState<MapMarkerItem | null>(null);
  const [bounds, setBounds] = useState<string>('');

  const handleLayerToggle = useCallback((layer: LayerType) => {
    setLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const handleSeverityToggle = useCallback((severity: SeverityEnum) => {
    setSeverityFilters((prev) =>
      prev.includes(severity) ? prev.filter((s) => s !== severity) : [...prev, severity]
    );
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelectedItem(null);
  }, []);

  const handleMarkerClick = useCallback((item: MapMarkerItem) => {
    setSelectedItem(item);
  }, []);

  return {
    layers,
    severityFilters,
    selectedItem,
    bounds,
    handleLayerToggle,
    handleSeverityToggle,
    handleClearSelection,
    handleMarkerClick,
    setBounds,
  };
}
