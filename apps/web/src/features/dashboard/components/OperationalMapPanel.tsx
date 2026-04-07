const SEVERITY_LEGEND = [
  { label: 'Critical', color: 'bg-error' },
  { label: 'High', color: 'bg-tertiary-container' },
  { label: 'Medium', color: 'bg-secondary-container' },
  { label: 'Low', color: 'bg-primary-container' },
] as const;

export function OperationalMapPanel() {
  return (
    <div
      className="flex-1 relative rounded-lg overflow-hidden border border-outline-variant/20 shadow-2xl"
      style={{ background: '#060606' }}
    >
      {/* Grid overlay */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(194,245,255,0.8) 1px, transparent 1px), linear-gradient(90deg, rgba(194,245,255,0.8) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      {/* Center placeholder notice */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-center">
          <span className="material-symbols-outlined text-5xl text-outline/50 mb-3">
            public
          </span>
          <p className="text-[11px] font-bold uppercase tracking-widest text-outline/60">
            Geospatial Map
          </p>
          <p className="text-[10px] text-outline/40 mt-1">Phase 4 — react-leaflet integration</p>
        </div>
      </div>

      {/* Floating zoom controls — bottom-left */}
      <div className="absolute bottom-6 left-6 flex flex-col gap-1.5 z-20">
        <button
          className="w-8 h-8 bg-surface-container/80 backdrop-blur-sm border border-outline-variant/30 rounded text-on-surface-variant hover:bg-surface-container-high transition-colors flex items-center justify-center text-sm font-bold"
          aria-label="Zoom in"
          disabled
        >
          +
        </button>
        <button
          className="w-8 h-8 bg-surface-container/80 backdrop-blur-sm border border-outline-variant/30 rounded text-on-surface-variant hover:bg-surface-container-high transition-colors flex items-center justify-center text-sm font-bold"
          aria-label="Zoom out"
          disabled
        >
          −
        </button>
        <button
          className="w-8 h-8 bg-surface-container/80 backdrop-blur-sm border border-outline-variant/30 rounded text-on-surface-variant hover:bg-surface-container-high transition-colors flex items-center justify-center"
          aria-label="Recenter"
          disabled
        >
          <span className="material-symbols-outlined text-sm">my_location</span>
        </button>
      </div>

      {/* Severity legend — bottom-right */}
      <div className="absolute bottom-6 right-6 z-20 bg-surface-container/80 backdrop-blur-sm border border-outline-variant/20 rounded-lg p-3">
        <p className="text-[8px] font-bold uppercase tracking-widest text-outline mb-2">
          Network Legend
        </p>
        <div className="flex flex-col gap-1.5">
          {SEVERITY_LEGEND.map(({ label, color }) => (
            <div key={label} className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${color}`} />
              <span className="text-[9px] text-on-surface-variant">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
