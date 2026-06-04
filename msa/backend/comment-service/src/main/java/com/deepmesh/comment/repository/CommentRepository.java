package com.deepmesh.comment.repository;

import com.deepmesh.comment.entity.Comment;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface CommentRepository extends JpaRepository<Comment, Long> {
    // Cursor 없이 첫 N개 (id 오름차순)
    List<Comment> findByPostIdOrderByIdAsc(Long postId, Pageable pageable);
    // Cursor 기반: cursor(commentId) 이후 N개
    List<Comment> findByPostIdAndIdGreaterThanOrderByIdAsc(Long postId, Long cursor, Pageable pageable);
    // 게시글 삭제 시 연쇄 삭제 (internal)
    void deleteByPostId(Long postId);
}