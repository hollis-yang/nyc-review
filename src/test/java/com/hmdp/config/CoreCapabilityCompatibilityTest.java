package com.hmdp.config;

import com.hmdp.controller.TranslateController;
import com.hmdp.controller.VoucherOrderController;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class CoreCapabilityCompatibilityTest {

    @Test
    void translationEndpointsRemainBackwardCompatible() throws Exception {
        RequestMapping baseMapping = TranslateController.class.getAnnotation(RequestMapping.class);
        assertNotNull(baseMapping);
        assertArrayEquals(new String[]{"/translate"}, baseMapping.value());

        assertPostMapping(
                TranslateController.class.getDeclaredMethod("translateBlog", Long.class, String.class),
                "/blog"
        );
        assertPostMapping(
                TranslateController.class.getDeclaredMethod("translateComment", Long.class, String.class),
                "/comment"
        );
        assertPostMapping(
                TranslateController.class.getDeclaredMethod("translateShop", Long.class, String.class),
                "/shop"
        );
    }

    @Test
    void manualSeckillEndpointRemainsAvailableToTheFrontend() throws Exception {
        RequestMapping baseMapping = VoucherOrderController.class.getAnnotation(RequestMapping.class);
        assertNotNull(baseMapping);
        assertArrayEquals(new String[]{"/voucher-order"}, baseMapping.value());

        assertPostMapping(
                VoucherOrderController.class.getDeclaredMethod("seckillVoucher", Long.class),
                "seckill/{id}"
        );
    }

    private void assertPostMapping(Method method, String expectedPath) {
        PostMapping mapping = method.getAnnotation(PostMapping.class);
        assertNotNull(mapping);
        assertEquals(1, mapping.value().length);
        assertEquals(expectedPath, mapping.value()[0]);
    }
}
