package com.hmdp.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.rabbit.config.RetryInterceptorBuilder;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.rabbit.connection.CachingConnectionFactory;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.retry.RepublishMessageRecovererWithConfirms;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.boot.autoconfigure.amqp.SimpleRabbitListenerContainerFactoryConfigurer;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.retry.interceptor.RetryOperationsInterceptor;
import org.springframework.scheduling.annotation.EnableScheduling;

@Configuration
@EnableScheduling
public class RabbitMqConfig {

    public static final String ORDER_EXCHANGE = "hmdp.voucher.order.exchange";
    public static final String ORDER_QUEUE = "hmdp.voucher.order.queue";
    public static final String ORDER_ROUTING_KEY = "voucher.order.accepted";
    public static final String ERROR_EXCHANGE = "hmdp.voucher.order.error.exchange";
    public static final String ERROR_QUEUE = "hmdp.voucher.order.error.queue";
    public static final String ERROR_ROUTING_KEY = "voucher.order.failed";

    @Bean
    DirectExchange voucherOrderExchange() {
        return new DirectExchange(ORDER_EXCHANGE, true, false);
    }

    @Bean
    Queue voucherOrderQueue() {
        return QueueBuilder.durable(ORDER_QUEUE).build();
    }

    @Bean
    Binding voucherOrderBinding(
            @Qualifier("voucherOrderQueue") Queue voucherOrderQueue,
            @Qualifier("voucherOrderExchange") DirectExchange voucherOrderExchange
    ) {
        return BindingBuilder.bind(voucherOrderQueue).to(voucherOrderExchange).with(ORDER_ROUTING_KEY);
    }

    @Bean
    DirectExchange voucherOrderErrorExchange() {
        return new DirectExchange(ERROR_EXCHANGE, true, false);
    }

    @Bean
    Queue voucherOrderErrorQueue() {
        return QueueBuilder.durable(ERROR_QUEUE).build();
    }

    @Bean
    Binding voucherOrderErrorBinding(
            @Qualifier("voucherOrderErrorQueue") Queue voucherOrderErrorQueue,
            @Qualifier("voucherOrderErrorExchange") DirectExchange voucherOrderErrorExchange
    ) {
        return BindingBuilder.bind(voucherOrderErrorQueue)
                .to(voucherOrderErrorExchange)
                .with(ERROR_ROUTING_KEY);
    }

    @Bean
    MessageConverter rabbitMessageConverter(ObjectMapper objectMapper) {
        return new Jackson2JsonMessageConverter(objectMapper);
    }

    @Bean
    RetryOperationsInterceptor voucherOrderRetryInterceptor(RabbitTemplate rabbitTemplate) {
        RepublishMessageRecovererWithConfirms recoverer = new RepublishMessageRecovererWithConfirms(
                rabbitTemplate,
                ERROR_EXCHANGE,
                ERROR_ROUTING_KEY,
                CachingConnectionFactory.ConfirmType.CORRELATED
        );
        recoverer.setConfirmTimeout(5_000);
        return RetryInterceptorBuilder.stateless()
                .maxAttempts(5)
                .backOffOptions(250, 2.0, 2_000)
                .recoverer(recoverer)
                .build();
    }

    @Bean("voucherOrderRabbitListenerContainerFactory")
    SimpleRabbitListenerContainerFactory voucherOrderRabbitListenerContainerFactory(
            SimpleRabbitListenerContainerFactoryConfigurer configurer,
            ConnectionFactory connectionFactory,
            MessageConverter rabbitMessageConverter,
            RetryOperationsInterceptor voucherOrderRetryInterceptor
    ) {
        SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
        configurer.configure(factory, connectionFactory);
        factory.setMessageConverter(rabbitMessageConverter);
        factory.setAdviceChain(voucherOrderRetryInterceptor);
        factory.setDefaultRequeueRejected(false);
        return factory;
    }
}
