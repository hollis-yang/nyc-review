package com.nycreview.service.impl;

import com.nycreview.entity.Blog;
import com.nycreview.entity.BlogComments;
import com.nycreview.entity.Voucher;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class ContentProvenanceWritePathTest {

    @Test
    void blogWritePathOverridesClientSuppliedSyntheticProvenance() {
        Blog blog = new Blog()
                .setSourceType("SYNTHETIC")
                .setDataVersion("forged-version");

        BlogServiceImpl.markUserSubmitted(blog);

        assertEquals("USER_SUBMITTED", blog.getSourceType());
        assertNull(blog.getDataVersion());
    }

    @Test
    void commentWritePathOverridesClientSuppliedSyntheticProvenance() {
        BlogComments comment = new BlogComments()
                .setSourceType("SYNTHETIC")
                .setDataVersion("forged-version");

        BlogCommentsServiceImpl.markUserSubmitted(comment);

        assertEquals("USER_SUBMITTED", comment.getSourceType());
        assertNull(comment.getDataVersion());
    }

    @Test
    void voucherWritePathCannotMasqueradeAsSeededContent() {
        Voucher voucher = new Voucher()
                .setSourceType("SYNTHETIC")
                .setDataVersion("forged-version");

        VoucherServiceImpl.markApiSubmitted(voucher);

        assertEquals("USER_SUBMITTED", voucher.getSourceType());
        assertNull(voucher.getDataVersion());
    }
}
