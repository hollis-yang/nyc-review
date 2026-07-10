package com.hmdp.service;

import com.hmdp.config.UploadProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ImageStorageServiceTest {

    private static final byte[] PNG_BYTES = {
            (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x00
    };

    @TempDir
    Path uploadRoot;

    private ImageStorageService imageStorageService;

    @BeforeEach
    void setUp() {
        UploadProperties properties = new UploadProperties();
        properties.setImageDir(uploadRoot);
        imageStorageService = new ImageStorageService(properties);
    }

    @Test
    void storesDetectedImageInCurrentUserDirectory() {
        MockMultipartFile image = new MockMultipartFile(
                "file", "disguised.txt", "text/plain", PNG_BYTES
        );

        String publicPath = imageStorageService.store(image, 42L);

        assertTrue(publicPath.matches(
                "^/imgs/blogs/42/[0-9a-f-]{36}\\.png$"
        ));
        assertTrue(Files.exists(resolvePublicPath(publicPath)));
    }

    @Test
    void rejectsFileWithoutSupportedImageSignature() {
        MockMultipartFile image = new MockMultipartFile(
                "file", "fake.png", "image/png", "<script>alert(1)</script>".getBytes()
        );

        assertThrows(IllegalArgumentException.class, () -> imageStorageService.store(image, 42L));
    }

    @Test
    void rejectsImageLargerThanFiveMegabytes() {
        byte[] oversized = new byte[(5 * 1024 * 1024) + 1];
        System.arraycopy(PNG_BYTES, 0, oversized, 0, PNG_BYTES.length);
        MockMultipartFile image = new MockMultipartFile(
                "file", "large.png", "image/png", oversized
        );

        assertThrows(IllegalArgumentException.class, () -> imageStorageService.store(image, 42L));
    }

    @Test
    void deletesImageOwnedByCurrentUser() {
        MockMultipartFile image = new MockMultipartFile(
                "file", "image.png", "image/png", PNG_BYTES
        );
        String publicPath = imageStorageService.store(image, 42L);
        Path storedFile = resolvePublicPath(publicPath);

        assertTrue(imageStorageService.delete(publicPath, 42L));
        assertFalse(Files.exists(storedFile));
    }

    @Test
    void rejectsDeletingAnotherUsersImage() {
        MockMultipartFile image = new MockMultipartFile(
                "file", "image.png", "image/png", PNG_BYTES
        );
        String publicPath = imageStorageService.store(image, 42L);

        assertThrows(IllegalArgumentException.class, () -> imageStorageService.delete(publicPath, 7L));
        assertTrue(Files.exists(resolvePublicPath(publicPath)));
    }

    @Test
    void rejectsTraversalAndLegacyPaths() {
        assertThrows(
                IllegalArgumentException.class,
                () -> imageStorageService.delete("/imgs/blogs/42/../../application.yaml", 42L)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> imageStorageService.delete("/imgs/blogs/a/b/file.png", 42L)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> imageStorageService.delete("/etc/passwd", 42L)
        );
    }

    private Path resolvePublicPath(String publicPath) {
        return uploadRoot.resolve(publicPath.substring("/imgs/".length()));
    }
}
