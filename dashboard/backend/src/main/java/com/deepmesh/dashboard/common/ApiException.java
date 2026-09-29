package com.deepmesh.dashboard.common;

import lombok.Getter;

/** 도메인에서 던지는 에러. GlobalExceptionHandler가 공통 응답으로 변환한다. */
@Getter
public class ApiException extends RuntimeException {

	private final ErrorCode code;

	public ApiException(ErrorCode code, String message) {
		super(message);
		this.code = code;
	}
}
