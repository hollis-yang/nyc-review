package com.nycreview.agentapi.controller;

import com.nycreview.agentapi.dto.AgentActionExecuteRequest;
import com.nycreview.agentapi.service.AgentActionExecutionService;
import com.nycreview.dto.Result;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/agent/actions")
public class AgentActionToolController {

    @Resource
    private AgentActionExecutionService actionExecutionService;

    @PostMapping("/execute")
    public Result execute(@RequestBody AgentActionExecuteRequest request) {
        return actionExecutionService.execute(request);
    }

    @GetMapping("/preferences")
    public Result preferences() {
        return actionExecutionService.preferences();
    }
}
