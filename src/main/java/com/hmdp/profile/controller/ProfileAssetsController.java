package com.hmdp.profile.controller;

import com.hmdp.dto.Result;
import com.hmdp.profile.service.ProfileAssetsService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/profile/assets")
public class ProfileAssetsController {

    private final ProfileAssetsService profileAssetsService;

    public ProfileAssetsController(ProfileAssetsService profileAssetsService) {
        this.profileAssetsService = profileAssetsService;
    }

    @GetMapping
    public Result assets() {
        return Result.ok(profileAssetsService.assets());
    }

    @PutMapping("/memories/{id}")
    public Result updateMemory(@PathVariable("id") Long id, @RequestBody MemoryUpdateRequest request) {
        try {
            return profileAssetsService.updateMemory(id, request == null ? null : request.value())
                    ? Result.ok()
                    : Result.fail("Memory not found");
        } catch (IllegalArgumentException exception) {
            return Result.fail(exception.getMessage());
        }
    }

    @DeleteMapping("/memories/{id}")
    public Result deleteMemory(@PathVariable("id") Long id) {
        return profileAssetsService.deleteMemory(id)
                ? Result.ok()
                : Result.fail("Memory not found");
    }

    public record MemoryUpdateRequest(String value) {}
}
