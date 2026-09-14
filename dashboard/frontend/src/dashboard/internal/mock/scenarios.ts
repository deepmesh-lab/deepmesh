/**
 * 시연용 공격 시나리오 재생.
 *
 * 명세상 대시보드 API는 GET 전용이라 서버에 "재생"을 요청할 수단이 없다.
 * 따라서 이것은 목 저장소에 직접 이벤트를 주입하는, 목 모드 전용 기능이다.
 *
 * 시연 노트북(`demo/deepmesh_demo.ipynb`)의 공격 시나리오를 그대로 옮긴다.
 *
 * 시나리오 1 — k1. 침해된 auth Pod가 K8s API Server를 정찰(T1613). 정상 앱 Pod는 API 서버를
 *              부르지 않는 flow-OOD라 Request Verifier가 차단(DROP).
 * 시나리오 2 — r1. 침해된 frontend Pod가 XSS를 끼운 index.html을 응답(T1565). Response
 *              Consistency가 정상 replica 응답으로 대체(RELAY).
 *
 * 정상 트래픽은 시나리오가 아니라 배경이다 — mockState의 tick이 흘리고 켜고 끌 수만 있다.
 * 켜져 있는 동안 가끔 정상 판정(FORWARD) 이벤트도 한 건씩 흘린다(아래 emitNormalEvent).
 */
import { toKstIso } from '../time'
import type { AlertPayload, DetectionEventDetail } from '../types'
import { emitMockAlert, emitMockDetection } from './mockBus'
import {
  ensureEdge,
  recordDetection,
  setTickHook,
  takeEventId,
} from './mockState'
import {
  MOCK_EDGES,
  MOCK_NAMESPACE,
  MOCK_NODES,
  modelIdOf,
  podIpOf,
  podNamesOf,
} from './seed'

/**
 * seed의 Pod 이름·IP를 그대로 쓴다. 문자열로 박아 두면 replica 수를 바꿀 때 서비스 상세의
 * Pod와 이벤트의 Pod가 어긋나, 침해 Pod 표시가 엉뚱한 곳에 붙는다.
 *
 * 침해 Pod는 첫 replica다 — mockApi.getServiceDetail이 첫 replica를 침해로 표시한다.
 */
function podOf(serviceName: string, index: number) {
  const node = MOCK_NODES.find((item) => item.id === serviceName)!
  return { name: podNamesOf(node)[index], ip: podIpOf(node, index) }
}

function siblingPodsOf(serviceName: string) {
  const node = MOCK_NODES.find((item) => item.id === serviceName)!
  return podNamesOf(node).slice(1)
}

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
  | 'threshold'
  | 'windowSize'
  | 'packets'
  | 'sessionId'
>

