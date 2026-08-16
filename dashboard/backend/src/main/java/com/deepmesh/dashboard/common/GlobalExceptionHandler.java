package com.deepmesh.dashboard.common;

import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/** backend-frontend-api.md 공통 에러 응답 형식으로 예외를 변환한다. */
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

	@ExceptionHandler(ApiException.class)
	public ResponseEntity<Map<String, Object>> handleApi(ApiException exc, HttpServletRequest req) {
		return build(exc.getCode(), exc.getMessage(), req);
	}

	@ExceptionHandler({
			MethodArgumentNotValidException.class,
			MissingServletRequestParameterException.class,
			MethodArgumentTypeMismatchException.class,
			IllegalArgumentException.class
	})
	public ResponseEntity<Map<String, Object>> handleBadRequest(Exception exc, HttpServletRequest req) {
		return build(ErrorCode.INVALID_PARAMETER, exc.getMessage(), req);
	}

	@ExceptionHandler(Exception.class)
	public ResponseEntity<Map<String, Object>> handleUnexpected(Exception exc, HttpServletRequest req) {
		log.error("처리되지 않은 예외", exc);
		return build(ErrorCode.INTERNAL_ERROR, "서버 내부 오류가 발생했습니다.", req);
	}

	private ResponseEntity<Map<String, Object>> build(ErrorCode code, String message, HttpServletRequest req) {
		Map<String, Object> body = new LinkedHashMap<>();
		body.put("timestamp", OffsetDateTime.now().toString());
		body.put("status", code.status().value());
		body.put("code", code.name());
		body.put("message", message);
		body.put("path", req.getRequestURI());
		return ResponseEntity.status(code.status()).body(body);
	}
}
