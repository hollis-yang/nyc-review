import client from './client';

export function getVoucherList(shopId: number | string) {
  return client.get(`/voucher/list/${shopId}`);
}

export function seckillVoucher(voucherId: number | string) {
  return client.post(`/voucher-order/seckill/${voucherId}`);
}
