import { useState, useEffect, useCallback } from 'react';

export function useApi(apiFn, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(() => {
    setLoading(true);
    setError(null);
    const result = apiFn();
    if (!result || typeof result.then !== 'function') {
      setLoading(false);
      return;
    }
    result
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, deps);

  useEffect(() => { refetch(); }, [refetch]);

  return { data, loading, error, refetch };
}
