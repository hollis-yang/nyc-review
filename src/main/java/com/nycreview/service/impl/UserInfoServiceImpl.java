package com.nycreview.service.impl;

import com.nycreview.entity.UserInfo;
import com.nycreview.mapper.UserInfoMapper;
import com.nycreview.service.IUserInfoService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import org.springframework.stereotype.Service;

@Service
public class UserInfoServiceImpl extends ServiceImpl<UserInfoMapper, UserInfo> implements IUserInfoService {

}
