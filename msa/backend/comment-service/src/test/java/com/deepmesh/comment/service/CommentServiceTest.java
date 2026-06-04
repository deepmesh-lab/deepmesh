package com.deepmesh.comment.service;

import com.deepmesh.comment.config.AuthClient;
import com.deepmesh.comment.config.PostClient;
import com.deepmesh.comment.dto.*;
import com.deepmesh.comment.entity.Comment;
import com.deepmesh.comment.repository.CommentRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Pageable;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * CommentService 단위 테스트.
 * AuthClient, PostClient(east-west), DB를 Mock으로 대체.
 */
@ExtendWith(MockitoExtension.class)
class CommentServiceTest {

    @Mock CommentRepository commentRepo;
    @Mock AuthClient authClient;
    @Mock PostClient postClient;

    @InjectMocks CommentService commentService;

    private AuthClient.ValidateResponse user(Long id, String name) {
        AuthClient.ValidateResponse v = new AuthClient.ValidateResponse();
        v.setUserId(id);
        v.setUsername(name);
        return v;
    }

    private Comment comment(Long id, Long userId) {
        Comment c = new Comment();
        c.setId(id);
        c.setPostId(1L);
        c.setUserId(userId);
        c.setUsername("alice");
        c.setContent("댓글");
        return c;
    }

    // ── 목록 조회 (Cursor) ───────────────────────────────────

    @Test
    @DisplayName("목록 조회 - cursor=0이면 처음부터, hasNext 판단")
    void getByPostId_fromStart() {
        // size=2 요청 → size+1=3개 조회되면 hasNext=true
        List<Comment> result = new ArrayList<>(List.of(
            comment(1L, 1L), comment(2L, 1L), comment(3L, 1L)
        ));
        when(commentRepo.findByPostIdOrderByIdAsc(eq(1L), any(Pageable.class)))
            .thenReturn(result);

        CommentListResponse res = commentService.getByPostId(1L, null, 2);

        assertThat(res.getData()).hasSize(2);
        assertThat(res.getHasNext()).isTrue();
        assertThat(res.getNextCursor()).isEqualTo(2L);   // 마지막 항목 id
    }

    @Test
    @DisplayName("목록 조회 - 마지막 페이지면 hasNext=false, nextCursor=null")
    void getByPostId_lastPage() {
        List<Comment> result = new ArrayList<>(List.of(comment(1L, 1L)));
        when(commentRepo.findByPostIdOrderByIdAsc(eq(1L), any(Pageable.class)))
            .thenReturn(result);

        CommentListResponse res = commentService.getByPostId(1L, null, 20);

        assertThat(res.getHasNext()).isFalse();
        assertThat(res.getNextCursor()).isNull();
    }

    @Test
    @DisplayName("목록 조회 - cursor 지정 시 해당 id 이후 조회")
    void getByPostId_withCursor() {
        List<Comment> result = new ArrayList<>(List.of(comment(5L, 1L)));
        when(commentRepo.findByPostIdAndIdGreaterThanOrderByIdAsc(eq(1L), eq(4L), any(Pageable.class)))
            .thenReturn(result);

        CommentListResponse res = commentService.getByPostId(1L, 4L, 20);

        assertThat(res.getData()).hasSize(1);
        verify(commentRepo).findByPostIdAndIdGreaterThanOrderByIdAsc(eq(1L), eq(4L), any(Pageable.class));
    }

    // ── 작성 (게시글 존재 검증) ───────────────────────────────

    @Test
    @DisplayName("작성 성공 - 게시글 존재 검증 통과")
    void create_success() {
        CommentRequest req = new CommentRequest();
        req.setContent("댓글 내용");

        when(authClient.validate("Bearer t")).thenReturn(user(1L, "alice"));
        when(postClient.exists(1L)).thenReturn(true);
        when(commentRepo.save(any(Comment.class))).thenAnswer(inv -> {
            Comment c = inv.getArgument(0);
            c.setId(100L);
            return c;
        });

        CommentResponse res = commentService.create("Bearer t", 1L, req);

        assertThat(res.getCommentId()).isEqualTo(100L);
        assertThat(res.getPostId()).isEqualTo(1L);
        verify(postClient).exists(1L);   // 존재 검증 호출 확인
    }

    @Test
    @DisplayName("작성 실패 - 존재하지 않는 게시글이면 404, 저장 안 됨")
    void create_postNotExists() {
        CommentRequest req = new CommentRequest();
        req.setContent("댓글");

        when(authClient.validate("Bearer t")).thenReturn(user(1L, "alice"));
        when(postClient.exists(999L))
            .thenThrow(new ResponseStatusException(org.springframework.http.HttpStatus.NOT_FOUND, "게시글 없음"));

        assertThatThrownBy(() -> commentService.create("Bearer t", 999L, req))
            .isInstanceOf(ResponseStatusException.class);
        verify(commentRepo, never()).save(any());
    }

    // ── 수정/삭제 (소유권) ────────────────────────────────────

    @Test
    @DisplayName("수정 실패 - 본인 댓글이 아니면 403")
    void update_notOwner() {
        CommentRequest req = new CommentRequest();
        req.setContent("수정");

        when(authClient.validate("Bearer t")).thenReturn(user(2L, "bob"));   // bob
        when(commentRepo.findById(1L)).thenReturn(Optional.of(comment(1L, 1L)));  // alice 댓글

        assertThatThrownBy(() -> commentService.update("Bearer t", 1L, req))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("본인 댓글 아님");
    }

    @Test
    @DisplayName("삭제 성공 - message + commentId 반환")
    void delete_success() {
        when(authClient.validate("Bearer t")).thenReturn(user(1L, "alice"));
        when(commentRepo.findById(1L)).thenReturn(Optional.of(comment(1L, 1L)));

        CommentDeleteResponse res = commentService.delete("Bearer t", 1L);

        assertThat(res.getMessage()).contains("삭제");
        assertThat(res.getCommentId()).isEqualTo(1L);
        verify(commentRepo).delete(any(Comment.class));
    }

    // ── internal 연쇄 삭제 ───────────────────────────────────

    @Test
    @DisplayName("게시글 삭제 시 댓글 일괄 삭제 호출")
    void deleteByPostId() {
        commentService.deleteByPostId(1L);
        verify(commentRepo).deleteByPostId(1L);
    }
}
