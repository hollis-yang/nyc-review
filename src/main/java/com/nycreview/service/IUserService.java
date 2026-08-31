package com.nycreview.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.nycreview.dto.LoginFormDTO;
import com.nycreview.dto.RegisterFormDTO;
import com.nycreview.dto.Result;
import com.nycreview.entity.User;

public interface IUserService extends IService<User> {

    Result login(LoginFormDTO loginForm, String clientAddress);

    Result register(RegisterFormDTO registerForm, String clientAddress);

    Result sign();

    Result signCount();

    Result signCalendar(Integer year, Integer month);
}
