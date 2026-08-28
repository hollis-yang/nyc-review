package com.nycreview.dto;

import lombok.Data;

@Data
public class LoginFormDTO {
    /** ISO 3166-1 alpha-2 region, for example US, CN, or TW. */
    private String regionCode;

    /** National-format number entered next to the region selector. */
    private String phoneNumber;

    /** Backward-compatible E.164 field for non-browser clients. */
    private String phone;

    private String password;
}
