import { useCallback, useEffect, useRef, useState } from 'react'
import type { RestResponse } from '../../../api/restClient'
import { getErrorMessage } from '../../../api/restClient'

export type PolledResource<T> = {
  data: T | null
  error: string | null
  errorCode: string | null
  isLoading: boolean
  refresh: () => void
}

/**
 * REST 스냅샷을 주기적으로 다시 읽는다.
 *
 * 요약·서비스별 분포·시계열은 timeRange 기준 집계라 스트림의 STATS_TICK(rolling 1m)으로
 * 대체할 수 없다. 관리자 소수가 보는 화면이라 폴링 비용이 문제가 되지 않는다.
 *
 * `resetKey`가 바뀌면 주기를 기다리지 않고 즉시 다시 읽는다 (timeRange 변경 등).
 */
export function usePolledResource<T>(
  fetcher: () => Promise<RestResponse<T>>,
  intervalMs: number,
  resetKey = '',
  enabled = true,
): PolledResource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)

  fetcherRef.current = fetcher

  const refresh = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) {
      return
    }

    let cancelled = false

    async function load() {
      try {
        const response = await fetcherRef.current()
        if (cancelled) {
          return
        }
        setData(response.data)
        setError(null)
        setErrorCode(null)
      } catch (caught) {
        if (cancelled) {
          return
        }
        const body = (caught as { data?: { code?: string } })?.data
        setError(getErrorMessage(caught))
        setErrorCode(body?.code ?? null)
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    load()
    const timer = window.setInterval(load, intervalMs)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [intervalMs, enabled, nonce, resetKey])

  return { data, error, errorCode, isLoading, refresh }
}
