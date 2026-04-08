import * as alertsApi from './alertsApi';
import { alertsKeys, alertsListQueryOptions } from './alertsQueries';

vi.mock('./alertsApi');

describe('alertsKeys', () => {
  it('returns stable base key', () => {
    expect(alertsKeys.all).toEqual(['alerts']);
  });

  it('generates stable list key for same params', () => {
    const a = alertsKeys.list({ limit: 10, status: 'open' });
    const b = alertsKeys.list({ status: 'open', limit: 10 });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it('generates distinct keys for different params', () => {
    const open = alertsKeys.list({ status: 'open' });
    const acked = alertsKeys.list({ status: 'acked' });
    expect(JSON.stringify(open)).not.toBe(JSON.stringify(acked));
  });
});

describe('alertsListQueryOptions', () => {
  it('wires queryFn to getAlerts', async () => {
    const getAlertsSpy = vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue({
      items: [],
      page: { offset: 0, limit: 10, total: 0, has_more: false },
    });

    const options = alertsListQueryOptions({ limit: 10 });
    await options.queryFn?.({} as never);

    expect(getAlertsSpy).toHaveBeenCalledWith({ limit: 10 });
  });

  it('includes params in query key', () => {
    const options = alertsListQueryOptions({ limit: 10, status: 'open' });
    const key = options.queryKey;
    expect(JSON.stringify(key)).toContain('open');
  });
});
