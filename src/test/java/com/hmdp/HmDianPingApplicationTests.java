package com.hmdp;

import com.hmdp.entity.Blog;
import com.hmdp.entity.Follow;
import com.hmdp.entity.SeckillVoucher;
import com.hmdp.entity.UserInfo;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IFollowService;
import com.hmdp.service.ISeckillVoucherService;
import com.hmdp.service.IUserInfoService;
import com.hmdp.service.impl.ShopServiceImpl;
import com.hmdp.utils.RedisConstants;
import com.hmdp.utils.RedisIdWorker;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;

import javax.annotation.Resource;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;

@SpringBootTest
class HmDianPingApplicationTests {

    @Resource
    private ShopServiceImpl shopService;

    @Resource
    private RedisIdWorker redisIdWorker;

    @Resource
    private ISeckillVoucherService seckillVoucherService;

    @Resource
    private IBlogService blogService;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private IFollowService followService;

    @Resource
    private IUserInfoService userInfoService;

    private ExecutorService executorService = Executors.newFixedThreadPool(500);

    @Test
    void testIdWorker() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(300);

        Runnable task = () -> {
            for (int i = 0; i < 100; i++) {
                long id = redisIdWorker.nextId("order");
                System.out.println("id: " + id);
            }
            latch.countDown();
        };
        long begin = System.currentTimeMillis();
        for (int i = 0; i < 300; i++) {
            executorService.submit(task);
        }

