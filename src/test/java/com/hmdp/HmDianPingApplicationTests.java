package com.hmdp;

import com.hmdp.entity.Blog;
import com.hmdp.entity.SeckillVoucher;
import com.hmdp.service.IBlogService;
import com.hmdp.service.ISeckillVoucherService;
import com.hmdp.service.impl.ShopServiceImpl;
import com.hmdp.utils.RedisConstants;
import com.hmdp.utils.RedisIdWorker;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;

import javax.annotation.Resource;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

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
}
