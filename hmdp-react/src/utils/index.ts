export function getUrlParam(name: string): string {
  const search = window.location.search.substring(1);
  const reg = new RegExp('(^|&)' + name + '=([^&]*)(&|$)', 'i');
  const r = search.match(reg);
  if (r != null) {
    return decodeURIComponent(r[2]);
  }
  return '';
}

export function formatPrice(val: string | number): number | null {
  if (typeof val === 'string') {
    if (isNaN(Number(val))) return null;
    const index = val.lastIndexOf('.');
    let p = '';
    if (index < 0) {
      p = val + '00';
    } else if (index === val.length - 2) {
      p = val.replace('.', '') + '0';
    } else {
      p = val.replace('.', '');
    }
    return parseInt(p);
  } else if (typeof val === 'number') {
    if (!val) return null;
    const s = val + '';
    if (s.length === 0) return 0;
    if (s.length === 1) return parseFloat('0.0' + val);
    if (s.length === 2) return parseFloat('0.' + val);
    const i = s.indexOf('.');
    if (i < 0) {
      return parseFloat(s.substring(0, s.length - 2) + '.' + s.substring(s.length - 2));
    }
    const num = s.substring(0, i) + s.substring(i + 1);
    if (i === 1) return parseFloat('0.0' + num);
    if (i === 2) return parseFloat('0.' + num);
    if (i > 2) return parseFloat(num.substring(0, i - 2) + '.' + num.substring(i - 2));
  }
  return null;
}
