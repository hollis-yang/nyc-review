package com.hmdp.messaging;

import com.hmdp.config.RabbitMqConfig;
import com.hmdp.entity.VoucherOrder;
import com.hmdp.service.IVoucherOrderService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class VoucherOrderConsumer {

    private final IVoucherOrderService voucherOrderService;

    public VoucherOrderConsumer(IVoucherOrderService voucherOrderService) {
        this.voucherOrderService = voucherOrderService;
    }

    @RabbitListener(
            queues = RabbitMqConfig.ORDER_QUEUE,
            containerFactory = "voucherOrderRabbitListenerContainerFactory"
    )
    public void consume(VoucherOrderMessage message) {
        VoucherOrder order = new VoucherOrder();
        order.setId(message.id());
        order.setUserId(message.userId());
        order.setVoucherId(message.voucherId());
        try {
            voucherOrderService.createVoucherOrder(order);
        } catch (DuplicateKeyException duplicate) {
            log.info("RabbitMQ重复订单已由数据库唯一约束拦截 orderId={}", message.id());
        }
    }
}
