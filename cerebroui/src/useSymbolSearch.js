import { useEffect, useMemo, useState } from 'react';
import { createSymbolSearch } from './symbolSearch';

export default function useSymbolSearch(markets, limit = 12, minLength = 2) {
  const [state, setState] = useState({ results: [], searching: false, error: null });
  const worker = useMemo(() => createSymbolSearch({ publish: setState }), []);
  const marketKey = markets.join(',');
  useEffect(() => { worker.cancel(); }, [worker, marketKey]);
  useEffect(() => () => worker.cancel(false), [worker]);
  return { ...state,
    run: value => worker.run(value, { markets, limit }),
    schedule: value => worker.schedule(value, { markets, limit, minLength }),
    clear: () => worker.cancel()
  };
}
