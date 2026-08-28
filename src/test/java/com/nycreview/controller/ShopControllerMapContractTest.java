package com.nycreview.controller;

import com.nycreview.config.WebExceptionAdvice;
import com.nycreview.dto.map.ShopMapResponse;
import com.nycreview.service.ShopMapService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ShopControllerMapContractTest {

    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        ShopMapResponse response = new ShopMapResponse(
                ShopMapResponse.Mode.BOROUGH_CLUSTERS,
                10,
                15,
                "nyc-hybrid-v1",
                5,
                false,
                null,
                null,
                List.of(new ShopMapResponse.ClusterItem(
                        "BOROUGH",
                        "borough:manhattan",
                        "Manhattan",
                        "Manhattan",
                        40.75,
                        -73.98,
                        5,
                        new ShopMapResponse.Bounds(-74.02, 40.70, -73.93, 40.84),
                        Map.of(1L, 5L)
                ))
        );
        ShopMapService service = new ShopMapService(null) {
            @Override
            public ShopMapResponse query(
                    String west,
                    String south,
                    String east,
                    String north,
                    String zoom,
                    String typeIds
            ) {
                return response;
            }
        };
        ShopController controller = new ShopController();
        ReflectionTestUtils.setField(controller, "shopMapService", service);
        mvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new WebExceptionAdvice())
                .build();
    }

    @Test
    void exposesTheStableMapEnvelopeAndClusterContract() throws Exception {
        mvc.perform(get("/shop/map")
                        .param("west", "-74.1")
                        .param("south", "40.4")
                        .param("east", "-73.7")
                        .param("north", "40.95")
                        .param("zoom", "10")
                        .param("typeIds", "1,2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.mode").value("BOROUGH_CLUSTERS"))
                .andExpect(jsonPath("$.data.detailZoom").value(15))
                .andExpect(jsonPath("$.data.dataVersion").value("nyc-hybrid-v1"))
                .andExpect(jsonPath("$.data.matchedCount").value(5))
                .andExpect(jsonPath("$.data.truncated").value(false))
                .andExpect(jsonPath("$.data.items[0].kind").value("BOROUGH"))
                .andExpect(jsonPath("$.data.items[0].bounds.west").value(-74.02))
                .andExpect(jsonPath("$.data.items[0].countsByType['1']").value(5));
    }

    @Test
    void rejectsAMissingViewportParameterWithHttp400() throws Exception {
        mvc.perform(get("/shop/map")
                        .param("south", "40.4")
                        .param("east", "-73.7")
                        .param("north", "40.95")
                        .param("zoom", "10"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.errorMsg").value("west is required"));
    }
}
