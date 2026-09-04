import { useCallback, useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../../../api/restClient'
import { dashboardApi } from '../client'
import type { DetectionEvent, EventListParams } from '../types'

const PAGE_SIZE = 50

export type EventHistoryState = {
  items: DetectionEvent[]
  hasNext: boolean
  isLoading: boolean
  isLoadingMore: boolean
  error: string | null
  loadMore: () => void
}

/**
 * 커서 기반 페이지네이션. offset을 쓰면 실시간 유입 중 페이지 이동 사이에
 * 신규 이벤트가 앞에 삽입되어 중복·누락이 생긴다. (명세 1-1)
 */
export function useEventHistory(params: EventListParams): EventHistoryState {
  const [items, setItems] = useState<DetectionEvent[]>([])
  const [hasNext, setHasNext] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cursorRef = useRef<string | null>(null)
  const paramsKey = JSON.stringify(params)

  useEffect(() => {
    let cancelled = false
    cursorRef.current = null
    setIsLoading(true)

    dashboardApi
      .getEvents({ ...params, size: PAGE_SIZE })
      .then((response) => {
        if (cancelled) {
          return
        }
        setItems(response.data.items)
        setHasNext(response.data.hasNext)
        cursorRef.current = response.data.nextCursor
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(getErrorMessage(caught))
          setItems([])
          setHasNext(false)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
    // params는 값 기준으로 비교한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey])

  const loadMore = useCallback(() => {
    const cursor = cursorRef.current
    if (!cursor || isLoadingMore) {
      return
    }

    setIsLoadingMore(true)
    dashboardApi
      .getEvents({ ...params, cursor, size: PAGE_SIZE })
      .then((response) => {
        setItems((previous) => [...previous, ...response.data.items])
        setHasNext(response.data.hasNext)
        cursorRef.current = response.data.nextCursor
      })
      .catch((caught: unknown) => setError(getErrorMessage(caught)))
      .finally(() => setIsLoadingMore(false))
  }, [params, isLoadingMore])

  return { items, hasNext, isLoading, isLoadingMore, error, loadMore }
}
