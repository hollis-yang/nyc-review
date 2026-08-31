package com.nycreview.service.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.nycreview.dto.Result;
import com.nycreview.dto.ScrollResult;
import com.nycreview.dto.UserDTO;
import com.nycreview.entity.Blog;
import com.nycreview.entity.BlogComments;
import com.nycreview.entity.Follow;
import com.nycreview.entity.User;
import com.nycreview.mapper.BlogMapper;
import com.nycreview.mapper.BlogCommentsMapper;
import com.nycreview.service.ImageStorageService;
import com.nycreview.service.IBlogService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.service.IFollowService;
import com.nycreview.service.IUserService;
import com.nycreview.utils.RedisConstants;
import com.nycreview.utils.RedisPatternCleaner;
import com.nycreview.utils.ContentSourceTypes;
import com.nycreview.utils.SystemConstants;
import com.nycreview.utils.TransactionHooks;
import com.nycreview.utils.UserHolder;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import jakarta.annotation.Resource;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@Service
public class BlogServiceImpl extends ServiceImpl<BlogMapper, Blog> implements IBlogService {

    @Resource
    private IUserService userService;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private IFollowService followService;

    @Resource
    private BlogCommentsMapper blogCommentsMapper;

    @Resource
    private ImageStorageService imageStorageService;

    @Resource
    private RedisPatternCleaner redisPatternCleaner;

    @Resource
    private RedissonClient redissonClient;

    private static final String BLOG_LIKED_KEY = RedisConstants.BLOG_LIKED_KEY;
    private static final String FEED_KEY = RedisConstants.FEED_KEY;

    private static final DefaultRedisScript<Long> BLOG_LIKE_SCRIPT;

    static {
        BLOG_LIKE_SCRIPT = new DefaultRedisScript<>();
        BLOG_LIKE_SCRIPT.setLocation(new ClassPathResource("blog_like.lua"));
        BLOG_LIKE_SCRIPT.setResultType(Long.class);
    }

    @Override
    @Transactional
    public Result likeBlog(Long id) {
        // 1.获取登录用户
        Long userId = UserHolder.getUser().getId();
        if (getById(id) == null) {
            return Result.fail("Note not found");
        }
        String key = BLOG_LIKED_KEY + id;
        RLock lock = redissonClient.getLock("lock:blog-like:" + id + ":" + userId);
        boolean locked = false;
        boolean releaseAfterCompletion = false;
        try {
            locked = lock.tryLock(1, 10, TimeUnit.SECONDS);
            if (!locked) {
                return Result.fail("Too many requests. Please try again later");
            }
            Long delta = stringRedisTemplate.execute(
                    BLOG_LIKE_SCRIPT,
                    Collections.singletonList(key),
                    userId.toString(),
                    Long.toString(System.currentTimeMillis()));
            if (delta == null || (delta != 1L && delta != -1L)) {
                throw new IllegalStateException("Failed to update like status");
            }
            registerLikeRollbackCompensation(key, userId);
            releaseAfterCompletion = registerLikeLockRelease(lock);
            boolean updated = delta > 0
                    ? update().setSql("liked = liked + 1").eq("id", id).update()
                    : update().setSql("liked = GREATEST(liked - 1, 0)").eq("id", id).gt("liked", 0).update();
            if (!updated) {
                // 当前线程持有用户-博客粒度的分布式锁，再执行一次切换可安全补偿 Redis。
                stringRedisTemplate.execute(
                        BLOG_LIKE_SCRIPT,
                        Collections.singletonList(key),
                        userId.toString(),
                        Long.toString(System.currentTimeMillis()));
                return Result.fail("Failed to update like status");
            }
            return Result.ok();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return Result.fail("The operation was interrupted. Please try again");
        } finally {
            if (locked && !releaseAfterCompletion && lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }

    @Override
    public Result queryHotBlog(Integer current) {
        // 根据用户查询
        Page<Blog> page = query()
                .orderByDesc("liked")
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));
        // 获取当前页数据
        List<Blog> records = page.getRecords();
        // 查询用户
        records.forEach(blog -> {
            this.queryBlogUser(blog);
            this.isBlogLiked(blog);
        });
        return Result.ok(records);
    }

    @Override
    public Result queryBlogById(Long id) {
        // 1. 查询Blog
        Blog blog = getById(id);
        if (blog == null) {
            return Result.fail("Note not found");
        }
        // 2. 查询Blog有关的用户
        queryBlogUser(blog);
        // 3. 查询当前Blog是否被点赞
        isBlogLiked(blog);
        return Result.ok(blog);
    }

