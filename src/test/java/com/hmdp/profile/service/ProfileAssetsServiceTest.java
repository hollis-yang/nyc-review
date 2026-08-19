package com.hmdp.profile.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ProfileAssetsServiceTest {

    @Test
    void memoryValuesAreTrimmedAndBoundedBeforeAnyWrite() {
        assertEquals("quiet dinners", ProfileAssetsService.validateMemoryValue("  quiet dinners  "));
        assertThrows(IllegalArgumentException.class, () -> ProfileAssetsService.validateMemoryValue(" "));
        assertThrows(
                IllegalArgumentException.class,
                () -> ProfileAssetsService.validateMemoryValue("x".repeat(501))
        );
    }
}