        latch.await();
        long end = System.currentTimeMillis();
        System.out.println("总耗时: " + (end - begin) + "ms");
    }

    @Test
    void testCacheSeckillStock() {
        List<SeckillVoucher> list = seckillVoucherService.list();
        for (SeckillVoucher seckillVoucher : list) {
            stringRedisTemplate.opsForValue().set(
                    RedisConstants.SECKILL_STOCK_KEY + seckillVoucher.getVoucherId(),
                    seckillVoucher.getStock().toString());
        }
        System.out.println("已缓存 " + list.size() + " 个秒杀券的库存到 Redis");
    }

    @Test
    void testMockBlogLikes() {
        List<Blog> blogs = blogService.list();
        // 用户 ID 范围 1-13
        int totalUsers = 13;
        long now = System.currentTimeMillis();
        long thirtyDaysMs = 30L * 24 * 60 * 60 * 1000;

        for (Blog blog : blogs) {
            String key = RedisConstants.BLOG_LIKED_KEY + blog.getId();
            // 先清空旧数据
            stringRedisTemplate.delete(key);
            // 每个 blog 随机 5-15 个赞
            int likeCount = 5 + (int) (Math.random() * 11);
            for (int i = 0; i < likeCount; i++) {
                Long userId = (long) (1 + (int) (Math.random() * totalUsers));
                // 随机时间戳（过去30天内）
                long timestamp = now - (long) (Math.random() * thirtyDaysMs);
                stringRedisTemplate.opsForZSet().add(key, userId.toString(), timestamp);
            }
            // 同步数据库 liked 字段
            Long actualCount = stringRedisTemplate.opsForZSet().zCard(key);
            if (actualCount != null) {
                blogService.update().setSql("liked = " + actualCount).eq("id", blog.getId()).update();
            }
            System.out.println("blog " + blog.getId() + " → " + actualCount + " likes");
        }
        System.out.println("已为 " + blogs.size() + " 条笔记生成模拟点赞数据");
    }

    @Test
    void testMockFollowData() {
        // 1. 清空旧数据 — MySQL
        followService.getBaseMapper().delete(null);
        System.out.println("已清空旧关注数据 (MySQL)");

        // 1b. 清空旧数据 — Redis
        for (long uid = 1; uid <= 13; uid++) {
            stringRedisTemplate.delete(RedisConstants.FOLLOW_KEY + uid);
        }
        System.out.println("已清空旧关注数据 (Redis)");

        // 2. 构建关注网络
        // 格式: {userId, followUserId}
        long[][] data = {
            // ──── 用户 1 (小鱼同学) 关注 ────
            {1, 2}, {1, 4}, {1, 5}, {1, 9}, {1, 11},
            // ──── 用户 2 (可可今天不吃肉) 关注 ────
            {2, 1}, {2, 5}, {2, 7}, {2, 13},
            // ──── 用户 3 (杭城小王子) 关注 ────
            {3, 8}, {3, 11},
            // ──── 用户 4 (西湖边的猫) 关注 ────
            {4, 1}, {4, 5}, {4, 8}, {4, 11}, {4, 13},
            // ──── 用户 5 (可爱多) 关注 ────
            {5, 1}, {5, 2}, {5, 4}, {5, 8}, {5, 11}, {5, 13},
            // ──── 用户 6 (钱塘江边的人) 关注 ────
            {6, 4}, {6, 7}, {6, 13},
            // ──── 用户 7 (杭州小辣椒) 关注 ────
            {7, 2}, {7, 3}, {7, 5}, {7, 9}, {7, 11},
            // ──── 用户 8 (武林广场舞王) 关注 ────
            {8, 1}, {8, 2}, {8, 7}, {8, 11}, {8, 13},
            // ──── 用户 9 (龙井茶不茶) 关注 ────
            {9, 2}, {9, 7}, {9, 8},
            // ──── 用户 10 (滨江小霸王) 关注 ────
            {10, 5}, {10, 8}, {10, 9}, {10, 12}, {10, 13},
            // ──── 用户 11 (城西一枝花) 关注 ────
            {11, 1}, {11, 2}, {11, 4}, {11, 7}, {11, 8}, {11, 10},
            // ──── 用户 12 (萧山大哥大) 关注 ────
            {12, 6}, {12, 7}, {12, 8}, {12, 9}, {12, 13},
            // ──── 用户 13 (核心测试用户) 关注 ────
            {13, 1}, {13, 2}, {13, 4}, {13, 5}, {13, 7}, {13, 8}, {13, 10}, {13, 12},
        };

        List<Follow> followList = new ArrayList<>();
        for (long[] pair : data) {
            // MySQL: 构建 Follow 实体
            Follow f = new Follow();
            f.setUserId(pair[0]);
            f.setFollowUserId(pair[1]);
            f.setCreateTime(LocalDateTime.now());
            followList.add(f);

            // Redis: SADD follows:{userId} {followUserId}
            stringRedisTemplate.opsForSet().add(
                    RedisConstants.FOLLOW_KEY + pair[0],
                    String.valueOf(pair[1]));
        }

        // 3. 批量写入 MySQL
        followService.saveBatch(followList);
        System.out.println("已写入 MySQL: " + followList.size() + " 条关注关系");
        System.out.println("已写入 Redis:  " + data.length + " 条 (SADD)");

        // 4. 统计每个用户的关注数和粉丝数
        Map<Long, Long> followeeCount = followList.stream()
                .collect(Collectors.groupingBy(Follow::getUserId, Collectors.counting()));
        Map<Long, Long> fansCount = followList.stream()
                .collect(Collectors.groupingBy(Follow::getFollowUserId, Collectors.counting()));

        System.out.println("\n========== 关注统计 ==========");
        System.out.printf("%-6s %-8s %-6s\n", "用户ID", "关注数", "粉丝数");
        for (long uid : followeeCount.keySet().stream().sorted().collect(Collectors.toList())) {
            long fc = fansCount.getOrDefault(uid, 0L);
            System.out.printf("%-6d %-8d %-6d\n", uid, followeeCount.get(uid), fc);
        }

        // 5. 用户13的共同关注预览
        List<Long> user13Follows = followList.stream()
                .filter(f -> f.getUserId() == 13L)
                .map(Follow::getFollowUserId)
                .collect(Collectors.toList());
        System.out.println("\n用户13关注了: " + user13Follows);
        System.out.println("========== 用户13与其他用户的共同关注 ==========");
        for (long uid = 1; uid <= 13; uid++) {
            if (uid == 13) continue;
            final long targetUid = uid;
            List<Long> theirFollows = followList.stream()
                    .filter(f -> f.getUserId() == targetUid)
                    .map(Follow::getFollowUserId)
                    .collect(Collectors.toList());
            List<Long> common = user13Follows.stream()
                    .filter(theirFollows::contains)
                    .collect(Collectors.toList());
            if (!common.isEmpty()) {
                boolean mutual = theirFollows.contains(13L);
                String tag = mutual ? " [互关]" : "";
                System.out.printf("  13 & %-2d → 共同关注 %s%s\n", uid, common, tag);
            }
        }

        // 6. Redis 验证: SINTER 查用户13与用户5的共同关注
        String key13 = RedisConstants.FOLLOW_KEY + 13;
        String key5 = RedisConstants.FOLLOW_KEY + 5;
        System.out.println("\n========== Redis SINTER 验证 ==========");
        System.out.println("SINTER " + key13 + " " + key5 + " → "
                + stringRedisTemplate.opsForSet().intersect(key13, key5));

        // SCARD 验证每个用户的关注数
        System.out.println("\nRedis Set 大小验证:");
        for (long uid = 1; uid <= 13; uid++) {
            Long size = stringRedisTemplate.opsForSet().size(RedisConstants.FOLLOW_KEY + uid);
            if (size != null && size > 0) {
                System.out.printf("  follows:%d → SCARD = %d\n", uid, size);
            }
        }

        // 6. 同步 tb_user_info 的 followee 和 fans 计数器
        System.out.println("\n========== 同步 tb_user_info 计数器 ==========");
        for (long uid = 1; uid <= 13; uid++) {
            UserInfo info = userInfoService.getById(uid);
            if (info == null) {
                info = new UserInfo();
                info.setUserId(uid);
                info.setCity("杭州");
            }
            info.setFollowee(followeeCount.getOrDefault(uid, 0L).intValue());
            info.setFans(fansCount.getOrDefault(uid, 0L).intValue());
            userInfoService.saveOrUpdate(info);
            System.out.printf("  用户 %-2d: followee=%d, fans=%d\n", uid, info.getFollowee(), info.getFans());
        }
    }

    @Test
    void testBackfillFeed() {
        List<Blog> blogs = blogService.list();
        if (blogs.isEmpty()) {
            System.out.println("没有博客数据");
            return;
        }
        // 清空旧的 feed 数据
        for (long uid = 1; uid <= 13; uid++) {
            stringRedisTemplate.delete(RedisConstants.FEED_KEY + uid);
        }

        int totalPushed = 0;
        for (Blog blog : blogs) {
            List<Follow> follows = followService.query()
                    .eq("follow_user_id", blog.getUserId())
                    .list();
            for (Follow follow : follows) {
                String key = RedisConstants.FEED_KEY + follow.getUserId();
                stringRedisTemplate.opsForZSet().add(
                        key, blog.getId().toString(), System.currentTimeMillis());
                totalPushed++;
            }
        }
        System.out.println("已为 " + blogs.size() + " 条笔记回填 feed，共推送 " + totalPushed + " 次");
    }
}
