package com.nycreview.service;

import com.nycreview.config.UploadProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
public class ImageStorageService {

    static final long MAX_IMAGE_SIZE = 5L * 1024 * 1024;

    private static final Pattern PUBLIC_IMAGE_PATH = Pattern.compile(
            "^/imgs/blogs/(\\d+)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.(?:jpg|png|webp))$"
    );

    private final UploadProperties uploadProperties;

    public String store(MultipartFile image, Long userId) {
        validateUpload(image, userId);
        String extension = detectImageExtension(image);
        Path userDirectory = prepareUserDirectory(userId);
        String fileName = UUID.randomUUID() + "." + extension;
        Path target = userDirectory.resolve(fileName).normalize();
        ensureDirectChild(userDirectory, target);

        try (InputStream inputStream = image.getInputStream()) {
            Files.copy(inputStream, target);
        } catch (IOException e) {
            try {
                Files.deleteIfExists(target);
            } catch (IOException cleanupError) {
                e.addSuppressed(cleanupError);
            }
            throw new IllegalStateException("Failed to save the image", e);
        }
        return "/imgs/blogs/" + userId + "/" + fileName;
    }

    public boolean delete(String publicPath, Long userId) {
        if (publicPath == null || userId == null) {
            throw new IllegalArgumentException("Invalid image path");
        }

        Matcher matcher = PUBLIC_IMAGE_PATH.matcher(publicPath);
        if (!matcher.matches()) {
            throw new IllegalArgumentException("Invalid image path");
        }

        Long ownerId;
        try {
            ownerId = Long.valueOf(matcher.group(1));
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("Invalid image path");
        }
        if (!userId.equals(ownerId)) {
            throw new IllegalArgumentException("You can only delete images you uploaded");
        }

        Path root = uploadRoot();
        Path userDirectory = root.resolve("blogs").resolve(userId.toString()).normalize();
        ensureWithinRoot(root, userDirectory);
        if (!Files.isDirectory(userDirectory, LinkOption.NOFOLLOW_LINKS)) {
            return false;
        }

        try {
            Path realRoot = root.toRealPath();
            Path realUserDirectory = userDirectory.toRealPath();
            ensureWithinRoot(realRoot, realUserDirectory);
            Path target = realUserDirectory.resolve(matcher.group(2)).normalize();
            ensureDirectChild(realUserDirectory, target);
            if (Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS)) {
                throw new IllegalArgumentException("Invalid image path");
            }
            return Files.deleteIfExists(target);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to delete the image", e);
        }
    }

    private void validateUpload(MultipartFile image, Long userId) {
        if (userId == null) {
            throw new IllegalArgumentException("Please sign in first");
        }
        if (image == null || image.isEmpty()) {
            throw new IllegalArgumentException("Please select an image");
        }
        if (image.getSize() > MAX_IMAGE_SIZE) {
            throw new IllegalArgumentException("Images cannot exceed 5 MB");
        }
    }

    private String detectImageExtension(MultipartFile image) {
        try (InputStream inputStream = image.getInputStream()) {
            byte[] header = inputStream.readNBytes(12);
            if (isJpeg(header)) {
                return "jpg";
            }
            if (isPng(header)) {
                return "png";
            }
            if (isWebp(header)) {
                return "webp";
            }
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read the image", e);
        }
        throw new IllegalArgumentException("Only JPEG, PNG, and WebP images are supported");
    }

    private Path prepareUserDirectory(Long userId) {
        Path root = uploadRoot();
        Path userDirectory = root.resolve("blogs").resolve(userId.toString()).normalize();
        ensureWithinRoot(root, userDirectory);
        try {
            Files.createDirectories(userDirectory);
            if (!Files.isDirectory(userDirectory, LinkOption.NOFOLLOW_LINKS)) {
                throw new IllegalStateException("The image directory is unavailable");
            }
            Path realRoot = root.toRealPath();
            Path realUserDirectory = userDirectory.toRealPath();
            ensureWithinRoot(realRoot, realUserDirectory);
            return realUserDirectory;
        } catch (IOException e) {
            throw new IllegalStateException("Failed to create the image directory", e);
        }
    }

    private Path uploadRoot() {
        Path imageDir = uploadProperties.getImageDir();
        if (imageDir == null) {
            throw new IllegalStateException("The image upload directory is not configured");
        }
        return imageDir.toAbsolutePath().normalize();
    }

    private void ensureWithinRoot(Path root, Path path) {
        if (!path.startsWith(root)) {
            throw new IllegalArgumentException("Invalid image path");
        }
    }

    private void ensureDirectChild(Path directory, Path target) {
        ensureWithinRoot(directory, target);
        if (!directory.equals(target.getParent())) {
            throw new IllegalArgumentException("Invalid image path");
        }
    }

    private boolean isJpeg(byte[] header) {
        return header.length >= 3
                && unsigned(header[0]) == 0xFF
                && unsigned(header[1]) == 0xD8
                && unsigned(header[2]) == 0xFF;
    }

    private boolean isPng(byte[] header) {
        int[] signature = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
        if (header.length < signature.length) {
            return false;
        }
        for (int i = 0; i < signature.length; i++) {
            if (unsigned(header[i]) != signature[i]) {
                return false;
            }
        }
        return true;
    }

    private boolean isWebp(byte[] header) {
        return header.length >= 12
                && header[0] == 'R' && header[1] == 'I' && header[2] == 'F' && header[3] == 'F'
                && header[8] == 'W' && header[9] == 'E' && header[10] == 'B' && header[11] == 'P';
    }

    private int unsigned(byte value) {
        return value & 0xFF;
    }
}
