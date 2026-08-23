package com.hmdp.config;

import com.hmdp.service.ShopMapService;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class WebExceptionAdviceTest {

    @Test
    void invalidArgumentsProduceHttp400InsteadOfTheGenericRuntimeResponse() throws Exception {
        MockMvc mvc = MockMvcBuilders
                .standaloneSetup(new InvalidRequestController())
                .setControllerAdvice(new WebExceptionAdvice())
                .build();

        mvc.perform(get("/test/invalid").accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.errorMsg").value("invalid viewport"));
    }

    @Test
    void missingRequiredParametersAlsoProduceHttp400() throws Exception {
        MockMvc mvc = MockMvcBuilders
                .standaloneSetup(new InvalidRequestController())
                .setControllerAdvice(new WebExceptionAdvice())
                .build();

        mvc.perform(get("/test/requires-west").accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.errorMsg").value("west is required"));
    }

    @Test
    void missingMapProjectionProducesHttp503() throws Exception {
        MockMvc mvc = MockMvcBuilders
                .standaloneSetup(new InvalidRequestController())
                .setControllerAdvice(new WebExceptionAdvice())
                .build();

        mvc.perform(get("/test/map-unavailable").accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.errorMsg").value("Map data has not been initialized"));
    }

    @RestController
    private static class InvalidRequestController {
        @GetMapping("/test/invalid")
        void invalid() {
            throw new IllegalArgumentException("invalid viewport");
        }

        @GetMapping("/test/requires-west")
        void requiresWest(@RequestParam("west") String west) {
        }

        @GetMapping("/test/map-unavailable")
        void mapUnavailable() {
            throw new ShopMapService.MapDataUnavailableException("Map data has not been initialized");
        }
    }
}