function emitStep(
  step: ScenarioStep,
  edgeId: string,
  alert?: Omit<AlertPayload, 'type' | 'eventId' | 'occurredAt'>,
  modelVerdict: DetectionEventDetail['modelVerdict'] = 'ATTACK',
) {
  const now = new Date()
  const event: DetectionEventDetail = {
    ...step,
    eventId: takeEventId(),
    occurredAt: toKstIso(now),
    namespace: MOCK_NAMESPACE,
    protocol: 'TCP',
    modelVerdict,
    // 목 점수(-0.2 ~ -0.6)가 모두 ATTACK이 되도록 그보다 위에 둔다.
    threshold: -0.05,
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

/**
 * 시나리오 1 — k1: K8s API 정찰 (T1613, :443 flow-OOD).
 *
 * 노트북은 auth Pod 안에서 서비스어카운트 토큰으로 pods·secrets·version을 번갈아 8번
 * 조회한다(HTTP/1.1 keep-alive 한 연결). auth의 정상 트래픽은 mysql과 응답뿐이라
 * apiserver:443은 학습에 없던 흐름이다.
 */
export function playScenario1() {
  if (playing) {
    return
  }

  // 평소에 없던 통신 경로가 공격 시점에 처음 생성된다 — topology 델타의 addedEdges.
  ensureEdge('auth->kubernetes', 'auth', 'kubernetes')

  const attacker = podOf('auth', 0)
  const paths = [
    '/api/v1/namespaces/default/pods',
    '/api/v1/namespaces/default/secrets',
    '/version',
  ]

  playSteps(8, 430, (index) => {
    const path = paths[index % paths.length]

    emitStep(
      {
        serviceName: 'auth',
        podName: attacker.name,
        nodeName: 'worker-1',
        direction: 'REQUEST',
        srcIp: attacker.ip,
        // keep-alive 한 연결이라 출발 포트가 하나다.
        srcPort: 48812,
        dstIp: '10.96.0.1',
        dstPort: 443,
        peerServiceName: 'kubernetes',
        ocsvmScore: Number((-0.31 - Math.random() * 0.28).toFixed(4)),
        verdict: 'DROP',
        category: 'drop',
        verificationStage: 'REQUEST_VERIFIER',
        verificationPassed: false,
        detectionLatencyMs: Number((0.52 + Math.random() * 0.25).toFixed(2)),
        signature: `GET|kubernetes.default.svc:443|${path}|q:|b:`,
        summary: `GET ${path} — Request Verifier 미관측 요청`,
        modelId: modelIdOf('auth'),
        verification: {
          stage: 'REQUEST_VERIFIER',
          passed: false,
          checkedPods: siblingPodsOf('auth'),
          detail: `동일 요청(GET ${path})의 이력이 타 replica에 존재하지 않습니다. 이 Pod에서만 관측된 요청이므로 차단했습니다.`,
          elapsedMs: Number((2.4 + Math.random() * 1.6).toFixed(1)),
        },
      },
      'auth->kubernetes',
      index === 0
        ? {
            severity: 'HIGH',
            verdict: 'DROP',
            serviceName: 'auth',
            podName: attacker.name,
            title: 'Kubernetes API 정찰 차단 (k1)',
            message: `${attacker.name} 에서 Kubernetes API Server로 관측되지 않은 요청이 발생하여 차단했습니다.`,
          }
        : undefined,
    )
  })
}

/**
 * 시나리오 2 — r1: 응답 위조 XSS (T1565).
 *
 * 노트북은 frontend Pod의 index.html 앞에 XSS를 끼워 넣고, post Pod에서 `GET /`을 반복해
 * 변조된 응답을 받게 한다. 판정은 **frontend 사이드카가 내보낸 응답**에 대해 난다.
 *
 * 간선은 `frontend → post`다. 백엔드(TopologyService.buildEdges)는 간선을 "관측한 서비스 →
 * 이벤트의 dstIp"로 만드는데, 응답 이벤트의 dstIp는 응답을 받은 post다. 요청 방향
 * (`post → frontend`)으로 기록하면 실제 백엔드에 붙었을 때와 화살표가 반대가 된다.
 */
export function playScenario2() {
  if (playing) {
    return
  }

  ensureEdge('frontend->post', 'frontend', 'post')

  const attacker = podOf('frontend', 0)
  const client = podOf('post', 0)

  playSteps(5, 530, (index) => {
    emitStep(
      {
        serviceName: 'frontend',
        podName: attacker.name,
        nodeName: 'worker-1',
        direction: 'RESPONSE',
        srcIp: attacker.ip,
        srcPort: 80,
        dstIp: client.ip,
        dstPort: 52310 + index,
        peerServiceName: 'post',
        ocsvmScore: Number((-0.22 - Math.random() * 0.3).toFixed(4)),
        verdict: 'RELAY',
        category: 'relay',
        verificationStage: 'RESPONSE_CONSISTENCY',
        verificationPassed: false,
        detectionLatencyMs: Number((0.49 + Math.random() * 0.22).toFixed(2)),
        signature: 'GET|frontend-service:80|/|q:|b:',
        summary: 'GET / — 응답 본문 불일치(XSS 삽입), 정상 replica 응답으로 대체',
        modelId: modelIdOf('frontend'),
        verification: {
          stage: 'RESPONSE_CONSISTENCY',
          passed: false,
          checkedPods: siblingPodsOf('frontend'),
          detail:
            '정상 replica의 참조 응답과 index.html 본문이 일치하지 않습니다(앞부분에 <script> 삽입). ' +
            '원본을 폐기하고 참조 응답으로 대체했습니다.',
          elapsedMs: Number((4.1 + Math.random() * 2).toFixed(1)),
        },
      },
      // 관측 주체는 frontend의 프록시(egress 응답)이고, 응답이 흘러간 방향은 frontend→post다.
      // 노드 counts는 serviceName='frontend'로, 엣지 counts는 이 경로로 각각 집계된다.
      'frontend->post',
      index === 0
        ? {
            severity: 'MEDIUM',
            verdict: 'RELAY',
            serviceName: 'frontend',
            podName: attacker.name,
            title: '변조된 응답을 정상 replica 응답으로 대체 (r1)',
            message: `${attacker.name} 의 index.html 응답이 참조 응답과 달라 대체했습니다. 서비스는 정상 유지됩니다.`,
          }
        : undefined,
    )
  })
}

// ── 배경 정상 판정 이벤트 ──────────────────────────────────────────────

/** 정상 경로별 요청 모양. msa/backend의 실제 호출(seed.ts MOCK_EDGES 주석)을 따른다. */
const NORMAL_REQUESTS: Record<string, { signature: string; port: number }> = {
  'frontend->auth': { signature: 'POST|auth-service:8080|/api/auth/login|q:|b:', port: 8080 },
  'frontend->post': { signature: 'GET|post-service:8080|/api/posts|q:|b:', port: 8080 },
  'frontend->comment': { signature: 'GET|comment-service:8080|/api/comments|q:postId=12|b:', port: 8080 },
  'post->auth': { signature: 'POST|auth-service:8080|/api/auth/validate|q:|b:', port: 8080 },
  'comment->auth': { signature: 'POST|auth-service:8080|/api/auth/validate|q:|b:', port: 8080 },
  'comment->post': { signature: 'GET|post-service:8080|/api/posts/12|q:|b:', port: 8080 },
  'auth->mysql': { signature: 'TCP|mysql:3306', port: 3306 },
  'post->mysql': { signature: 'TCP|mysql:3306', port: 3306 },
  'comment->mysql': { signature: 'TCP|mysql:3306', port: 3306 },
}

/** mysql은 사이드카가 없어 seed에 IP 대역이 없다. 다른 Pod와 겹치지 않는 값을 쓴다. */
const MYSQL_IP = '10.244.4.10'

/** 평시 트래픽이 있는 경로 중 판정 이벤트를 만들 수 있는 것. external은 관측 주체가 없다. */
const NORMAL_EDGES = MOCK_EDGES.filter(
  (seed) => seed.benignRate > 0 && NORMAL_REQUESTS[seed.id],
)

/** tick(1초)당 정상 판정 이벤트를 흘릴 확률. 피드가 정상 로그로 넘쳐 공격이 묻히지 않을 정도. */
const NORMAL_EVENT_CHANCE = 0.5

const randomIndex = (length: number) => Math.floor(Math.random() * length)

/**
 * 정상 트래픽이 켜진 tick에서 가끔 정상 판정 이벤트를 한 건 흘린다.
 *
 * 토폴로지는 FORWARD **이벤트**가 들어온 경로만 1초간 굵은 실선으로 그린다. 집계(tick의
 * benign)만으로는 그 신호가 없어서, 목에서도 실제처럼 이벤트가 있어야 화면을 확인할 수 있다.
 *
 * 시나리오 재생 중에는 흘리지 않는다 — 공격 이벤트 사이에 정상 로그가 끼면 흐름이 끊겨 보인다.
 * 이벤트 한 건은 recordDetection이 집계에도 1을 더하지만, tick의 benign 수십 건에 비하면 무시할 만하다.
 */
function emitNormalEvent() {
  if (playing || NORMAL_EDGES.length === 0 || Math.random() > NORMAL_EVENT_CHANCE) {
    return
  }

  const seed = NORMAL_EDGES[randomIndex(NORMAL_EDGES.length)]
  const request = NORMAL_REQUESTS[seed.id]
  const sourceNode = MOCK_NODES.find((item) => item.id === seed.source)!
  const targetNode = MOCK_NODES.find((item) => item.id === seed.target)!
  const from = podOf(seed.source, randomIndex(sourceNode.replicaCount))
  const dstIp = targetNode.proxyEnabled
    ? podIpOf(targetNode, randomIndex(targetNode.replicaCount))
    : MYSQL_IP
  const [method, , path] = request.signature.split('|')

  emitStep(
    {
      serviceName: seed.source,
      podName: from.name,
      nodeName: 'worker-2',
      direction: 'REQUEST',
      srcIp: from.ip,
      srcPort: 40000 + randomIndex(20000),
      dstIp,
      dstPort: request.port,
      peerServiceName: seed.target,
      // threshold(-0.05)보다 위 — 모델이 정상으로 본 점수다.
      ocsvmScore: Number((0.02 + Math.random() * 0.3).toFixed(4)),
      verdict: 'FORWARD',
      category: 'benign',
      verificationStage: null,
      verificationPassed: null,
      detectionLatencyMs: Number((0.4 + Math.random() * 0.3).toFixed(2)),
      signature: request.signature,
      summary: `${method} ${path ?? ''} — 정상 판정`.trim(),
      modelId: modelIdOf(seed.source),
      // 정상 판정은 교차 검증을 돌리지 않는다.
      verification: {
        stage: null,
        passed: null,
        checkedPods: [],
        detail: null,
        elapsedMs: null,
      },
    },
    seed.id,
    undefined,
    'BENIGN',
  )
}

setTickHook(emitNormalEvent)
