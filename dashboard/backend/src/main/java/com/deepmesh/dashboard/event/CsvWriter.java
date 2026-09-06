package com.deepmesh.dashboard.event;

import java.util.List;

/**
 * CSV 한 줄을 만든다. DB와 HTTP를 모른다.
 *
 * <p>엑셀에서 바로 열리는 것을 목표로 한다. 줄바꿈은 CRLF이고, 파일 맨 앞에는 {@link #BOM}을
 * 한 번 쓴다 — BOM이 없으면 엑셀이 UTF-8로 읽지 않아 한글이 깨진다.
 */
public final class CsvWriter {

	/** 파일 맨 앞에 한 번만 쓴다. */
	public static final String BOM = "﻿";

	private static final String EOL = "\r\n";

	/**
	 * 화면 표와 같되 {@code service → peer} 한 칸만 두 열로 나눈다. 화살표가 낀 한 칸은
	 * 엑셀에서 필터와 피벗이 걸리지 않는다.
	 *
	 * <p>eventId는 넣지 않는다. BIGINT 문자열이라 엑셀이 지수 표기로 바꾸며 정밀도를 날린다.
	 */
	private static final List<String> HEADERS = List.of(
			"occurredAt", "verdict", "serviceName", "peerServiceName",
			"podName", "direction", "ocsvmScore", "detectionLatencyMs");

	private CsvWriter() {
	}

	public static String headerLine() {
		return line(HEADERS.toArray());
	}

	public static String line(Object... values) {
		StringBuilder sb = new StringBuilder();
		for (int i = 0; i < values.length; i++) {
			if (i > 0) {
				sb.append(',');
			}
			sb.append(escape(values[i]));
		}
		return sb.append(EOL).toString();
	}

	private static String escape(Object value) {
		if (value == null) {
			return "";
		}
		String text = value.toString();
		boolean plain = text.indexOf('"') < 0 && text.indexOf(',') < 0
				&& text.indexOf('\n') < 0 && text.indexOf('\r') < 0;
		if (plain) {
			return text;
		}
		return '"' + text.replace("\"", "\"\"") + '"';
	}
}
