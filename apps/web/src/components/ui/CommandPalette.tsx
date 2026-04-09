import { Command } from 'cmdk';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAlertsQuery } from '@/features/alerts/api/alertsQueries';
import { useLeadsQuery } from '@/features/leads/api/leadsQueries';

interface NavigationItem {
  path: string;
  label: string;
  icon: string;
}

const NAVIGATION_ITEMS: NavigationItem[] = [
  { path: '/', label: 'Overview', icon: 'dashboard' },
  { path: '/watches', label: 'Watches', icon: 'visibility' },
  { path: '/alerts', label: 'Alerts', icon: 'notifications_active' },
  { path: '/leads', label: 'Leads', icon: 'trending_up' },
  { path: '/map', label: 'Intelligence Map', icon: 'map' },
  { path: '/settings', label: 'Settings', icon: 'settings' },
];

const ACTION_ITEMS = [
  { id: 'create-watch', label: 'Create Watch', icon: 'add_circle' },
  { id: 'export-data', label: 'Export Data', icon: 'download' },
];

function useDebouncedValue(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => clearTimeout(timerRef.current);
  }, [value, delay]);

  return debounced;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const debouncedSearch = useDebouncedValue(search, 300);
  const trimmedSearch = debouncedSearch.trim();

  const { data: alertsData } = useAlertsQuery(
    trimmedSearch ? { limit: 5 } : { limit: 0 },
  );

  const { data: leadsData } = useLeadsQuery(
    trimmedSearch ? { limit: 5 } : { limit: 0 },
  );

  // Filter alerts/leads by search term client-side
  const filteredAlerts = useMemo(
    () =>
      trimmedSearch
        ? (alertsData?.items ?? []).filter((a) =>
            a.title.toLowerCase().includes(trimmedSearch.toLowerCase()),
          )
        : [],
    [alertsData, trimmedSearch],
  );

  const filteredLeads = useMemo(
    () =>
      trimmedSearch
        ? (leadsData?.items ?? []).filter((l) =>
            l.title.toLowerCase().includes(trimmedSearch.toLowerCase()),
          )
        : [],
    [leadsData, trimmedSearch],
  );

  // Keyboard shortcut
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setSearch('');
    }
  }, []);

  const handleSelect = useCallback(
    (value: string) => {
      handleOpenChange(false);
      if (value.startsWith('/')) {
        navigate(value);
      }
      // Action items are placeholders for now
    },
    [navigate, handleOpenChange],
  );

  return (
    <Command.Dialog
      open={open}
      onOpenChange={handleOpenChange}
      label="Command palette"
      shouldFilter={true}
      className="fixed inset-0 z-50"
      data-testid="command-palette"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50"
        aria-hidden="true"
        data-testid="command-palette-backdrop"
      />

      {/* Dialog */}
      <div className="fixed inset-0 flex items-start justify-center pt-[20vh]">
        <div className="w-full max-w-lg bg-surface-low border border-surface-border rounded-lg shadow-2xl overflow-hidden">
          <Command.Input
            ref={inputRef}
            value={search}
            onValueChange={setSearch}
            placeholder="Search or type a command..."
            className="w-full px-4 py-3 text-sm text-text-primary bg-transparent border-b border-surface-border outline-none placeholder:text-text-muted font-body"
            data-testid="command-palette-input"
          />

          <Command.List className="max-h-[300px] overflow-y-auto p-2">
            <Command.Empty className="px-4 py-8 text-center text-sm text-text-muted font-body">
              {search ? 'No results found.' : 'Start typing to search...'}
            </Command.Empty>

            {/* Navigation group */}
            <Command.Group
              heading="Navigation"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-bold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-text-muted"
            >
              {NAVIGATION_ITEMS.map((item) => (
                <Command.Item
                  key={item.path}
                  value={`nav-${item.label}`}
                  onSelect={() => handleSelect(item.path)}
                  className="flex items-center gap-3 px-3 py-2 rounded text-sm text-text-primary cursor-pointer data-[selected=true]:bg-surface-container-high font-body"
                  data-testid={`command-item-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
                >
                  <span
                    className="material-symbols-outlined text-text-muted"
                    style={{ fontSize: 18 }}
                  >
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </Command.Item>
              ))}
            </Command.Group>

            {/* Alerts group - only when searching */}
            {filteredAlerts.length > 0 && (
              <Command.Group
                heading="Alerts"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-bold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-text-muted"
              >
                {filteredAlerts.map((alert) => (
                  <Command.Item
                    key={alert.id}
                    value={`alert-${alert.title}`}
                    onSelect={() => handleSelect(`/alerts`)}
                    className="flex items-center gap-3 px-3 py-2 rounded text-sm text-text-primary cursor-pointer data-[selected=true]:bg-surface-container-high font-body"
                  >
                    <span
                      className="material-symbols-outlined text-text-muted"
                      style={{ fontSize: 18 }}
                    >
                      notifications_active
                    </span>
                    <span className="truncate">{alert.title}</span>
                    <span className="ml-auto text-xs text-text-muted capitalize">
                      {alert.severity}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Leads group - only when searching */}
            {filteredLeads.length > 0 && (
              <Command.Group
                heading="Leads"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-bold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-text-muted"
              >
                {filteredLeads.map((lead) => (
                  <Command.Item
                    key={lead.id}
                    value={`lead-${lead.title}`}
                    onSelect={() => handleSelect(`/leads`)}
                    className="flex items-center gap-3 px-3 py-2 rounded text-sm text-text-primary cursor-pointer data-[selected=true]:bg-surface-container-high font-body"
                  >
                    <span
                      className="material-symbols-outlined text-text-muted"
                      style={{ fontSize: 18 }}
                    >
                      trending_up
                    </span>
                    <span className="truncate">{lead.title}</span>
                    <span className="ml-auto text-xs text-text-muted capitalize">
                      {lead.status}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Actions group */}
            <Command.Group
              heading="Actions"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-bold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-text-muted"
            >
              {ACTION_ITEMS.map((item) => (
                <Command.Item
                  key={item.id}
                  value={`action-${item.label}`}
                  onSelect={() => handleSelect(`/${item.id}`)}
                  className="flex items-center gap-3 px-3 py-2 rounded text-sm text-text-primary cursor-pointer data-[selected=true]:bg-surface-container-high font-body"
                >
                  <span
                    className="material-symbols-outlined text-text-muted"
                    style={{ fontSize: 18 }}
                  >
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </Command.Item>
              ))}
            </Command.Group>
          </Command.List>
        </div>
      </div>
    </Command.Dialog>
  );
}
