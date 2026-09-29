import { useEffect, useState } from 'react'
import { dashboardApi } from '../client'
import type { DashboardStream, DetectionEvent } from '../types'

const FEED_LIMIT = 80

/**
 * 피드 상한과 별도로 남겨 두는 공격 이벤트(drop·relay) 수.
 *
 * 정상 판정(FORWARD)도 이벤트로 오면서 80건은 몇 분이면 정상 로그로 가득 찬다. 그러면 방금
 * 차단한 사건이 피드에서 밀려나고, 토폴로지는 그 이벤트로 Pod끼리 잇던 공격선을 서비스
 * 상자끼리로 되돌린다. 공격은 드물고 중요하므로 최신 80건 밖이어도 이만큼은 붙잡아 둔다.
 */
const ATTACK_KEEP = 50

function isAttack(event: DetectionEvent) {
  return event.category === 'drop' || event.category === 'relay'
}

/**
 * 최신순 목록을 자른다. 최신 FEED_LIMIT건 + 그 밖의 최근 공격 ATTACK_KEEP건.
 * 원래 순서(최신순)는 그대로 둔다 — 공격만 따로 앞에 모으면 시간 순서가 깨진다.
 */
function trimFeed(events: DetectionEvent[]): DetectionEvent[] {
  const kept = new Set(events.slice(0, FEED_LIMIT).map((event) => event.eventId))
  events
    .filter(isAttack)
    .slice(0, ATTACK_KEEP)
    .forEach((event) => kept.add(event.eventId))
  return events.filter((event) => kept.has(event.eventId))
}

export type DetectionFeedState = {
  events: DetectionEvent[]
  /** 배치 상한 초과 또는 재전송 상한으로 화면에 오지 못한 건수 */
  omittedCount: number
  isLoading: boolean
  error: string | null
}

/**
 * 초기 50건은 REST로, 이후는 스트림의 detection 배치로 채운다.
 * 프록시가 정상 판정도 개별 이벤트로 남기므로 FORWARD(benign) 이벤트도 함께 온다.
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
        return trimFeed([...fresh.reverse(), ...previous])
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
