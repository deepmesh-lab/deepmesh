package com.deepmesh.comment;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
public class CommentApplication {
    public static void main(String[] args) { SpringApplication.run(CommentApplication.class, args); }
}