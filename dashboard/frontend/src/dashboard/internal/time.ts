/**
 * 시각 표기 유틸. 명세 1-1에 따라 모든 문자열은 오프셋 `+09:00`을 명시한 ISO-8601 KST다.
 * 오프셋을 생략하면 브라우저 로컬 타임존으로 해석되어 접속 환경마다 시각이 어긋난다.
 */
import type { IsoDateTime } from './types'

const KST_OFFSET_MINUTES = 9 * 60

function pad(value: number, length = 2) {
  return String(value).padStart(length, '0')
}

/** Date → `2026-08-06T13:21:07.482+09:00` */
export function toKstIso(date: Date): IsoDateTime {
  const shifted = new Date(
    date.getTime() + (KST_OFFSET_MINUTES + date.getTimezoneOffset()) * 60_000,
  )

  return (
    `${shifted.getFullYear()}-${pad(shifted.getMonth() + 1)}-${pad(shifted.getDate())}` +
    `T${pad(shifted.getHours())}:${pad(shifted.getMinutes())}:${pad(shifted.getSeconds())}` +
    `.${pad(shifted.getMilliseconds(), 3)}+09:00`
  )
}

/** 오프셋이 붙어 있으므로 Date 생성자가 그대로 해석한다. */
export function fromIso(value: IsoDateTime): Date {
  return new Date(value)
}

/** `13:21:07` — 피드·차트 축 표기용 */
export function formatKstTime(value: IsoDateTime): string {
  return toKstIso(fromIso(value)).slice(11, 19)
}

/** `08-06 13:21:07` — 이력 조회용 */
export function formatKstDateTime(value: IsoDateTime): string {
  const iso = toKstIso(fromIso(value))
  return `${iso.slice(5, 10)} ${iso.slice(11, 19)}`
}

/** `2026-08-06 13:21:07` — 헤더 시계용. 연·월·일까지 붙인다. */
export function formatKstStamp(value: IsoDateTime): string {
  const iso = toKstIso(fromIso(value))
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}`
}

/** `<input type="datetime-local">` 값 ↔ KST ISO 변환 */
export function toDateTimeLocalValue(value: IsoDateTime): string {
  return toKstIso(fromIso(value)).slice(0, 16)
}

export function fromDateTimeLocalValue(value: string): IsoDateTime {
  // datetime-local은 오프셋이 없다. 명세대로 KST로 간주한다.
  return `${value}:00.000+09:00`
}

export function nowKstIso(): IsoDateTime {
  return toKstIso(new Date())
}

const TIME_RANGE_MS: Record<string, number> = {
  '1m': 60_000,
  '5m': 5 * 60_000,
  '15m': 15 * 60_000,
  '1h': 60 * 60_000,
  '24h': 24 * 60 * 60_000,
}

export function timeRangeToMs(timeRange: string): number {
  return TIME_RANGE_MS[timeRange] ?? TIME_RANGE_MS['5m']
}

const INTERVAL_MS: Record<string, number> = {
  '10s': 10_000,
  '1m': 60_000,
  '5m': 5 * 60_000,
}

export function intervalToMs(interval: string): number {
  return INTERVAL_MS[interval] ?? INTERVAL_MS['1m']
}
