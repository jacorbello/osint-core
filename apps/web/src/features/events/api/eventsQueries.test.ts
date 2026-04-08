import * as eventsApi from './eventsApi';
import {
  eventDetailQueryOptions,
  eventFacetsQueryOptions,
  eventRelatedQueryOptions,
  eventsKeys,
  eventsListQueryOptions,
} from './eventsQueries';

describe('eventsQueries', () => {
  it('creates deterministic keys for identical params', () => {
    const paramsA = { severity: 'high', limit: 50, offset: 0 };
    const paramsB = { offset: 0, limit: 50, severity: 'high' };

    expect(eventsKeys.list(paramsA)).toEqual(eventsKeys.list(paramsB));
  });

  it('changes key when list params change', () => {
    expect(eventsKeys.list({ severity: 'high' })).not.toEqual(
      eventsKeys.list({ severity: 'low' })
    );
  });

  it('normalizes include order for related keys', () => {
    const keyA = eventsKeys.related('evt-1', { include: ['alerts', 'entities'] });
    const keyB = eventsKeys.related('evt-1', { include: ['entities', 'alerts'] });

    expect(keyA).toEqual(keyB);
  });

  it('wires list queryFn to events API', async () => {
    const apiSpy = vi.spyOn(eventsApi, 'getEvents').mockResolvedValue({
      items: [],
      page: { offset: 0, limit: 50, total: 0, has_more: false },
    });

    const params = { limit: 50, offset: 0 };
    const options = eventsListQueryOptions(params);
    await options.queryFn?.({} as never);

    expect(apiSpy).toHaveBeenCalledWith(params);
    apiSpy.mockRestore();
  });

  it('wires facets/detail/related queryFns to events API', async () => {
    const event = {
      id: 'evt-1',
      event_type: 'test',
      source_id: 'src',
      title: null,
      summary: null,
      raw_excerpt: null,
      occurred_at: null,
      ingested_at: new Date().toISOString(),
      score: null,
      severity: null,
      dedupe_fingerprint: 'fp',
      plan_version_id: null,
      country_code: null,
      latitude: null,
      longitude: null,
      region: null,
      source_category: null,
      nlp_relevance: null,
      nlp_summary: null,
      metadata: {},
    };

    const facetsSpy = vi.spyOn(eventsApi, 'getEventFacets').mockResolvedValue({
      facets: {},
      applied_filters: {},
    });
    const detailSpy = vi.spyOn(eventsApi, 'getEvent').mockResolvedValue(event);
    const relatedSpy = vi.spyOn(eventsApi, 'getEventRelated').mockResolvedValue({
      event,
      alerts: [],
      entities: [],
      indicators: [],
      meta: { alert_count: 0, entity_count: 0, indicator_count: 0 },
    });

    await eventFacetsQueryOptions({ severity: 'high' }).queryFn?.({} as never);
    await eventDetailQueryOptions('evt-1').queryFn?.({} as never);
    await eventRelatedQueryOptions('evt-1', { include: ['alerts'] }).queryFn?.({} as never);

    expect(facetsSpy).toHaveBeenCalledWith({ severity: 'high' });
    expect(detailSpy).toHaveBeenCalledWith('evt-1');
    expect(relatedSpy).toHaveBeenCalledWith('evt-1', { include: ['alerts'] });

    facetsSpy.mockRestore();
    detailSpy.mockRestore();
    relatedSpy.mockRestore();
  });
});
