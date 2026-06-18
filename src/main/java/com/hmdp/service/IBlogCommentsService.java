package com.hmdp.service;

import com.hmdp.entity.BlogComments;
import com.baomidou.mybatisplus.extension.service.IService;

import com.hmdp.dto.Result;

public interface IBlogCommentsService extends IService<BlogComments> {

    Result queryCommentsByBlogId(Long blogId);

    Result addComment(BlogComments comment);

    Result deleteComment(Long id);
}
