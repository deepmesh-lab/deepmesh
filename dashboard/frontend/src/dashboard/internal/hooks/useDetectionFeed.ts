import { useEffect, useState } from 'react'
import { dashboardApi } from '../client'
import type { DashboardStream, DetectionEvent } from '../types'

const FEED_LIMIT = 80

export type DetectionFeedState = {
  events: DetectionEvent[]
  /** 배치 상한 초과 또는 재전송 상한으로 화면에 오지 못한 건수 */
  omittedCount: number
  isLoading: boolean
  error: string | null
}

/**
 * 초기 50건은 REST로, 이후는 스트림의 detection 배치로 채운다.
 * BENIGN 트래픽은 개별 이벤트로 저장되지 않으므로 여기 나타나지 않는다. (명세 1-7)
 */
export function useDetectionFeed(
  stream: DashboardStream | null,
): DetectionFeedState {
  const [events, setEvents] = useState<DetectionEvent[]>([])
  const [omittedCount, setOmittedCount] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    dashboardApi
      .getEvents({ size: 50 })
      .then((response) => {
        if (!cancelled) {
          setEvents(response.data.items)
          setError(null)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(
            caught instanceof Error ? caught.message : '이벤트를 불러오지 못했습니다.',
          )
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
  }, [])

  useEffect(() => {
    if (!stream) {
      return
    }

    const unsubscribeDetection = stream.subscribe('detection', (payload) => {
      setEvents((previous) => {
        const known = new Set(previous.map((event) => event.eventId))
        const fresh = payload.events.filter((event) => !known.has(event.eventId))
        return [...fresh.reverse(), ...previous].slice(0, FEED_LIMIT)
      })

      if (payload.droppedCount > 0) {
        setOmittedCount((value) => value + payload.droppedCount)
      }
    })

    // 재전송 상한을 넘긴 단절 구간. 사용자에게 "n건 생략됨"으로 알린다. (명세 2-3)
    const unsubscribeGap = stream.subscribe('gap', (payload) => {
      setOmittedCount((value) => value + payload.missedCount)
    })

    return () => {
      unsubscribeDetection()
      unsubscribeGap()
    }
  }, [stream])

  return { events, omittedCount, isLoading, error }
}
