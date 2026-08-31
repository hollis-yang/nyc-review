package com.nycreview.dto;

import lombok.Data;

@Data
public class ResetPasswordDTO {
    private String regionCode;
    private String phoneNumber;
    private String phone;
    private String recoveryKey;
    private String newPassword;
}