    @Override
    @Transactional
    public Result saveBlog(Blog blog) {
        // 1.获取登录用户
        UserDTO user = UserHolder.getUser();
        blog.setUserId(user.getId());
        // Provenance is server-owned. In particular, a client cannot make a
        // user post look like generated evidence by sending SYNTHETIC.
        markUserSubmitted(blog);
        // 2.保存探店博文
        boolean isSuccess = save(blog);
        if (!isSuccess) {
            return Result.fail("Failed to create the note");
        }
        // 3.查询笔记作者的所有粉丝
        List<Follow> follows = followService.query().eq("follow_user_id", user.getId()).list();
        // 4.仅在数据库事务提交后推送，避免数据库回滚但 Feed 已写入
        TransactionHooks.afterCommit(() -> {
            long publishedAt = blog.getCreateTime() == null
                    ? System.currentTimeMillis()
                    : blog.getCreateTime().atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
            for (Follow follow : follows) {
                try {
                    stringRedisTemplate.opsForZSet().add(
                            FEED_KEY + follow.getUserId(),
                            blog.getId().toString(),
                            publishedAt);
                } catch (RuntimeException e) {
                    // 查询关注 Feed 时会从数据库回补，单个推送失败不影响博客发布结果。
                }
            }
        });
        // 5.返回id
        return Result.ok(blog.getId());
    }

    static void markUserSubmitted(Blog blog) {
        blog.setSourceType(ContentSourceTypes.USER_SUBMITTED);
        blog.setDataVersion(null);
    }

    @Override
    public Result queryBlogLikes(Long id) {
        String key = BLOG_LIKED_KEY + id;
        // 1. Query the five most recent likes. Generated/demo relationships
        // are appended with current scores, so reverse order also keeps the
        // visible avatar row consistent with the latest real interactions.
        Set<String> top5 = stringRedisTemplate.opsForZSet().reverseRange(key, 0, 4);
        if (top5 == null || top5.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }
        // 2.解析出用户id（保持ZSet返回的顺序）
        List<Long> ids = top5.stream().map(Long::valueOf).collect(Collectors.toList());
        // 3.根据用户id查询出用户，MySQL ORDER BY FIELD 保持原顺序
        String idsStr = ids.stream().map(String::valueOf).collect(Collectors.joining(","));
        List<UserDTO> userDTOS = userService.query()
                .in("id", ids)
                .last("ORDER BY FIELD(id, " + idsStr + ")")
                .list()
                .stream()
                .map(u -> BeanUtil.copyProperties(u, UserDTO.class))
                .collect(Collectors.toList());
        return Result.ok(userDTOS);
    }

    @Override
    public Result queryBlogLikesByFollowees(Long id) {
        UserDTO currentUser = UserHolder.getUser();
        if (currentUser == null || currentUser.getId() == null) {
            return Result.fail("Please sign in first");
        }
        Set<Long> followeeIds = followService.query()
                .eq("user_id", currentUser.getId())
                .list()
                .stream()
                .map(Follow::getFollowUserId)
                .collect(Collectors.toSet());
        if (followeeIds.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }

        Set<String> likerIds = stringRedisTemplate.opsForZSet()
                .reverseRange(BLOG_LIKED_KEY + id, 0, -1);
        if (likerIds == null || likerIds.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }
        List<Long> matched = likerIds.stream()
                .map(Long::valueOf)
                .filter(followeeIds::contains)
                .limit(3)
                .toList();
        if (matched.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }
        String idsStr = matched.stream().map(String::valueOf).collect(Collectors.joining(","));
        List<UserDTO> users = userService.query()
                .in("id", matched)
                .last("ORDER BY FIELD(id, " + idsStr + ")")
                .list()
                .stream()
                .map(user -> BeanUtil.copyProperties(user, UserDTO.class))
                .toList();
        return Result.ok(users);
    }

    @Override
    @Transactional
    public Result deleteBlog(Long id) {
        Blog blog = getById(id);
        if (blog == null) {
            return Result.fail("Note not found");
        }
        Long userId = UserHolder.getUser().getId();
        if (!userId.equals(blog.getUserId())) {
            return Result.fail("You can only delete your own notes");
        }
        List<BlogComments> comments = blogCommentsMapper.selectList(
                new QueryWrapper<BlogComments>().eq("blog_id", id));
        blogCommentsMapper.delete(new QueryWrapper<BlogComments>().eq("blog_id", id));
        if (!removeById(id)) {
            throw new IllegalStateException("Failed to delete the note");
        }
        List<Long> commentIds = comments.stream().map(BlogComments::getId).collect(Collectors.toList());
        List<String> images = blog.getImages() == null
                ? Collections.emptyList()
                : List.of(blog.getImages().split(","));
        TransactionHooks.afterCommit(() -> cleanupDeletedBlog(blog, commentIds, images));
        return Result.ok();
    }

    private void isBlogLiked(Blog blog) {
        // 1.获取登录用户
        UserDTO user = UserHolder.getUser();
        if (user == null) {
            // 用户未登录，无需查询是否点赞
            return;
        }
        Long userId = user.getId();
        // 2.判断当前用户是否点赞
        String key = BLOG_LIKED_KEY + blog.getId();
        Double score = stringRedisTemplate.opsForZSet().score(key, userId.toString());
        blog.setIsLike(score != null);
    }

