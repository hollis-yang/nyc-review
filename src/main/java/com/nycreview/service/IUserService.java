package com.nycreview.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.nycreview.dto.LoginFormDTO;
import com.nycreview.dto.Result;
import com.nycreview.entity.User;

import jakarta.servlet.http.HttpSession;

public interface IUserService extends IService<User> {

    Result sendCode(String phone, HttpSession session);

    Result login(LoginFormDTO loginForm, HttpSession session);

    Result sign();

    Result signCount();
}
