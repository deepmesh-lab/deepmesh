package com.deepmesh.post.service;

import com.deepmesh.post.config.AuthClient;
import com.deepmesh.post.config.CommentClient;
import com.deepmesh.post.dto.*;
import com.deepmesh.post.entity.Post;
import com.deepmesh.post.exception.ApiException;
import com.deepmesh.post.repository.PostRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class PostService {

    private final PostRepository postRepo;
    private final AuthClient authClient;
    private final CommentClient commentClient;

    private static final int MAX_SIZE = 50;

    // ── 목록 조회 — Offset 페이지네이션 (기본값 page=1, size=20) ─
    public PostListResponse getAll(Integer page, Integer size) {
        int p = (page == null) ? 1 : page;
        int s = (size == null) ? 20 : size;
        // MODIFY : BAD_REQUEST
        if (p < 1) throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_PARAM", "page는 1 이상이어야 합니다.");
        if (s < 1) throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_PARAM", "size는 1 이상이어야 합니다.");

        s = Math.min(s, MAX_SIZE);   // size 상한 50

        Pageable pageable = PageRequest.of(p - 1, s);   // 1-base → 0-base
        Page<Post> postPage = postRepo.findAllByOrderByIdDesc(pageable);

        PostListResponse response = new PostListResponse();
        response.setPage(p);
        response.setSize(s);
        response.setTotalPage(postPage.getTotalPages());
        response.setTotalCount(postPage.getTotalElements());
        response.setData(postPage.getContent().stream()
            .map(PostResponse::fromSummary).collect(Collectors.toList()));
        return response;
    }

    // ── 단건 조회 ────────────────────────────────────────────
    public PostResponse getOne(Long id) {
        return PostResponse.from(findOrThrow(id));
    }

    // ── 게시글 작성 ─────────────────────────────────────────
    @Transactional
    public PostResponse create(String authHeader, PostRequest req) {
        AuthClient.ValidateResponse user = authClient.validate(authHeader);
        Post post = new Post();
        post.setUserId(user.getUserId());
        post.setUsername(user.getUsername());
        post.setTitle(req.getTitle());
        post.setContent(req.getContent());
        return PostResponse.from(postRepo.save(post));
    }

    // ── 게시글 수정 (본인만) ─────────────────────────────────
    @Transactional
    public PostResponse update(String authHeader, Long id, PostRequest req) {
        AuthClient.ValidateResponse user = authClient.validate(authHeader);
        Post post = findOrThrow(id);
        checkOwner(post, user.getUserId());
        post.setTitle(req.getTitle());
        post.setContent(req.getContent());
        return PostResponse.from(postRepo.save(post));
    }

    // ── 게시글 삭제 — 200 + message + postId, 댓글 연쇄 삭제 ──
    @Transactional
    public PostDeleteResponse delete(String authHeader, Long id) {
        AuthClient.ValidateResponse user = authClient.validate(authHeader);
        Post post = findOrThrow(id);
        checkOwner(post, user.getUserId());

        commentClient.deleteByPostId(id);   //MODIFY : comment 삭제 후
        postRepo.delete(post);              //post 지우기로 순서변경
        return new PostDeleteResponse("게시글이 삭제되었습니다.", id);
    }

    // ── internal: 게시글 존재 여부 확인 ──────────────────────
    public PostExistsResponse exists(Long id) {
        return new PostExistsResponse(id, postRepo.existsById(id));
    }

    // ── 내부 유틸 ─────────────────────────────────────────
    private Post findOrThrow(Long id) {
        return postRepo.findById(id)
            .orElseThrow(() ->  new ApiException(HttpStatus.NOT_FOUND, "POST_NOT_FOUND", "요청한 게시글을 찾을 수 없습니다."));
    }

    private void checkOwner(Post post, Long userId) {
        if (!post.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "POST_FORBIDDEN", "본인이 작성한 게시글이 아닙니다.");
        }
    }
}
