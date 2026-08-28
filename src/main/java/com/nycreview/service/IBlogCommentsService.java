package com.nycreview.service;

import com.nycreview.entity.BlogComments;
import com.baomidou.mybatisplus.extension.service.IService;

import com.nycreview.dto.Result;

public interface IBlogCommentsService extends IService<BlogComments> {

    Result queryCommentsByBlogId(Long blogId);

    Result addComment(BlogComments comment);

    Result deleteComment(Long id);
}
