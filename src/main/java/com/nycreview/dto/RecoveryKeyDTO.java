package com.nycreview.dto;

import lombok.Data;

@Data
public class RecoveryKeyDTO {
    private String currentPassword;
    private String recoveryKey;
}
