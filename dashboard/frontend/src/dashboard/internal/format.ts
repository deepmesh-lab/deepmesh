/**
 * 백엔드가 채우지 못한 수치는 null로 온다. 그대로 `.toFixed()`를 부르면 렌더가 죽고,
 * ErrorBoundary가 없는 자리라면 화면이 통째로 빈다.
 *
 * null은 null로 돌려준다. 0으로 대체하지 않는다 — "값이 없음"과 "0"은 다르다.
 * 어떻게 보여줄지는 부르는 쪽이 정한다. 상세 대화상자는 KeyValue의 `null` 배지를 그대로
 * 쓰고(응답을 있는 그대로 보여주는 자리다), 목록 표는 대시(—)로 바꾼다.
 */
export function fixed(value: number | null | undefined, digits: number) {
  return value === null || value === undefined ? null : value.toFixed(digits)
}

/**
 * 판정 시그니처를 사람이 읽는 조각으로 나눈다.
 *
 * 프록시가 `메서드|대상|경로|q:쿼리|b:본문힌트` 로 만든다. 형식이 다르면 통째로
 * `경로`에 담아 그대로 보여준다 — 파싱에 실패했다고 정보를 버리지 않는다.
 */
export function parseSignature(signature: string | null): {
  method: string | null
  target: string | null
  path: string
  query: string | null
} | null {
  if (!signature) {
    return null
  }
  const parts = signature.split('|')
  if (parts.length < 3) {
    return { method: null, target: null, path: signature, query: null }
  }
  const [method, target, path, ...rest] = parts
  const query = rest.find((part) => part.startsWith('q:'))?.slice(2) ?? null
  return {
    method,
    target,
    path,
    query: query && query.length > 0 ? query : null,
  }
}
