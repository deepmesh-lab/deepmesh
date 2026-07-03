package com.deepmesh.comment.controller;

import com.deepmesh.comment.dto.*;
import com.deepmesh.comment.service.CommentService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
public class CommentController {

    private final CommentService commentService;

    // ══════ Public API /api/** ══════

    /** GET /api/posts/{postId}/comments — 목록 (Cursor, 기본값 cursor=0 size=20, id 오름차순) */
    @GetMapping("/api/comments/{postId}/comments")     // 전처리 필요
    public ResponseEntity<CommentListResponse> getByPostId(
        @PathVariable Long postId,
        @RequestParam(required = false) Long cursor,
        @RequestParam(required = false) Integer size
    ) {
        return ResponseEntity.ok(commentService.getByPostId(postId, cursor, size));
    }

    /** POST /api/posts/{postId}/comments — 댓글 작성 (postId Path Variable) */
    @PostMapping("/api/comments/{postId}/comments")
    public ResponseEntity<CommentResponse> create(
        @RequestHeader("Authorization") String authHeader,
        @PathVariable Long postId,
        @Valid @RequestBody CommentRequest req
    ) {
        return ResponseEntity.status(HttpStatus.CREATED)
            .body(commentService.create(authHeader, postId, req));
    }

    /** PUT /api/comments/{id} — 댓글 수정 */
    @PutMapping("/api/comments/{id}")
    public ResponseEntity<CommentResponse> update(
        @RequestHeader("Authorization") String authHeader,
        @PathVariable Long id,
        @Valid @RequestBody CommentRequest req
    ) {
        return ResponseEntity.ok(commentService.update(authHeader, id, req));
    }

    /** DELETE /api/comments/{id} — 댓글 삭제 (200 + message + commentId) */
    @DeleteMapping("/api/comments/{id}")
    public ResponseEntity<CommentDeleteResponse> delete(
        @RequestHeader("Authorization") String authHeader,
        @PathVariable Long id
    ) {
        return ResponseEntity.ok(commentService.delete(authHeader, id));
    }

    // ══════ Internal API /internal/** (Post Service → Comment Service) ══════

    /** DELETE /internal/posts/{postId}/comments — 게시글 삭제 시 댓글 일괄 삭제 (204 유지) */
    @DeleteMapping("/internal/posts/{postId}/comments")
    public ResponseEntity<Void> deleteByPostId(@PathVariable Long postId) {
        commentService.deleteByPostId(postId);
        return ResponseEntity.noContent().build();
    }
}
