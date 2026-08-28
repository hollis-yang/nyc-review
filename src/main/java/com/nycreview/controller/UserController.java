package com.nycreview.controller;


import cn.hutool.core.bean.BeanUtil;
import com.nycreview.dto.LoginFormDTO;
import com.nycreview.dto.RegisterFormDTO;
import com.nycreview.dto.Result;
import com.nycreview.dto.UserDTO;
import com.nycreview.entity.User;
import com.nycreview.entity.UserInfo;
import com.nycreview.service.IUserInfoService;
import com.nycreview.service.IUserService;
import com.nycreview.utils.RedisConstants;
import com.nycreview.utils.UserHolder;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;

@Slf4j
@RestController
@RequestMapping("/user")
public class UserController {

    @Resource
    private IUserService userService;

    @Resource
    private IUserInfoService userInfoService;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @PostMapping("code")
    @ResponseStatus(HttpStatus.GONE)
    public Result sendCodeDisabled() {
        return Result.fail("SMS login is disabled");
    }

    @PostMapping("/login")
    public Result login(@RequestBody LoginFormDTO loginForm, HttpServletRequest request){
        return userService.login(loginForm, clientAddress(request));
    }

    @PostMapping("/register")
    public Result register(@RequestBody RegisterFormDTO registerForm, HttpServletRequest request) {
        return userService.register(registerForm, clientAddress(request));
    }

    /**
     * 登出功能
     * @return 无
     */
    @PostMapping("/logout")
    public Result logout(HttpServletRequest request){
        // 1.获取token
        String token = request.getHeader("authorization");
        if (token != null && !token.isEmpty()) {
            // 2.删除Redis中的用户信息
            stringRedisTemplate.delete(RedisConstants.LOGIN_USER_KEY + token);
        }
        // 3.清除ThreadLocal
        UserHolder.removeUser();
        return Result.ok();
    }

    @GetMapping("/me")
    public Result me(){
        // 获取当前登录的用户并返回
        UserDTO user = UserHolder.getUser();
        return Result.ok(user);
    }

    @GetMapping("/info/{id}")
    public Result info(@PathVariable("id") Long userId){
        // 查询详情
        UserInfo info = userInfoService.getById(userId);
        if (info == null) {
            // 没有详情，应该是第一次查看详情
            return Result.ok();
        }
        info.setCreateTime(null);
        info.setUpdateTime(null);
        // 返回
        return Result.ok(info);
    }

    @GetMapping("/{id}")
    public Result queryUserById(@PathVariable("id") Long userId){
        // 查询详情
        User user = userService.getById(userId);
        if (user == null) {
            return Result.ok();
        }
        UserDTO userDTO = BeanUtil.copyProperties(user, UserDTO.class);
        // 返回
        return Result.ok(userDTO);
    }

    @PostMapping("/sign")
    public Result sign() {
        return userService.sign();
    }

    @GetMapping("/sign/count")
    public Result signCount(){
        return userService.signCount();
    }

    /**
     * 更新用户基本信息（昵称、头像）
     */
    @PutMapping("/me")
    public Result updateMe(@RequestBody User user, HttpServletRequest request) {
        UserDTO userDTO = UserHolder.getUser();
        if (userDTO == null) {
            return Result.fail("Please sign in first");
        }
        // 防止修改其他用户
        user.setId(userDTO.getId());
        user.setPhone(null);
        user.setPassword(null);
        userService.updateById(user);
        // 更新Redis中的用户缓存
        String token = request.getHeader("authorization");
        if (token != null && !token.isEmpty()) {
            String key = RedisConstants.LOGIN_USER_KEY + token;
            if (user.getNickName() != null) {
                stringRedisTemplate.opsForHash().put(key, "nickName", user.getNickName());
            }
            if (user.getIcon() != null) {
                stringRedisTemplate.opsForHash().put(key, "icon", user.getIcon());
            }
        }
        return Result.ok();
    }

    /**
     * 更新用户详细信息（简介、性别、城市、生日）
     */
    @PutMapping("/info")
    public Result updateInfo(@RequestBody UserInfo userInfo) {
        UserDTO userDTO = UserHolder.getUser();
        if (userDTO == null) {
            return Result.fail("Please sign in first");
        }
        // 防止修改其他用户
        userInfo.setUserId(userDTO.getId());
        boolean saved = userInfoService.saveOrUpdate(userInfo);
        return saved ? Result.ok() : Result.fail("Failed to save the user profile");
    }

    private String clientAddress(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Real-IP");
        return forwarded == null || forwarded.isBlank() ? request.getRemoteAddr() : forwarded.trim();
    }
}
