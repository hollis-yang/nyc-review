package com.hmdp.utils;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RegexUtilsInternationalPhoneTest {

    @Test
    void acceptsE164UsAndLegacyChineseNumbers() {
        assertFalse(RegexUtils.isPhoneInvalid("+12125550123"));
        assertFalse(RegexUtils.isPhoneInvalid("13686869696"));
    }

    @Test
    void rejectsMalformedNumbers() {
        assertTrue(RegexUtils.isPhoneInvalid("+0123"));
        assertTrue(RegexUtils.isPhoneInvalid("212-555-0123"));
        assertTrue(RegexUtils.isPhoneInvalid("123"));
    }
}
