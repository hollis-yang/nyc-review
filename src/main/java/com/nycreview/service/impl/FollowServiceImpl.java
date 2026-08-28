package com.nycreview.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.nycreview.dto.Result;
import com.nycreview.dto.UserDTO;
import com.nycreview.entity.Follow;
import com.nycreview.entity.UserInfo;
import com.nycreview.mapper.FollowMapper;
import com.nycreview.service.IFollowService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.service.IUserService;
import com.nycreview.service.IUserInfoService;
import com.nycreview.utils.UserHolder;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class FollowServiceImpl extends ServiceImpl<FollowMapper, Follow> implements IFollowService {

    @Resource
    private IUserService userService;

    @Resource
    private IUserInfoService userInfoService;

    @Override
    public Result followCommons(Long id) {
        // 1.获取当前用户
        Long userId = UserHolder.getUser().getId();
        if (id == null || userService.getById(id) == null) {
            return Result.fail("User not found");
        }
        // 2.MySQL 是关注关系的最终数据源，避免 Redis Set 丢失导致结果错误
        List<Long> myFollowIds = query()
                .eq("user_id", userId)
                .list()
                .stream()
                .map(Follow::getFollowUserId)
                .collect(Collectors.toList());
        if (myFollowIds.isEmpty()) {
            // 无交集
            return Result.ok(Collections.emptyList());
        }
        List<Long> ids = query()
                .eq("user_id", id)
                .in("follow_user_id", myFollowIds)
                .list()
                .stream()
                .map(Follow::getFollowUserId)
                .collect(Collectors.toList());
        if (ids.isEmpty()) {
            return Result.ok(Collections.emptyList());
        }
        // 4.查询用户
        List<UserDTO> userDTOS = userService.listByIds(ids)
                .stream()
                .map(user -> BeanUtil.copyProperties(user, UserDTO.class))
                .collect(Collectors.toList());
        return Result.ok(userDTOS);
    }

    @Override
    @Transactional
    public Result follow(Long followUserId, Boolean isFollow) {
        // 1.获取用户
        Long userId = UserHolder.getUser().getId();
        if (followUserId == null || isFollow == null) {
            return Result.fail("Invalid follow request");
        }
        if (userId.equals(followUserId)) {
            return Result.fail("You cannot follow yourself");
        }
        if (userService.getById(followUserId) == null) {
            return Result.fail("User not found");
        }
        ensureUserInfo(userId);
        ensureUserInfo(followUserId);
        // 2.true->关注，false->取关
        if (isFollow) {
            long existing = query()
                    .eq("user_id", userId)
                    .eq("follow_user_id", followUserId)
                    .count();
            if (existing > 0) {
                return Result.ok();
            }
            // 3.关注->新增数据
            Follow follow = new Follow();
            follow.setFollowUserId(followUserId);
            follow.setUserId(userId);
            boolean isSuccess;
            try {
                isSuccess = save(follow);
            } catch (DuplicateKeyException duplicate) {
                return Result.ok();
            }
            if (!isSuccess) {
                return Result.fail("Failed to update follow status");
            }
            updateFollowCount(userId, "followee", 1);
            updateFollowCount(followUserId, "fans", 1);
        } else {
            // 4.取关->删除数据
            boolean isSuccess = remove(new QueryWrapper<Follow>()
                    .eq("user_id", userId)
                    .eq("follow_user_id", followUserId));
            if (isSuccess) {
                updateFollowCount(userId, "followee", -1);
                updateFollowCount(followUserId, "fans", -1);
            }
        }
        return Result.ok();
    }

    @Override
    public Result isFollow(Long followUserId) {
        // 1.获取用户
        Long userId = UserHolder.getUser().getId();
        // 2.查询是否关注
        long count = query().eq("follow_user_id", followUserId).eq("user_id", userId).count();
        // 3.count>0 -> 关注
        return Result.ok(count > 0);
    }

    private void ensureUserInfo(Long userId) {
        if (userInfoService.getById(userId) != null) {
            return;
        }
        UserInfo info = new UserInfo();
        info.setUserId(userId);
        info.setFans(0);
        info.setFollowee(0);
        info.setCredits(0);
        info.setLevel(false);
        try {
            if (!userInfoService.save(info)) {
                throw new IllegalStateException("Failed to initialize the user profile");
            }
        } catch (DuplicateKeyException ignored) {
            // 另一个并发事务已经补建了资料行。
        }
    }

    private void updateFollowCount(Long userId, String column, int delta) {
        boolean updated = userInfoService.update()
                .setSql(column + " = GREATEST(COALESCE(" + column + ", 0) + " + delta + ", 0)")
                .eq("user_id", userId)
                .update();
        if (!updated) {
            throw new IllegalStateException("Failed to update follow statistics");
        }
    }
}
