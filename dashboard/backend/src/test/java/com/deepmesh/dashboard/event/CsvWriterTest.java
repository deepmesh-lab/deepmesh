package com.deepmesh.dashboard.event;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class CsvWriterTest {

	@Test
	void 특수문자가_없으면_감싸지_않는다() {
		assertThat(CsvWriter.line("post", "DROP")).isEqualTo("post,DROP\r\n");
	}

	@Test
	void 쉼표가_있으면_큰따옴표로_감싼다() {
		assertThat(CsvWriter.line("a,b")).isEqualTo("\"a,b\"\r\n");
	}

	@Test
	void 큰따옴표는_두_번_써서_이스케이프한다() {
		assertThat(CsvWriter.line("a\"b")).isEqualTo("\"a\"\"b\"\r\n");
	}

	@Test
	void 개행이_있으면_큰따옴표로_감싼다() {
		assertThat(CsvWriter.line("a\nb")).isEqualTo("\"a\nb\"\r\n");
	}

	@Test
	void null은_빈_칸으로_쓴다() {
		assertThat(CsvWriter.line("a", null, "b")).isEqualTo("a,,b\r\n");
	}

	@Test
	void 헤더는_여덟_열이고_service와_peer가_나뉘어_있다() {
		assertThat(CsvWriter.headerLine()).isEqualTo(
				"occurredAt,verdict,serviceName,peerServiceName,podName,direction,"
						+ "ocsvmScore,detectionLatencyMs\r\n");
	}

	@Test
	void BOM은_엑셀이_UTF8로_읽게_하는_한_글자다() {
		assertThat(CsvWriter.BOM).isEqualTo("﻿");
	}
}
