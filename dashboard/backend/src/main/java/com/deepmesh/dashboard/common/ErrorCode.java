package com.deepmesh.dashboard.common;

import org.springframework.http.HttpStatus;

/** backend-frontend-api.md 공통 에러 응답의 code 체계. 프론트 분기는 이 값으로 한다. */
public enum ErrorCode {

	INVALID_PARAMETER(HttpStatus.BAD_REQUEST),
	INVALID_TIME_RANGE(HttpStatus.BAD_REQUEST),
	CONFLICTING_PARAMETER(HttpStatus.BAD_REQUEST),
	EVENT_NOT_FOUND(HttpStatus.NOT_FOUND),
	SERVICE_NOT_FOUND(HttpStatus.NOT_FOUND),
	INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR),
	DATA_SOURCE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE);

	private final HttpStatus status;

	ErrorCode(HttpStatus status) {
		this.status = status;
	}

	public HttpStatus status() {
		return status;
	}
}
