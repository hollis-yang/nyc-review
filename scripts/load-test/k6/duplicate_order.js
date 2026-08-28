import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import {
  baseUrl,
  classifyBusinessResponse,
  defaultThresholds,
  tokenFor,
  voucherId,
} from './common.js';

const users = Number(__ENV.UNIQUE_USERS || '200');
const repeats = Number(__ENV.REPEATS || '5');

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    duplicates: {
      executor: 'shared-iterations',
      vus: Number(__ENV.VUS || '100'),
      iterations: users * repeats,
      maxDuration: __ENV.MAX_DURATION || '2m',
    },
  },
  thresholds: {
    ...defaultThresholds,
    http_req_duration: ['p(95)<750', 'p(99)<1500'],
  },
};

export default function () {
  const userIndex = exec.scenario.iterationInTest % users;
  const response = http.post(`${baseUrl}/voucher-order/seckill/${voucherId}`, null, {
    headers: { authorization: tokenFor(userIndex) },
    tags: { endpoint: 'seckill_duplicate' },
  });
  const outcome = classifyBusinessResponse(response);
  check(outcome, {
    'accepted or business rejected': (value) => !['technical_error', 'invalid_json'].includes(value),
  });
}
