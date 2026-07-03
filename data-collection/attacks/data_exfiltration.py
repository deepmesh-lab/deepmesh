"""
MITRE ATT&CK: T1041 - Exfiltration Over C2 Channel (Data Exfiltration)
연구 목적 침입 탐지 테스트용 스크립트
사용법: python data_exfiltration.py --host http://<TARGET> [--pages N] [--delay FLOAT]
"""
import argparse
import requests
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PAGE_SIZE = 100


def scrape_post_list(base_url: str, page: int, delay: float) -> list:
    """페이지 단위로 게시물 목록 스크래핑."""
    url = f"{base_url}/api/posts"
    params = {"page": page, "size": PAGE_SIZE}
    try:
        resp = requests.get(url, params=params, timeout=10)
        logger.info(
            "LIST page=%d status=%d content_length=%d",
            page, resp.status_code, len(resp.content),
        )
        if resp.status_code == 200:
            data = resp.json()
            # Spring Page 응답 또는 단순 리스트 모두 처리
            if isinstance(data, dict):
                content = data.get("content", data.get("data", []))
            elif isinstance(data, list):
                content = data
            else:
                content = []
            ids = [item.get("id") or item.get("postId") for item in content if isinstance(item, dict)]
            return [pid for pid in ids if pid is not None]
    except requests.RequestException as exc:
        logger.error("LIST page=%d 오류 — %s", page, exc)
    finally:
        time.sleep(delay)
    return []


def scrape_post_detail(base_url: str, post_id, delay: float) -> None:
    """개별 게시물 상세 데이터 추출."""
    url = f"{base_url}/api/posts/{post_id}"
    try:
        resp = requests.get(url, timeout=10)
        logger.info(
            "DETAIL post_id=%s status=%d content_length=%d",
            post_id, resp.status_code, len(resp.content),
        )
    except requests.RequestException as exc:
        logger.error("DETAIL post_id=%s 오류 — %s", post_id, exc)
    finally:
        time.sleep(delay)


def run(host: str, pages: int, delay: float) -> None:
    base_url = host.rstrip("/")
    logger.info(
        "T1041 Data Exfiltration 시작 — 대상: %s, 페이지 수: %d, page_size: %d",
        base_url, pages, PAGE_SIZE,
    )

    all_ids: list = []

    # 1단계: 목록 대량 스크래핑
    logger.info("=== 1단계: 게시물 목록 스크래핑 ===")
    for page in range(pages):
        ids = scrape_post_list(base_url, page, delay)
        all_ids.extend(ids)
        logger.debug("page=%d 수집 id 수: %d", page, len(ids))

    logger.info("목록 스크래핑 완료 — 수집된 post id 수: %d", len(all_ids))

    # 2단계: 개별 상세 데이터 추출
    logger.info("=== 2단계: 개별 게시물 상세 추출 ===")
    unique_ids = list(dict.fromkeys(all_ids))  # 순서 유지 중복 제거
    for post_id in unique_ids:
        scrape_post_detail(base_url, post_id, delay)

    # 3단계: 추가 엔드포인트 스크래핑
    logger.info("=== 3단계: 추가 엔드포인트 스크래핑 ===")
    extra_endpoints = [
        "/api/auth/users",
        "/api/posts/recent",
        "/api/posts/popular",
        "/api/comments",
    ]
    for endpoint in extra_endpoints:
        url = f"{base_url}{endpoint}"
        try:
            resp = requests.get(url, timeout=10)
            logger.info(
                "EXTRA %s status=%d content_length=%d",
                endpoint, resp.status_code, len(resp.content),
            )
        except requests.RequestException as exc:
            logger.error("EXTRA %s 오류 — %s", endpoint, exc)
        time.sleep(delay)

    logger.info(
        "완료 — 목록 %d 페이지 스크래핑, 상세 %d건 추출",
        pages, len(unique_ids),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T1041 Data Exfiltration 침입 탐지 테스트 스크립트"
    )
    parser.add_argument("--host", required=True, help="대상 호스트 URL (예: http://192.168.1.1)")
    parser.add_argument("--pages", type=int, default=50, help="스크래핑할 페이지 수 (기본값: 50)")
    parser.add_argument("--delay", type=float, default=0.01, help="요청 간격(초) (기본값: 0.01)")
    args = parser.parse_args()

    run(args.host, args.pages, args.delay)


if __name__ == "__main__":
    main()
