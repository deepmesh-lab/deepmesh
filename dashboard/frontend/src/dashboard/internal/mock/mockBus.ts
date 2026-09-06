/**
 * 시나리오 재생과 목 스트림 사이의 연결 고리.
 * 시나리오는 이벤트를 저장소에 기록한 뒤 여기로 흘리고, 목 스트림이 이를 배치로 묶어 내보낸다.
 */
import type { AlertPayload, DetectionEvent } from '../types'

type DetectionListener = (event: DetectionEvent) => void
type AlertListener = (alert: AlertPayload) => void

const detectionListeners = new Set<DetectionListener>()
const alertListeners = new Set<AlertListener>()

export function onMockDetection(listener: DetectionListener) {
  detectionListeners.add(listener)
  return () => {
    detectionListeners.delete(listener)
  }
}

export function onMockAlert(listener: AlertListener) {
  alertListeners.add(listener)
  return () => {
    alertListeners.delete(listener)
  }
}

export function emitMockDetection(event: DetectionEvent) {
  detectionListeners.forEach((listener) => listener(event))
}

export function emitMockAlert(alert: AlertPayload) {
  alertListeners.forEach((listener) => listener(alert))
}
