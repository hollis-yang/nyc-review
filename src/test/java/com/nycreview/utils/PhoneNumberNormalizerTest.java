package com.nycreview.utils;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class PhoneNumberNormalizerTest {

    private final PhoneNumberNormalizer normalizer = new PhoneNumberNormalizer();

    @Test
    void normalizesUsMainlandChinaAndTaiwanNumbersToE164() {
        assertEquals("+12125550123", normalizer.normalize("US", "2125550123", null));
        assertEquals("+8613800138000", normalizer.normalize("CN", "13800138000", null));
        assertEquals("+886912345678", normalizer.normalize("TW", "0912345678", null));
    }

    @Test
    void acceptsBackwardCompatibleE164InputWithoutARegion() {
        assertEquals("+85251234567", normalizer.normalize(null, null, "+85251234567"));
    }

    @Test
    void rejectsInvalidNumbersAndMissingRegions() {
        assertThrows(IllegalArgumentException.class, () -> normalizer.normalize("US", "123", null));
        assertThrows(IllegalArgumentException.class, () -> normalizer.normalize(null, "2125550123", null));
    }
}
