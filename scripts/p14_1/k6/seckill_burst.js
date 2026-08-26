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

const iterations = Number(__ENV.ITERATIONS || '1000');
const vus = Number(__ENV.VUS || '250');

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    burst: {
      executor: 'shared-iterations',
      vus,
      iterations,
      maxDuration: __ENV.MAX_DURATION || '2m',
    },
  },
  thresholds: {
    ...defaultThresholds,
    http_req_duration: ['p(95)<750', 'p(99)<1500'],
  },
};

export default function () {
  const token = tokenFor(exec.scenario.iterationInTest);
  const response = http.post(`${baseUrl}/voucher-order/seckill/${voucherId}`, null, {
    headers: { authorization: token },
    tags: { endpoint: 'seckill' },
  });
  const outcome = classifyBusinessResponse(response);
  check(outcome, {
    'business outcome classified': (value) => !['technical_error', 'invalid_json'].includes(value),
  });
}
