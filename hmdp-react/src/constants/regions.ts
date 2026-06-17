// 中国省份/城市级联数据
const regions = [
  {
    label: '北京', value: '北京',
    children: [
      { label: '东城区', value: '东城区' }, { label: '西城区', value: '西城区' },
      { label: '朝阳区', value: '朝阳区' }, { label: '海淀区', value: '海淀区' },
      { label: '丰台区', value: '丰台区' }, { label: '通州区', value: '通州区' },
    ],
  },
  {
    label: '上海', value: '上海',
    children: [
      { label: '黄浦区', value: '黄浦区' }, { label: '徐汇区', value: '徐汇区' },
      { label: '静安区', value: '静安区' }, { label: '浦东新区', value: '浦东新区' },
      { label: '闵行区', value: '闵行区' }, { label: '虹口区', value: '虹口区' },
    ],
  },
  {
    label: '天津', value: '天津',
    children: [
      { label: '和平区', value: '和平区' }, { label: '南开区', value: '南开区' },
      { label: '河西区', value: '河西区' }, { label: '滨海新区', value: '滨海新区' },
    ],
  },
  {
    label: '重庆', value: '重庆',
    children: [
      { label: '渝中区', value: '渝中区' }, { label: '江北区', value: '江北区' },
      { label: '南岸区', value: '南岸区' }, { label: '沙坪坝区', value: '沙坪坝区' },
    ],
  },
  {
    label: '广东', value: '广东',
    children: [
      { label: '广州', value: '广州' }, { label: '深圳', value: '深圳' },
      { label: '珠海', value: '珠海' }, { label: '东莞', value: '东莞' },
      { label: '佛山', value: '佛山' }, { label: '惠州', value: '惠州' },
      { label: '中山', value: '中山' },
    ],
  },
  {
    label: '浙江', value: '浙江',
    children: [
      { label: '杭州', value: '杭州' }, { label: '宁波', value: '宁波' },
      { label: '温州', value: '温州' }, { label: '嘉兴', value: '嘉兴' },
      { label: '湖州', value: '湖州' }, { label: '绍兴', value: '绍兴' },
      { label: '金华', value: '金华' }, { label: '台州', value: '台州' },
    ],
  },
  {
    label: '江苏', value: '江苏',
    children: [
      { label: '南京', value: '南京' }, { label: '苏州', value: '苏州' },
      { label: '无锡', value: '无锡' }, { label: '常州', value: '常州' },
      { label: '南通', value: '南通' }, { label: '扬州', value: '扬州' },
      { label: '徐州', value: '徐州' },
    ],
  },
  {
    label: '山东', value: '山东',
    children: [
      { label: '济南', value: '济南' }, { label: '青岛', value: '青岛' },
      { label: '烟台', value: '烟台' }, { label: '威海', value: '威海' },
      { label: '潍坊', value: '潍坊' }, { label: '淄博', value: '淄博' },
    ],
  },
  {
    label: '四川', value: '四川',
    children: [
      { label: '成都', value: '成都' }, { label: '绵阳', value: '绵阳' },
      { label: '德阳', value: '德阳' }, { label: '宜宾', value: '宜宾' },
      { label: '泸州', value: '泸州' },
    ],
  },
  {
    label: '湖北', value: '湖北',
    children: [
      { label: '武汉', value: '武汉' }, { label: '宜昌', value: '宜昌' },
      { label: '襄阳', value: '襄阳' }, { label: '荆州', value: '荆州' },
      { label: '黄冈', value: '黄冈' },
    ],
  },
  {
    label: '湖南', value: '湖南',
    children: [
      { label: '长沙', value: '长沙' }, { label: '株洲', value: '株洲' },
      { label: '湘潭', value: '湘潭' }, { label: '衡阳', value: '衡阳' },
      { label: '岳阳', value: '岳阳' },
    ],
  },
  {
    label: '河南', value: '河南',
    children: [
      { label: '郑州', value: '郑州' }, { label: '洛阳', value: '洛阳' },
      { label: '开封', value: '开封' }, { label: '南阳', value: '南阳' },
      { label: '许昌', value: '许昌' },
    ],
  },
  {
    label: '河北', value: '河北',
    children: [
      { label: '石家庄', value: '石家庄' }, { label: '唐山', value: '唐山' },
      { label: '保定', value: '保定' }, { label: '邯郸', value: '邯郸' },
    ],
  },
  {
    label: '福建', value: '福建',
    children: [
      { label: '福州', value: '福州' }, { label: '厦门', value: '厦门' },
      { label: '泉州', value: '泉州' }, { label: '漳州', value: '漳州' },
      { label: '莆田', value: '莆田' },
    ],
  },
  {
    label: '安徽', value: '安徽',
    children: [
      { label: '合肥', value: '合肥' }, { label: '芜湖', value: '芜湖' },
      { label: '蚌埠', value: '蚌埠' }, { label: '安庆', value: '安庆' },
    ],
  },
  {
    label: '辽宁', value: '辽宁',
    children: [
      { label: '沈阳', value: '沈阳' }, { label: '大连', value: '大连' },
      { label: '鞍山', value: '鞍山' }, { label: '抚顺', value: '抚顺' },
    ],
  },
  {
    label: '陕西', value: '陕西',
    children: [
      { label: '西安', value: '西安' }, { label: '咸阳', value: '咸阳' },
      { label: '宝鸡', value: '宝鸡' }, { label: '渭南', value: '渭南' },
    ],
  },
  {
    label: '江西', value: '江西',
    children: [
      { label: '南昌', value: '南昌' }, { label: '九江', value: '九江' },
      { label: '赣州', value: '赣州' }, { label: '景德镇', value: '景德镇' },
    ],
  },
  {
    label: '云南', value: '云南',
    children: [
      { label: '昆明', value: '昆明' }, { label: '大理', value: '大理' },
      { label: '丽江', value: '丽江' }, { label: '曲靖', value: '曲靖' },
    ],
  },
  {
    label: '贵州', value: '贵州',
    children: [
      { label: '贵阳', value: '贵阳' }, { label: '遵义', value: '遵义' },
      { label: '安顺', value: '安顺' }, { label: '毕节', value: '毕节' },
    ],
  },
  {
    label: '广西', value: '广西',
    children: [
      { label: '南宁', value: '南宁' }, { label: '桂林', value: '桂林' },
      { label: '柳州', value: '柳州' }, { label: '北海', value: '北海' },
    ],
  },
  {
    label: '山西', value: '山西',
    children: [
      { label: '太原', value: '太原' }, { label: '大同', value: '大同' },
      { label: '长治', value: '长治' }, { label: '晋中', value: '晋中' },
    ],
  },
  {
    label: '吉林', value: '吉林',
    children: [
      { label: '长春', value: '长春' }, { label: '吉林', value: '吉林' },
      { label: '延边', value: '延边' }, { label: '四平', value: '四平' },
    ],
  },
  {
    label: '黑龙江', value: '黑龙江',
    children: [
      { label: '哈尔滨', value: '哈尔滨' }, { label: '齐齐哈尔', value: '齐齐哈尔' },
      { label: '牡丹江', value: '牡丹江' }, { label: '大庆', value: '大庆' },
    ],
  },
  {
    label: '海南', value: '海南',
    children: [
      { label: '海口', value: '海口' }, { label: '三亚', value: '三亚' },
      { label: '儋州', value: '儋州' }, { label: '琼海', value: '琼海' },
    ],
  },
  {
    label: '甘肃', value: '甘肃',
    children: [
      { label: '兰州', value: '兰州' }, { label: '天水', value: '天水' },
      { label: '敦煌', value: '敦煌' },
    ],
  },
  {
    label: '内蒙古', value: '内蒙古',
    children: [
      { label: '呼和浩特', value: '呼和浩特' }, { label: '包头', value: '包头' },
      { label: '鄂尔多斯', value: '鄂尔多斯' },
    ],
  },
  {
    label: '新疆', value: '新疆',
    children: [
      { label: '乌鲁木齐', value: '乌鲁木齐' }, { label: '克拉玛依', value: '克拉玛依' },
      { label: '吐鲁番', value: '吐鲁番' }, { label: '喀什', value: '喀什' },
    ],
  },
  {
    label: '西藏', value: '西藏',
    children: [
      { label: '拉萨', value: '拉萨' }, { label: '日喀则', value: '日喀则' },
      { label: '林芝', value: '林芝' },
    ],
  },
  {
    label: '青海', value: '青海',
    children: [
      { label: '西宁', value: '西宁' }, { label: '海东', value: '海东' },
    ],
  },
  {
    label: '宁夏', value: '宁夏',
    children: [
      { label: '银川', value: '银川' }, { label: '石嘴山', value: '石嘴山' },
      { label: '吴忠', value: '吴忠' },
    ],
  },
];

export default regions;
