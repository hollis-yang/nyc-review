package com.nycreview.controller;

import com.nycreview.dto.Result;
import com.nycreview.service.ImageStorageService;
import com.nycreview.utils.UserHolder;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/upload")
@RequiredArgsConstructor
public class UploadController {

    private final ImageStorageService imageStorageService;

    @PostMapping("/blog")
    public Result uploadImage(@RequestParam("file") MultipartFile image) {
        try {
            Long userId = UserHolder.getUser().getId();
            return Result.ok(imageStorageService.store(image, userId));
        } catch (IllegalArgumentException e) {
            return Result.fail(e.getMessage());
        }
    }

    @DeleteMapping("/blog")
    public Result deleteBlogImage(@RequestParam("name") String publicPath) {
        try {
            Long userId = UserHolder.getUser().getId();
            if (!imageStorageService.delete(publicPath, userId)) {
                return Result.fail("Image not found");
            }
            return Result.ok();
        } catch (IllegalArgumentException e) {
            return Result.fail(e.getMessage());
        }
    }
}
