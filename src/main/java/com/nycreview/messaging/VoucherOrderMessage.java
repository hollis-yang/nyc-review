package com.nycreview.messaging;

public record VoucherOrderMessage(Long id, Long userId, Long voucherId) {

    public VoucherOrderMessage {
        if (id == null || id <= 0 || userId == null || userId <= 0 || voucherId == null || voucherId <= 0) {
            throw new IllegalArgumentException("Voucher order message identifiers must be positive");
        }
    }
}
