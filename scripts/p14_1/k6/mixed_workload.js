import http from 'k6/http';
import exec from 'k6/execution';
import {
  baseUrl,
  classifyBusinessResponse,
  recordApiResponse,
  tokenFor,
  voucherId,
} from './common.js';

const rate = Number(__ENV.RATE || '50');

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    mixed: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration: __ENV.DURATION || '10m',
      preAllocatedVUs: Number(__ENV.PRE_ALLOCATED_VUS || '75'),
      maxVUs: Number(__ENV.MAX_VUS || '300'),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    technical_errors: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1200'],
  },
};

const readPaths = [
  '/shop/map?west=-74.26&south=40.49&east=-73.68&north=40.92&zoom=10',
  '/shop/map?west=-74.05&south=40.68&east=-73.85&north=40.88&zoom=13&typeIds=1,2,3',
  '/shop/of/type?typeId=1&current=1&sortBy=rating',
  '/shop/of/type?typeId=2&current=1&sortBy=popularity',
  '/shop/1',
  '/shop-review/1?current=1',
  '/voucher/list/1',
];

export default function () {
  const iteration = exec.scenario.iterationInTest;
  const slot = iteration % 20;
  if (slot === 0 || slot === 10) {
    const response = http.post(`${baseUrl}/voucher-order/seckill/${voucherId}`, null, {
      headers: { authorization: tokenFor(Math.floor(iteration / 10)) },
      tags: { endpoint: 'mixed_seckill' },
    });
    classifyBusinessResponse(response);
    return;
  }
  if (slot === 1) {
    const response = http.get(`${baseUrl}/profile/assets`, {
      headers: { authorization: tokenFor(Math.floor(iteration / 20)) },
      tags: { endpoint: '/profile/assets' },
    });
    recordApiResponse(response, 'profile assets valid');
    return;
  }
  if (slot === 2) {
    const response = http.post(
      `${baseUrl}/internal/agent/tools/shops/search`,
      JSON.stringify({
        query: null,
        typeId: 1,
        neighborhood: 'Midtown',
        requiredTags: ['quiet'],
        limit: 5,
      }),
      {
        headers: {
          authorization: tokenFor(Math.floor(iteration / 20)),
          'Content-Type': 'application/json',
        },
        tags: { endpoint: '/internal/agent/tools/shops/search' },
      },
    );
    recordApiResponse(response, 'agent shop tool valid');
    return;
  }
  const path = readPaths[iteration % readPaths.length];
  const response = http.get(`${baseUrl}${path}`, { tags: { endpoint: path.split('?')[0] } });
  recordApiResponse(response, 'read response valid');
}
