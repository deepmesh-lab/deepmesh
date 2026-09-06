/**
 * 시연용 공격 시나리오 재생.
 *
 * 명세상 대시보드 API는 GET 전용이라 서버에 "재생"을 요청할 수단이 없다.
 * 따라서 이것은 목 저장소에 직접 이벤트를 주입하는, 목 모드 전용 기능이다.
 *
 * 시나리오 1 — 침해된 post Pod가 K8s API Server에 비인가 요청. Request Verifier가 차단(DROP).
 * 시나리오 2 — 침해된 post Pod가 변조된 응답 반환. Response Consistency가 정상 replica 응답으로 대체(RELAY).
 */
import { toKstIso } from '../time'
import type { AlertPayload, DetectionEventDetail } from '../types'
import { emitMockAlert, emitMockDetection } from './mockBus'
import { ensureEdge, recordDetection, takeEventId } from './mockState'
import { MOCK_NAMESPACE, modelIdOf } from './seed'

const COMPROMISED_POD = 'post-6d4f8b9c7d-a1b2c'
const REFERENCE_PODS = ['post-6d4f8b9c7d-d3e4f', 'post-6d4f8b9c7d-g5h6i']
const COMPROMISED_POD_IP = '10.244.1.37'

let playing = false
const playingListeners = new Set<(value: boolean) => void>()

function setPlaying(value: boolean) {
  playing = value
  playingListeners.forEach((listener) => listener(value))
}

export function isScenarioPlaying() {
  return playing
}

export function onScenarioPlayingChange(listener: (value: boolean) => void) {
  playingListeners.add(listener)
  return () => {
    playingListeners.delete(listener)
  }
}

function buildPackets(at: Date) {
  const lengths = [1460, 1460, 812, 1460, 604]
  return lengths.map((length, index) => ({
    seq: index + 1,
    capturedAt: toKstIso(new Date(at.getTime() - (5 - index) * 2)),
    length,
    flags: index % 2 === 1 ? 'ACK' : 'PSH,ACK',
  }))
}

function sessionId() {
  return `s-${Math.random().toString(16).slice(2, 10)}`
}

type ScenarioStep = Omit<
  DetectionEventDetail,
  | 'eventId'
  | 'occurredAt'
  | 'namespace'
  | 'protocol'
  | 'modelVerdict'
  | 'windowSize'
  | 'packets'
  | 'sessionId'
>

function emitStep(step: ScenarioStep, edgeId: string, alert?: Omit<AlertPayload, 'type' | 'eventId' | 'occurredAt'>) {
  const now = new Date()
  const event: DetectionEventDetail = {
    ...step,
    eventId: takeEventId(),
    occurredAt: toKstIso(now),
    namespace: MOCK_NAMESPACE,
    protocol: 'TCP',
    modelVerdict: 'ATTACK',
    sessionId: sessionId(),
    windowSize: 5,
    packets: buildPackets(now),
  }

  recordDetection(event, edgeId)
  // 스트림으로 나가는 것은 목록 스키마다. 상세 필드는 GET /dashboard/events/{id}로만 조회된다.
  const { windowSize: _w, modelId: _m, packets: _p, verification: _v, ...item } = event
  emitMockDetection(item)

  if (alert) {
    emitMockAlert({
      ...alert,
      type: 'ALERT',
      eventId: event.eventId,
      occurredAt: event.occurredAt,
    })
  }
}

function playSteps(count: number, intervalMs: number, step: (index: number) => void) {
  if (playing) {
    return
  }
  setPlaying(true)

  let index = 0
  const timer = window.setInterval(() => {
    step(index)
    index += 1
    if (index >= count) {
      window.clearInterval(timer)
      setPlaying(false)
    }
  }, intervalMs)

  // 첫 이벤트는 기다리지 않고 바로 내보낸다.
  step(index)
  index += 1
}

export function playScenario1() {
  if (playing) {
    return
  }

  // 평소에 없던 통신 경로가 공격 시점에 처음 생성된다 — topology 델타의 addedEdges.
  ensureEdge('post->kubernetes', 'post', 'kubernetes')

  const paths = [
    'GET /api/v1/namespaces/default/pods',
    'GET /api/v1/namespaces/default/services',
    'GET /apis/apps/v1/namespaces/default/replicasets',
    'POST /api/v1/namespaces/default/pods',
  ]

  playSteps(8, 430, (index) => {
    const path = paths[index % paths.length]

    emitStep(
      {
        serviceName: 'post',
        podName: COMPROMISED_POD,
        nodeName: 'worker-1',
        direction: 'REQUEST',
        srcIp: COMPROMISED_POD_IP,
        srcPort: 48800 + index,
        dstIp: '10.96.0.1',
        dstPort: 443,
        peerServiceName: 'kubernetes',
        ocsvmScore: Number((-0.31 - Math.random() * 0.28).toFixed(4)),
        verdict: 'DROP',
        category: 'drop',
        verificationStage: 'REQUEST_VERIFIER',
        verificationPassed: false,
        detectionLatencyMs: Number((0.52 + Math.random() * 0.25).toFixed(2)),
        signature: `${path.split(' ')[0]}|10.96.0.1:443|${path.split(' ')[1]}|q:|b:`,
        summary: `${path} — Request Verifier 미관측 요청`,
        modelId: modelIdOf('post'),
        verification: {
          stage: 'REQUEST_VERIFIER',
          passed: false,
          checkedPods: REFERENCE_PODS,
          detail: `동일 요청(${path})의 이력이 타 replica에 존재하지 않습니다. 이 Pod에서만 관측된 요청이므로 차단했습니다.`,
          elapsedMs: Number((2.4 + Math.random() * 1.6).toFixed(1)),
        },
      },
      'post->kubernetes',
      index === 0
        ? {
            severity: 'HIGH',
            verdict: 'DROP',
            serviceName: 'post',
            podName: COMPROMISED_POD,
            title: '비인가 Kubernetes API 요청 차단',
            message: `${COMPROMISED_POD} 에서 관측되지 않은 요청이 발생하여 차단했습니다.`,
          }
        : undefined,
    )
  })
}

