package com.deepmesh.post.repository;

import com.deepmesh.post.entity.Post;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface PostRepository extends JpaRepository<Post, Long> {
    // id 기준 내림차순 (부하테스트 시 created_at 중복 방지)
    Page<Post> findAllByOrderByIdDesc(Pageable pageable);
}