package com.deepmesh.comment.service;

import com.deepmesh.comment.config.AuthClient;
import com.deepmesh.comment.config.PostClient;
import com.deepmesh.comment.dto.*;
import com.deepmesh.comment.entity.Comment;
import com.deepmesh.comment.exception.ApiException;
import com.deepmesh.comment.repository.CommentRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class CommentService {

    private final CommentRepository commentRepo;
    private final AuthClient authClient;
    private final PostClient postClient;

    private static final int MAX_SIZE = 50;

    // ── 댓글 목록 — Cursor 기반 (기본값 cursor=0, size=20) ────
    public CommentListResponse getByPostId(Long postId, Long cursor, Integer size) {
        // MODIFY : NOT_FOUND, BAD_REQUEST
        if (!postClient.exists(postId)) {
            throw new ApiException(HttpStatus.NOT_FOUND, "POST_NOT_FOUND", "요청한 게시글을 찾을 수 없습니다.");
        }
        long c = (cursor == null) ? 0L : cursor;
        int s = (size == null) ? 20 : size;

        if (c < 0) throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_PARAM", "cursor는 0 이상이어야 합니다.");
        if (s < 1) throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_PARAM", "size는 1 이상이어야 합니다.");

        s = Math.min(s, MAX_SIZE);   // size 상한 50

        // size+1개 조회 → hasNext 판단
        Pageable pageable = PageRequest.of(0, s + 1);
        List<Comment> comments = (c == 0L)
            ? commentRepo.findByPostIdOrderByIdAsc(postId, pageable)
            : commentRepo.findByPostIdAndIdGreaterThanOrderByIdAsc(postId, c, pageable);

        boolean hasNext = comments.size() > s;
        if (hasNext) comments = comments.subList(0, s);

        CommentListResponse response = new CommentListResponse();
        response.setPostId(postId);
        response.setSize(s);
        response.setHasNext(hasNext);
        response.setNextCursor(hasNext ? comments.get(comments.size() - 1).getId() : null);
        response.setData(comments.stream().map(CommentResponse::from).collect(Collectors.toList()));
        return response;
    }

    // ── 댓글 작성 — postId Path Variable + 게시글 존재 검증 ──
    @Transactional
    public CommentResponse create(String authHeader, Long postId, CommentRequest req) {
        AuthClient.ValidateResponse user = authClient.validate(authHeader);

        if (!postClient.exists(postId)) {
            throw new ApiException(HttpStatus.NOT_FOUND, "POST_NOT_FOUND", "요청한 게시글을 찾을 수 없습니다.");
        }

        Comment comment = new Comment();
        comment.setPostId(postId);
        comment.setUserId(user.getUserId());
        comment.setUsername(user.getUsername());
        comment.setContent(req.getContent());
        return CommentResponse.from(commentRepo.save(comment));
    }

    // ── 댓글 수정 (본인만) ────────────────────────────────────
    @Transactional
    public CommentResponse update(String authHeader, Long id, CommentRequest req) {
        AuthClient.ValidateResponse user = authClient.validate(authHeader);
        Comment comment = findOrThrow(id);
        checkOwner(comment, user.getUserId());
        comment.setContent(req.getContent());
        return CommentResponse.from(commentRepo.save(comment));
    }

    // ── 댓글 삭제 — 200 + message + commentId ────────────────
    @Transactional
    public CommentDeleteResponse delete(String authHeader, Long id) {
        AuthClient.ValidateResponse user = authClient.validate(authHeader);
        Comment comment = findOrThrow(id);
        checkOwner(comment, user.getUserId());
        commentRepo.delete(comment);
        return new CommentDeleteResponse("댓글이 삭제되었습니다.", id);
    }

    // ── internal: 게시글 삭제 시 연쇄 삭제 ────────────────────
    @Transactional
    public void deleteByPostId(Long postId) {
        commentRepo.deleteByPostId(postId);
    }

    // ── 내부 유틸 ─────────────────────────────────────────────
    private Comment findOrThrow(Long id) {
        return commentRepo.findById(id)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "COMMENT_NOT_FOUND", "요청한 댓글을 찾을 수 없습니다."));
    }

    private void checkOwner(Comment comment, Long userId) {
        if (!comment.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "COMMENT_FORBIDDEN", "본인이 작성한 댓글이 아닙니다.");
        }
    }
}