/**
 * 시나리오 3 — 교차 검증이 판정을 뒤집는 경우 (`cleared`).
 *
 * 모델은 ATTACK으로 봤지만 **다른 replica에도 동일 요청 이력이 있어** Request Verifier가
 * 통과시킨다. 논문 §4.2의 오탐 흡수가 실제로 동작했음을 보여주는 유일한 관측 지표다.
 * 평시 트래픽이 없던 `post → comment` 경로가 이때 살아난다.
 *
 * `cleared`는 알림을 발행하지 않는다 — 서비스에 영향이 없었고 시스템이 의도대로 동작했다.
 * (명세 2-2)
 */
export function playScenario3() {
  if (playing) {
    return
  }

  playSteps(6, 480, (index) => {
    const postId = 12 + index

    emitStep(
      {
        serviceName: 'post',
        podName: COMPROMISED_POD,
        nodeName: 'worker-1',
        direction: 'REQUEST',
        srcIp: COMPROMISED_POD_IP,
        srcPort: 51200 + index,
        dstIp: '10.244.3.41',
        dstPort: 8080,
        peerServiceName: 'comment',
        ocsvmScore: Number((-0.06 - Math.random() * 0.09).toFixed(4)),
        verdict: 'FORWARD',
        category: 'cleared',
        verificationStage: 'REQUEST_VERIFIER',
        verificationPassed: true,
        detectionLatencyMs: Number((0.44 + Math.random() * 0.2).toFixed(2)),
        signature: `DELETE|comment-service:8080|/api/comments|q:postId=${postId}|b:`,
        summary: `DELETE /api/comments?postId=${postId} — 타 replica에 동일 요청 이력 존재, 판정이 뒤집힘`,
        modelId: modelIdOf('post'),
        verification: {
          stage: 'REQUEST_VERIFIER',
          passed: true,
          checkedPods: REFERENCE_PODS,
          detail:
            '동일 ReplicaSet의 다른 Pod에서도 같은 요청이 관측되었습니다. 한 Pod에서만 나온 요청이 아니므로 통과시켰습니다. ' +
            '다만 교차 검증 통과가 트래픽의 정상성을 보증하지는 않습니다.',
          elapsedMs: Number((2.1 + Math.random() * 1.4).toFixed(1)),
        },
      },
      'post->comment',
    )
  })
}

export function playScenario2() {
  if (playing) {
    return
  }

  playSteps(7, 530, (index) => {
    // 한 건은 참조 응답과 일치해 판정이 뒤집힌다 — 교차 검증이 오탐을 흡수한 케이스.
    const cleared = index === 2

    emitStep(
      {
        serviceName: 'post',
        podName: COMPROMISED_POD,
        nodeName: 'worker-1',
        direction: 'RESPONSE',
        srcIp: COMPROMISED_POD_IP,
        srcPort: 8081,
        dstIp: '10.244.0.19',
        dstPort: 52310 + index,
        peerServiceName: 'frontend',
        ocsvmScore: Number((-0.22 - Math.random() * 0.3).toFixed(4)),
        verdict: cleared ? 'FORWARD' : 'RELAY',
        category: cleared ? 'cleared' : 'relay',
        verificationStage: 'RESPONSE_CONSISTENCY',
        verificationPassed: cleared,
        detectionLatencyMs: Number((0.49 + Math.random() * 0.22).toFixed(2)),
        signature: 'GET|post-service:8080|/api/posts/12|q:|b:',
        summary: cleared
          ? 'GET /api/posts/12 — 참조 응답과 일치, 판정이 뒤집힘'
          : 'GET /api/posts/12 — 응답 본문 불일치, 정상 replica 응답으로 대체',
        modelId: modelIdOf('post'),
        verification: {
          stage: 'RESPONSE_CONSISTENCY',
          passed: cleared,
          checkedPods: REFERENCE_PODS,
          detail: cleared
            ? '참조 응답과 본문이 일치하여 원본을 그대로 전달했습니다. 교차 검증 통과가 트래픽의 정상성을 보증하지는 않습니다.'
            : '정상 replica의 참조 응답과 본문이 일치하지 않습니다. 원본을 폐기하고 참조 응답으로 대체했습니다.',
          elapsedMs: Number((4.1 + Math.random() * 2).toFixed(1)),
        },
      },
      // 관측 주체는 post의 프록시(egress 응답)이고, 통신 경로는 frontend↔post다.
      // 노드 counts는 serviceName='post'로, 엣지 counts는 이 경로로 각각 집계된다.
      'frontend->post',
      index === 0
        ? {
            severity: 'MEDIUM',
            verdict: 'RELAY',
            serviceName: 'post',
            podName: COMPROMISED_POD,
            title: '변조된 응답을 정상 replica 응답으로 대체',
            message: `${COMPROMISED_POD} 의 응답이 참조 응답과 달라 대체했습니다. 서비스는 정상 유지됩니다.`,
          }
        : undefined,
    )
  })
}
