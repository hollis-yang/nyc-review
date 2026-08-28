import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

export const baseUrl = __ENV.BASE_URL || 'http://spring:8081';
export const voucherId = Number(__ENV.VOUCHER_ID || '9140001');
export const accepted = new Counter('business_accepted');
export const rejected = new Counter('business_rejected');
export const duplicates = new Counter('business_duplicate');
export const outOfStock = new Counter('business_out_of_stock');
export const technicalErrors = new Rate('technical_errors');
export const businessDuration = new Trend('business_duration', true);

export const tokens = new SharedArray('p14-load-tokens', () => {
  const path = __ENV.TOKENS_FILE || '/workspace/reports/runtime/tokens.json';
  return JSON.parse(open(path));
});

export function tokenFor(index) {
  return tokens[index % tokens.length].token;
}

export function classifyBusinessResponse(response) {
  businessDuration.add(response.timings.duration);
  if (response.status !== 200) {
    technicalErrors.add(true);
    return 'technical_error';
  }
  let body;
  try {
    body = response.json();
  } catch (_) {
    technicalErrors.add(true);
    return 'invalid_json';
  }
  technicalErrors.add(false);
  if (body && body.success === true) {
    accepted.add(1);
    return 'accepted';
  }
  rejected.add(1);
  const message = String((body && body.errorMsg) || '').toLowerCase();
  if (message.includes('duplicate') || message.includes('already') || message.includes('重复')) {
    duplicates.add(1);
    return 'duplicate';
  }
  if (message.includes('stock') || message.includes('inventory') || message.includes('库存')) {
    outOfStock.add(1);
    return 'out_of_stock';
  }
  return 'business_rejection';
}

export function recordApiResponse(response, label) {
  let valid = response.status === 200;
  if (valid) {
    try {
      valid = response.json('success') !== false;
    } catch (_) {
      valid = false;
    }
  }
  technicalErrors.add(!valid);
  check(response, { [label]: () => valid });
  return valid;
}

export const defaultThresholds = {
  http_req_failed: ['rate<0.01'],
  technical_errors: ['rate<0.01'],
};
