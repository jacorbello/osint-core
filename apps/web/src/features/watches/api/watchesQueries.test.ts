import * as watchesApi from './watchesApi';
import { watchesKeys, watchesListQueryOptions, watchDetailQueryOptions } from './watchesQueries';

describe('watchesQueries', () => {
  it('creates deterministic keys for identical params', () => {
    const paramsA = { status: 'active' as const, limit: 50, offset: 0 };
    const paramsB = { offset: 0, limit: 50, status: 'active' as const };

    expect(watchesKeys.list(paramsA)).toEqual(watchesKeys.list(paramsB));
  });

  it('changes key when list params change', () => {
    expect(watchesKeys.list({ status: 'active' })).not.toEqual(
      watchesKeys.list({ status: 'paused' })
    );
  });

  it('wires list queryFn to watches API', async () => {
    const apiSpy = vi.spyOn(watchesApi, 'getWatches').mockResolvedValue({
      items: [],
      page: { offset: 0, limit: 50, total: 0, has_more: false },
    });

    const params = { limit: 50, offset: 0 };
    const options = watchesListQueryOptions(params);
    await options.queryFn?.({} as never);

    expect(apiSpy).toHaveBeenCalledWith(params);
    apiSpy.mockRestore();
  });

  it('wires detail queryFn to watches API', async () => {
    const watch = {
      id: 'watch-1',
      name: 'Test Watch',
      watch_type: 'dynamic' as const,
      status: 'active' as const,
      region: null,
      country_codes: null,
      bounding_box: null,
      keywords: ['test'],
      source_filter: null,
      severity_threshold: 'medium' as const,
      plan_id: null,
      ttl_hours: null,
      created_at: new Date().toISOString(),
      expires_at: null,
      promoted_at: null,
      created_by: 'analyst',
    };

    const detailSpy = vi.spyOn(watchesApi, 'getWatch').mockResolvedValue(watch);

    await watchDetailQueryOptions('watch-1').queryFn?.({} as never);

    expect(detailSpy).toHaveBeenCalledWith('watch-1');
    detailSpy.mockRestore();
  });
});
