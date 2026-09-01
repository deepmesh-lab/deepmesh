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
