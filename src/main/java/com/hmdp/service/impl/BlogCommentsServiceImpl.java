package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.User;
import com.hmdp.mapper.BlogCommentsMapper;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IUserService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.UserHolder;
import org.springframework.stereotype.Service;

import jakarta.annotation.Resource;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class BlogCommentsServiceImpl extends ServiceImpl<BlogCommentsMapper, BlogComments> implements IBlogCommentsService {

    @Resource
    private IUserService userService;

    @Override
    public Result queryCommentsByBlogId(Long blogId) {
        // 查询一级评论（parent_id = 0），按时间倒序
        List<BlogComments> commentList = query()
                .eq("blog_id", blogId)
                .eq("parent_id", 0)
                .eq("status", 0)
                .orderByAsc("create_time")
                .list();

        // 组装带用户信息的返回数据
        List<Map<String, Object>> result = new ArrayList<>();
        for (BlogComments comment : commentList) {
            User user = userService.getById(comment.getUserId());
            Map<String, Object> item = new HashMap<>();
            item.put("id", comment.getId());
            item.put("userId", comment.getUserId());
            item.put("content", comment.getContent());
            item.put("liked", comment.getLiked());
            item.put("createTime", comment.getCreateTime().toString());
            item.put("icon", user != null ? user.getIcon() : "");
            item.put("name", user != null ? user.getNickName() : "匿名用户");
            result.add(item);
        }

        return Result.ok(result);
    }

    @Override
    public Result addComment(BlogComments comment) {
        if (comment.getBlogId() == null) {
            return Result.fail("博客ID不能为空");
        }
        if (comment.getContent() == null || comment.getContent().trim().isEmpty()) {
            return Result.fail("评论内容不能为空");
        }
        Long userId = UserHolder.getUser().getId();
        comment.setUserId(userId);
        comment.setLiked(0);
        comment.setStatus(false);
        if (comment.getParentId() == null) comment.setParentId(0L);
        if (comment.getAnswerId() == null) comment.setAnswerId(0L);
        save(comment);
        return Result.ok(comment.getId());
    }
}
