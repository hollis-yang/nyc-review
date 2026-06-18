package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.dto.Result;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.User;
import com.hmdp.mapper.BlogCommentsMapper;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IUserService;
import com.hmdp.utils.UserHolder;
import org.springframework.stereotype.Service;

import jakarta.annotation.Resource;
import java.util.*;
import java.util.stream.Collectors;

@Service
public class BlogCommentsServiceImpl extends ServiceImpl<BlogCommentsMapper, BlogComments> implements IBlogCommentsService {

    @Resource
    private IUserService userService;

    @Resource
    private IBlogService blogService;

    @Override
    public Result queryCommentsByBlogId(Long blogId) {
        // 查询该博客所有评论，按时间正序
        List<BlogComments> all = query()
                .eq("blog_id", blogId)
                .eq("status", 0)
                .orderByAsc("create_time")
                .list();

        if (all.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }

        // 批量查用户
        Set<Long> userIds = all.stream()
                .map(BlogComments::getUserId)
                .collect(Collectors.toSet());
        Map<Long, User> userMap = userService.listByIds(userIds).stream()
                .collect(Collectors.toMap(User::getId, u -> u));

        // 构建 id -> comment 的 Map
        Map<Long, BlogComments> commentMap = all.stream()
                .collect(Collectors.toMap(BlogComments::getId, c -> c, (a, b) -> a));

        // 按 parentId 分组
        Map<Long, List<BlogComments>> childrenMap = new HashMap<>();
        List<BlogComments> roots = new ArrayList<>();
        for (BlogComments c : all) {
            if (c.getParentId() == null || c.getParentId() == 0L) {
                roots.add(c);
            } else {
                childrenMap.computeIfAbsent(c.getParentId(), k -> new ArrayList<>()).add(c);
            }
        }

        // 构建返回数据
        List<Map<String, Object>> result = new ArrayList<>();
        for (BlogComments root : roots) {
            result.add(buildCommentItem(root, childrenMap, commentMap, userMap));
        }
        return Result.ok(result);
    }

    private Map<String, Object> buildCommentItem(
            BlogComments comment,
            Map<Long, List<BlogComments>> childrenMap,
            Map<Long, BlogComments> commentMap,
            Map<Long, User> userMap) {

        User user = userMap.get(comment.getUserId());
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", comment.getId());
        item.put("userId", comment.getUserId());
        item.put("parentId", comment.getParentId());
        item.put("answerId", comment.getAnswerId());
        item.put("content", comment.getContent());
        item.put("liked", comment.getLiked());
        item.put("createTime", comment.getCreateTime().toString());
        item.put("icon", user != null ? user.getIcon() : "");
        item.put("name", user != null ? user.getNickName() : "匿名用户");

        // 被回复者名称
        String replyToName = "";
        if (comment.getAnswerId() != null && comment.getAnswerId() > 0) {
            BlogComments answered = commentMap.get(comment.getAnswerId());
            if (answered != null) {
                User answeredUser = userMap.get(answered.getUserId());
                replyToName = answeredUser != null ? answeredUser.getNickName() : "匿名用户";
            }
        }
        item.put("replyToName", replyToName);

        // 子评论
        List<BlogComments> children = childrenMap.getOrDefault(comment.getId(), Collections.emptyList());
        List<Map<String, Object>> childList = new ArrayList<>();
        for (BlogComments child : children) {
            childList.add(buildCommentItem(child, childrenMap, commentMap, userMap));
        }
        item.put("children", childList);

        return item;
    }

    @Override
    public Result addComment(BlogComments comment) {
        if (comment.getBlogId() == null) {
            return Result.fail("博客ID不能为空");
        }
        if (comment.getContent() == null || comment.getContent().trim().isEmpty()) {
            return Result.fail("评论内容不能为空");
        }
        // 校验父评论
        if (comment.getParentId() != null && comment.getParentId() > 0) {
            BlogComments parent = getById(comment.getParentId());
            if (parent == null || !parent.getBlogId().equals(comment.getBlogId())) {
                return Result.fail("父评论不存在");
            }
            // 确保 parentId 指向顶层评论
            if (parent.getParentId() != null && parent.getParentId() > 0) {
                comment.setParentId(parent.getParentId());
            }
        } else {
            comment.setParentId(0L);
        }
        if (comment.getAnswerId() == null) {
            comment.setAnswerId(0L);
        }
        Long userId = UserHolder.getUser().getId();
        comment.setUserId(userId);
        comment.setLiked(0);
        comment.setStatus(false);
        save(comment);
        blogService.update().setSql("comments = comments + 1").eq("id", comment.getBlogId()).update();
        return Result.ok(comment.getId());
    }

    @Override
    public Result deleteComment(Long id) {
        BlogComments comment = getById(id);
        if (comment == null) {
            return Result.fail("评论不存在");
        }
        Long userId = UserHolder.getUser().getId();
        if (!userId.equals(comment.getUserId())) {
            return Result.fail("只能删除自己的评论");
        }
        int deletedCount = 1;
        // 顶层评论：级联删除所有子评论
        if (comment.getParentId() == null || comment.getParentId() == 0L) {
            List<BlogComments> children = lambdaQuery().eq(BlogComments::getParentId, id).list();
            if (!children.isEmpty()) {
                List<Long> childIds = children.stream().map(BlogComments::getId).collect(Collectors.toList());
                removeByIds(childIds);
                deletedCount += children.size();
            }
        }
        removeById(id);
        blogService.update()
                .setSql("comments = comments - " + deletedCount)
                .eq("id", comment.getBlogId()).update();
        return Result.ok();
    }
}
