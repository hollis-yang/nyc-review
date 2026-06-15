package com.hmdp.controller;


import com.hmdp.dto.Result;
import com.hmdp.service.IBlogCommentsService;
import org.springframework.web.bind.annotation.*;

import javax.annotation.Resource;

/**
 * <p>
 *  前端控制器
 * </p>
 *
 * @author 虎哥
 * @since 2021-12-22
 */
@RestController
@RequestMapping("/blog-comments")
public class BlogCommentsController {

    @Resource
    private IBlogCommentsService blogCommentsService;

    @GetMapping
    public Result queryComments(@RequestParam("blogId") Long blogId) {
        return blogCommentsService.queryCommentsByBlogId(blogId);
    }
}
