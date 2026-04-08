import * as leadsApi from './leadsApi';
import { leadsKeys, leadsListQueryOptions } from './leadsQueries';

vi.mock('./leadsApi');

describe('leadsKeys', () => {
  it('returns stable base key', () => {
    expect(leadsKeys.all).toEqual(['leads']);
  });

  it('generates stable list key for same params', () => {
    const a = leadsKeys.list({ limit: 10, status: 'new' });
    const b = leadsKeys.list({ status: 'new', limit: 10 });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it('generates distinct keys for different params', () => {
    const newLeads = leadsKeys.list({ status: 'new' });
    const reviewing = leadsKeys.list({ status: 'reviewing' });
    expect(JSON.stringify(newLeads)).not.toBe(JSON.stringify(reviewing));
  });
});

describe('leadsListQueryOptions', () => {
  it('wires queryFn to getLeads', async () => {
    const getLeadsSpy = vi.spyOn(leadsApi, 'getLeads').mockResolvedValue({
      items: [],
      page: { offset: 0, limit: 10, total: 0, has_more: false },
    });

    const options = leadsListQueryOptions({ limit: 10 });
    await options.queryFn?.({} as never);

    expect(getLeadsSpy).toHaveBeenCalledWith({ limit: 10 });
  });

  it('includes params in query key', () => {
    const options = leadsListQueryOptions({ limit: 10, status: 'new' });
    expect(JSON.stringify(options.queryKey)).toContain('new');
  });
});
