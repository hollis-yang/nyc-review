package com.nycreview;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.EnableAspectJAutoProxy;

@MapperScan("com.nycreview.mapper")
@SpringBootApplication
@EnableAspectJAutoProxy(exposeProxy = true) // 开启 AspectJ 自动代理，并暴露代理对象
public class NycReviewApplication {

    public static void main(String[] args) {
        SpringApplication.run(NycReviewApplication.class, args);
    }

}
