import * as dashboardApi from './dashboardApi';
import { dashboardKeys, dashboardSummaryQueryOptions } from './dashboardQueries';

describe('dashboardQueries', () => {
  it('builds stable summary key', () => {
    expect(dashboardKeys.summary()).toEqual(['dashboard', 'summary']);
  });

  it('wires summary queryFn to dashboard API', async () => {
    const apiSpy = vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue({
      alerts: {},
      watches: {},
      leads: {},
      jobs: {},
      events: { last_24h_count: 0 },
      updated_at: new Date().toISOString(),
    });

    const options = dashboardSummaryQueryOptions();
    await options.queryFn?.({} as never);

    expect(apiSpy).toHaveBeenCalledTimes(1);
    apiSpy.mockRestore();
  });
});