    private void queryBlogUser(Blog blog) {
        Long userId = blog.getUserId();
        User user = userService.getById(userId);
        blog.setName(user.getNickName());
        blog.setIcon(user.getIcon());
    }

    @Override
    public Result queryBlogOfFollow(Long max, Integer offset) {
        // 1.获取当前用户
        Long userId = UserHolder.getUser().getId();
        backfillFeed(userId);
        // 2.查询收件箱 ZREVRANGEBYSCORE key Max Min LIMIT offset count
        String key = FEED_KEY + userId;
        Set<ZSetOperations.TypedTuple<String>> typedTuples = stringRedisTemplate.opsForZSet()
                .reverseRangeByScoreWithScores(key, 0, max, offset, 2);
        // 3.判断非空
        if (typedTuples == null || typedTuples.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }
        // 4.解析数据：blogId、minTime（时间戳）、offset
        List<Long> ids = new ArrayList<>(typedTuples.size());
        long minTime = 0;
        int os = 1;
        for (ZSetOperations.TypedTuple<String> tuple : typedTuples) {
            // 4.1.获取id
            ids.add(Long.valueOf(tuple.getValue()));
            // 4.2.获取分数（时间戳）
            long time = tuple.getScore().longValue();
            if (time == minTime) {
                os++;
            } else {
                minTime = time;
                os = 1;
            }
        }
        // 5.根据blogId查询blog
        String idStr = StrUtil.join(",", ids);
        List<Blog> blogs = query().in("id", ids)
                .last("ORDER BY FIELD(id, " + idStr + ")")
                .list();
        for (Blog blog : blogs) {
            // 5.1. 查询Blog有关的用户
            queryBlogUser(blog);
            // 5.2. 查询当前Blog是否被点赞
            isBlogLiked(blog);
        }
        // 6.封装并返回
        ScrollResult scrollResult = new ScrollResult();
        scrollResult.setList(blogs);
        scrollResult.setOffset(os);
        scrollResult.setMinTime(minTime);
        return Result.ok(scrollResult);
    }

    private void backfillFeed(Long userId) {
        List<Long> followedUserIds = followService.query()
                .eq("user_id", userId)
                .list()
                .stream()
                .map(Follow::getFollowUserId)
                .collect(Collectors.toList());
        if (followedUserIds.isEmpty()) {
            return;
        }
        List<Blog> recentBlogs = query()
                .in("user_id", followedUserIds)
                .orderByDesc("create_time")
                .last("LIMIT 100")
                .list();
        String feedKey = FEED_KEY + userId;
        for (Blog recentBlog : recentBlogs) {
            long score = recentBlog.getCreateTime() == null
                    ? 0L
                    : recentBlog.getCreateTime().atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
            stringRedisTemplate.opsForZSet().add(feedKey, recentBlog.getId().toString(), score);
        }
    }

    private void cleanupDeletedBlog(Blog blog, List<Long> commentIds, List<String> images) {
        try {
            stringRedisTemplate.delete(BLOG_LIKED_KEY + blog.getId());
            redisPatternCleaner.deleteByPattern(
                    RedisConstants.TRANSLATE_CACHE_KEY + "blog:" + blog.getId() + ":*");
            if (!commentIds.isEmpty()) {
                for (Long commentId : commentIds) {
                    redisPatternCleaner.deleteByPattern(
                            RedisConstants.TRANSLATE_CACHE_KEY + "comment:" + commentId + ":*");
                }
            }
            redisPatternCleaner.removeZSetMemberByPattern(FEED_KEY + "*", blog.getId().toString());
        } catch (RuntimeException ignored) {
            // Redis 清理失败不会回滚已经提交的数据库删除；重复清理是幂等的。
        }
        for (String image : images) {
            String path = image.trim();
            if (!path.startsWith("/imgs/blogs/" + blog.getUserId() + "/")) {
                continue;
            }
            try {
                boolean usedAsAvatar = userService.query().eq("icon", path).count() > 0;
                boolean usedByAnotherBlog = query().like("images", path).count() > 0;
                if (!usedAsAvatar && !usedByAnotherBlog) {
                    imageStorageService.delete(path, blog.getUserId());
                }
            } catch (RuntimeException ignored) {
                // 文件可能已经删除，保留数据库删除结果。
            }
        }
    }

    private void registerLikeRollbackCompensation(String key, Long userId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCompletion(int status) {
                if (status == TransactionSynchronization.STATUS_COMMITTED) {
                    return;
                }
                try {
                    stringRedisTemplate.execute(
                            BLOG_LIKE_SCRIPT,
                            Collections.singletonList(key),
                            userId.toString(),
                            Long.toString(System.currentTimeMillis()));
                } catch (RuntimeException ignored) {
                    // Redis 暂不可用时保留日志侧告警，后续一致性任务可再次修复。
                }
            }
        });
    }

    private boolean registerLikeLockRelease(RLock lock) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            return false;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCompletion(int status) {
                if (lock.isHeldByCurrentThread()) {
                    lock.unlock();
                }
            }
        });
        return true;
    }
}
