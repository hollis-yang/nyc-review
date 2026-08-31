package com.nycreview.controller;

import com.nycreview.dto.Result;
import com.nycreview.service.AccountSecurityService;
import com.nycreview.service.IUserService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class UserControllerAuthContractTest {

    private IUserService userService;
    private AccountSecurityService accountSecurityService;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        userService = mock(IUserService.class);
        accountSecurityService = mock(AccountSecurityService.class);
        UserController controller = new UserController();
        ReflectionTestUtils.setField(controller, "userService", userService);
        ReflectionTestUtils.setField(controller, "accountSecurityService", accountSecurityService);
        mvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void smsEndpointIsExplicitlyGone() throws Exception {
        mvc.perform(post("/user/code"))
                .andExpect(status().isGone())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.errorMsg").value("SMS login is disabled"));
    }

    @Test
    void loginAcceptsThePasswordOnlyInternationalPhoneContract() throws Exception {
        when(userService.login(any(), eq("198.51.100.7"))).thenReturn(Result.ok("login-token"));

        mvc.perform(post("/user/login")
                        .with(request -> {
                            request.setRemoteAddr("198.51.100.7");
                            return request;
                        })
                        .contentType("application/json")
                        .content("""
                                {"regionCode":"US","phoneNumber":"2125550123","password":"test-password"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").value("login-token"));

        verify(userService).login(any(), eq("198.51.100.7"));
    }

    @Test
    void registrationUsesTheTrustedProxyAddress() throws Exception {
        when(userService.register(any(), eq("203.0.113.8"))).thenReturn(Result.ok("register-token"));

        mvc.perform(post("/user/register")
                        .header("X-Real-IP", "203.0.113.8")
                        .contentType("application/json")
                        .content("""
                                {"regionCode":"TW","phoneNumber":"0912345678","password":"test-password","nickName":"New User"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").value("register-token"));

        verify(userService).register(any(), eq("203.0.113.8"));
    }

    @Test
    void passwordResetUsesPhoneRecoveryKeyAndNewPassword() throws Exception {
        mvc.perform(post("/user/password/reset")
                        .contentType("application/json")
                        .content("""
                                {
                                  "regionCode":"US",
                                  "phoneNumber":"2125550123",
                                  "recoveryKey":"Recovery-Key-123!",
                                  "newPassword":"New-password-2!"
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(accountSecurityService).resetPassword(any(), eq("127.0.0.1"));
    }

    @Test
    void checkInCalendarAcceptsAnExplicitMonth() throws Exception {
        when(userService.signCalendar(2026, 8)).thenReturn(Result.ok());

        mvc.perform(get("/user/sign/calendar")
                        .param("year", "2026")
                        .param("month", "8"))
                .andExpect(status().isOk());

        verify(userService).signCalendar(2026, 8);
    }
}
