package com.deepmesh.post.controller;

import com.deepmesh.post.dto.*;
import com.deepmesh.post.service.PostService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
public class PostController {

    private final PostService postService;

    // ══════ Public API /api/posts/** ══════

    /** GET /api/posts — 목록 조회 (Offset, 기본값 page=1 size=20, id 내림차순) */
    @GetMapping("/api/posts")
    public ResponseEntity<PostListResponse> getAll(
        @RequestParam(required = false) Integer page,
        @RequestParam(required = false) Integer size
    ) {
        return ResponseEntity.ok(postService.getAll(page, size));
    }

    /** GET /api/posts/{id} — 단건 조회 */
    @GetMapping("/api/posts/{id}")
    public ResponseEntity<PostResponse> getOne(@PathVariable Long id) {
        return ResponseEntity.ok(postService.getOne(id));
    }

    /** POST /api/posts — 게시글 작성 */
    @PostMapping("/api/posts")
    public ResponseEntity<PostResponse> create(
            @RequestHeader("Authorization") String authHeader,
            @Valid @RequestBody PostRequest req   // @Valid 추가
    ) {
        return ResponseEntity.status(HttpStatus.CREATED).body(postService.create(authHeader, req));
    }

    /** PUT /api/posts/{id} — 게시글 수정 */
    @PutMapping("/api/posts/{id}")
    public ResponseEntity<PostResponse> update(
        @RequestHeader("Authorization") String authHeader,
        @PathVariable Long id,
        @Valid @RequestBody PostRequest req
    ) {
        return ResponseEntity.ok(postService.update(authHeader, id, req));
    }

    /** DELETE /api/posts/{id} — 게시글 삭제 (200 + message + postId) */
    @DeleteMapping("/api/posts/{id}")
    public ResponseEntity<PostDeleteResponse> delete(
        @RequestHeader("Authorization") String authHeader,
        @PathVariable Long id
    ) {
        return ResponseEntity.ok(postService.delete(authHeader, id));
    }

    // ══════ Internal API /internal/** (Comment Service → Post Service) ══════

    /** GET /internal/posts/{postId}/exists — 게시글 존재 여부 확인 */
    @GetMapping("/internal/posts/{postId}/exists")
    public ResponseEntity<PostExistsResponse> exists(@PathVariable Long postId) {
        return ResponseEntity.ok(postService.exists(postId));
    }
}
