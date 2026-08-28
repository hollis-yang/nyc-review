package com.nycreview.dto;

import lombok.Data;

@Data
public class TranslateTextRequest {
    private String text;
    private String targetLang = "en";
}
