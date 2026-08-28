package com.nycreview.utils;

import com.google.i18n.phonenumbers.NumberParseException;
import com.google.i18n.phonenumbers.PhoneNumberUtil;
import com.google.i18n.phonenumbers.Phonenumber.PhoneNumber;
import org.springframework.stereotype.Component;

import java.util.Locale;

@Component
public class PhoneNumberNormalizer {

    private final PhoneNumberUtil phoneNumberUtil = PhoneNumberUtil.getInstance();

    public String normalize(String regionCode, String nationalNumber, String e164Fallback) {
        String input = firstNonBlank(nationalNumber, e164Fallback);
        if (input == null) {
            throw new IllegalArgumentException("Phone number is required");
        }

        String normalizedRegion = normalizeRegion(regionCode, input);
        try {
            PhoneNumber parsed = phoneNumberUtil.parse(input.trim(), normalizedRegion);
            if (!phoneNumberUtil.isValidNumber(parsed)) {
                throw new IllegalArgumentException("Invalid phone number");
            }
            return phoneNumberUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164);
        } catch (NumberParseException e) {
            throw new IllegalArgumentException("Invalid phone number");
        }
    }

    private String normalizeRegion(String regionCode, String input) {
        if (input.trim().startsWith("+")) {
            // libphonenumber uses the ISO-like "ZZ" sentinel when the number
            // already carries an international country calling code.
            return "ZZ";
        }
        if (regionCode == null || !regionCode.trim().matches("[A-Za-z]{2}")) {
            throw new IllegalArgumentException("A valid phone region is required");
        }
        return regionCode.trim().toUpperCase(Locale.ROOT);
    }

    private String firstNonBlank(String preferred, String fallback) {
        if (preferred != null && !preferred.isBlank()) {
            return preferred;
        }
        if (fallback != null && !fallback.isBlank()) {
            return fallback;
        }
        return null;
    }
}
