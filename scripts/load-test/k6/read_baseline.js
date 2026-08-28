import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import { baseUrl } from './common.js';

const contractErrors = new Rate('contract_errors');
const rate = Number(__ENV.RATE || '50');
const duration = __ENV.DURATION || '3m';

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    reads: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration,
      preAllocatedVUs: Number(__ENV.PRE_ALLOCATED_VUS || '50'),
      maxVUs: Number(__ENV.MAX_VUS || '200'),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    contract_errors: ['rate<0.01'],
    http_req_duration: ['p(95)<300', 'p(99)<800'],
  },
};

const paths = [
  '/shop/map?west=-74.26&south=40.49&east=-73.68&north=40.92&zoom=10',
  '/shop/map?west=-74.05&south=40.68&east=-73.85&north=40.88&zoom=13&typeIds=1,2,3',
  '/shop/map?west=-73.997&south=40.748&east=-73.975&north=40.765&zoom=17&typeIds=1,2',
  '/shop/of/type?typeId=1&current=1&sortBy=rating',
  '/shop/of/type?typeId=2&current=1&sortBy=popularity',
  '/shop/1',
  '/shop-review/1?current=1',
  '/voucher/list/1',
];

export default function () {
  const path = paths[exec.scenario.iterationInTest % paths.length];
  const response = http.get(`${baseUrl}${path}`, { tags: { endpoint: path.split('?')[0] } });
  const valid = check(response, {
    'HTTP 200': (value) => value.status === 200,
    'Result success': (value) => {
      try {
        return value.json('success') !== false;
      } catch (_) {
        return false;
      }
    },
  });
  contractErrors.add(!valid);
}
