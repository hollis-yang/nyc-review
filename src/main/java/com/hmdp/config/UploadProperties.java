package com.hmdp.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.nio.file.Path;

@Component
@ConfigurationProperties(prefix = "hmdp.upload")
public class UploadProperties {

    private Path imageDir;

    public Path getImageDir() {
        return imageDir;
    }

    public void setImageDir(Path imageDir) {
        this.imageDir = imageDir;
    }
}
