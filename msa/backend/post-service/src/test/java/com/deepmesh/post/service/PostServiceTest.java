package com.deepmesh.post.service;

import com.deepmesh.post.config.AuthClient;
import com.deepmesh.post.config.CommentClient;
import com.deepmesh.post.dto.*;
import com.deepmesh.post.entity.Post;
import com.deepmesh.post.repository.PostRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * PostService 단위 테스트.
 * AuthClient(east-west), CommentClient, DB를 Mock으로 대체.
 */
@ExtendWith(MockitoExtension.class)
class PostServiceTest {

    @Mock PostRepository postRepo;
    @Mock AuthClient authClient;
    @Mock CommentClient commentClient;

    @InjectMocks PostService postService;

    private AuthClient.ValidateResponse user(Long id, String name) {
        AuthClient.ValidateResponse v = new AuthClient.ValidateResponse();
        v.setUserId(id);
        v.setUsername(name);
        return v;
    }

    private Post post(Long id, Long userId) {
        Post p = new Post();
        p.setId(id);
        p.setUserId(userId);
        p.setUsername("alice");
        p.setTitle("title");
        p.setContent("content");
        return p;
    }

    // ── 목록 조회 (페이지네이션) ──────────────────────────────

    @Test
    @DisplayName("목록 조회 - 기본값 page=1, size=20 적용")
    void getAll_default() {
        Page<Post> page = new PageImpl<>(List.of(post(1L, 1L)), PageRequest.of(0, 20), 1);
        when(postRepo.findAllByOrderByIdDesc(any(Pageable.class))).thenReturn(page);

        PostListResponse res = postService.getAll(null, null);

        assertThat(res.getPage()).isEqualTo(1);
        assertThat(res.getSize()).isEqualTo(20);
        assertThat(res.getTotalCount()).isEqualTo(1L);
        assertThat(res.getData()).hasSize(1);
    }

    @Test
    @DisplayName("목록 조회 - size 50 초과 요청 시 50으로 제한")
    void getAll_sizeCapped() {
        Page<Post> page = new PageImpl<>(List.of(), PageRequest.of(0, 50), 0);
        when(postRepo.findAllByOrderByIdDesc(any(Pageable.class))).thenReturn(page);

        PostListResponse res = postService.getAll(1, 100);

        assertThat(res.getSize()).isEqualTo(50);
    }

    // ── 단건 조회 ────────────────────────────────────────────

    @Test
    @DisplayName("단건 조회 성공")
    void getOne_success() {
        when(postRepo.findById(1L)).thenReturn(Optional.of(post(1L, 1L)));

        PostResponse res = postService.getOne(1L);

        assertThat(res.getPostId()).isEqualTo(1L);
    }

    @Test
    @DisplayName("단건 조회 실패 - 없는 게시글이면 404")
    void getOne_notFound() {
        when(postRepo.findById(999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> postService.getOne(999L))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("게시글 없음");
    }

    // ── 작성 ─────────────────────────────────────────────────

    @Test
    @DisplayName("작성 성공 - 토큰에서 userId/username 도출")
    void create_success() {
        PostRequest req = new PostRequest();
        req.setTitle("새 글");
        req.setContent("내용");

        when(authClient.validate("Bearer t")).thenReturn(user(1L, "alice"));
        when(postRepo.save(any(Post.class))).thenAnswer(inv -> {
            Post p = inv.getArgument(0);
            p.setId(1L);
            return p;
        });

        PostResponse res = postService.create("Bearer t", req);

        assertThat(res.getPostId()).isEqualTo(1L);
        assertThat(res.getUserId()).isEqualTo(1L);
        assertThat(res.getUsername()).isEqualTo("alice");
    }

    // ── 수정 ─────────────────────────────────────────────────

    @Test
    @DisplayName("수정 실패 - 본인 글이 아니면 403")
    void update_notOwner() {
        PostRequest req = new PostRequest();
        req.setTitle("수정");
        req.setContent("수정");

        when(authClient.validate("Bearer t")).thenReturn(user(2L, "bob"));  // bob
        when(postRepo.findById(1L)).thenReturn(Optional.of(post(1L, 1L)));  // alice 글

        assertThatThrownBy(() -> postService.update("Bearer t", 1L, req))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("본인 글 아님");
    }

    // ── 삭제 ─────────────────────────────────────────────────

    @Test
    @DisplayName("삭제 성공 - 댓글 연쇄 삭제 호출 및 message 반환")
    void delete_success() {
        when(authClient.validate("Bearer t")).thenReturn(user(1L, "alice"));
        when(postRepo.findById(1L)).thenReturn(Optional.of(post(1L, 1L)));

        PostDeleteResponse res = postService.delete("Bearer t", 1L);

        assertThat(res.getMessage()).contains("삭제");
        assertThat(res.getPostId()).isEqualTo(1L);
        verify(postRepo).delete(any(Post.class));
        verify(commentClient).deleteByPostId(1L);   // 연쇄 삭제 검증
    }

    @Test
    @DisplayName("삭제 실패 - 본인 글이 아니면 403, 댓글 삭제 호출 안 됨")
    void delete_notOwner() {
        when(authClient.validate("Bearer t")).thenReturn(user(2L, "bob"));
        when(postRepo.findById(1L)).thenReturn(Optional.of(post(1L, 1L)));

        assertThatThrownBy(() -> postService.delete("Bearer t", 1L))
            .isInstanceOf(ResponseStatusException.class);
        verify(commentClient, never()).deleteByPostId(anyLong());
    }

    // ── internal exists ──────────────────────────────────────

    @Test
    @DisplayName("게시글 존재 확인 - 존재하면 true")
    void exists_true() {
        when(postRepo.existsById(1L)).thenReturn(true);

        PostExistsResponse res = postService.exists(1L);

        assertThat(res.isExists()).isTrue();
        assertThat(res.getPostId()).isEqualTo(1L);
    }
}
