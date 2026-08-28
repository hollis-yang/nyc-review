package com.nycreview.controller;


import com.nycreview.dto.Result;
import com.nycreview.entity.BlogComments;
import com.nycreview.service.IBlogCommentsService;
import org.springframework.web.bind.annotation.*;

import jakarta.annotation.Resource;

@RestController
@RequestMapping("/blog-comments")
public class BlogCommentsController {

    @Resource
    private IBlogCommentsService blogCommentsService;

    @GetMapping
    public Result queryComments(@RequestParam("blogId") Long blogId) {
        return blogCommentsService.queryCommentsByBlogId(blogId);
    }

    @PostMapping
    public Result addComment(@RequestBody BlogComments comment) {
        return blogCommentsService.addComment(comment);
    }

    @DeleteMapping("/{id}")
    public Result deleteComment(@PathVariable("id") Long id) {
        return blogCommentsService.deleteComment(id);
    }
}
