SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `tb_shop_type`;
CREATE TABLE `tb_shop_type` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `name` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '类型名称',
  `icon` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '图标',
  `sort` int(3) UNSIGNED NULL DEFAULT NULL COMMENT '顺序',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_shop_type VALUES (1,'美食','/types/ms.png',1,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (2,'KTV','/types/KTV.png',2,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (3,'丽人·美发','/types/lrmf.png',3,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (4,'健身运动','/types/jsyd.png',10,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (5,'按摩·足疗','/types/amzl.png',5,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (6,'美容SPA','/types/spa.png',6,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (7,'亲子游乐','/types/qzyl.png',7,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (8,'酒吧','/types/jiuba.png',8,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (9,'轰趴馆','/types/hpg.png',9,'2021-12-22 20:17:47','2021-12-23 11:24:31');
INSERT INTO tb_shop_type VALUES (10,'美睫·美甲','/types/mjmj.png',4,'2021-12-22 20:17:47','2021-12-23 11:24:31');

DROP TABLE IF EXISTS `tb_shop`;
CREATE TABLE `tb_shop` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '商铺名称',
  `type_id` bigint(20) UNSIGNED NOT NULL COMMENT '商铺类型的id',
  `images` varchar(1024) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '商铺图片',
  `area` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '商圈',
  `address` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '地址',
  `x` double UNSIGNED NOT NULL COMMENT '经度',
  `y` double UNSIGNED NOT NULL COMMENT '维度',
  `avg_price` bigint(10) UNSIGNED NULL DEFAULT NULL COMMENT '均价',
  `sold` int(10) UNSIGNED ZEROFILL NOT NULL COMMENT '销量',
  `comments` int(10) UNSIGNED ZEROFILL NOT NULL COMMENT '评论数量',
  `score` int(2) UNSIGNED ZEROFILL NOT NULL COMMENT '评分',
  `open_hours` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '营业时间',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `foreign_key_type`(`type_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 59 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_shop VALUES (1,'103茶餐厅',1,'https://qcloud.dpfile.com/pc/jiclIsCKmOI2arxKN1Uf0Hx3PucIJH8q0QSz-Z8llzcN56-_QiKuOvyio1OOxsRtFoXqu0G3iT2T27qat3WhLVEuLYk00OmSS1IdNpm8K8sG4JN9RIm2mTKcbLtc2o2vfCF2ubeXzk49OsGrXt_KYDCngOyCwZK-s3fqawWswzk.jpg,https://qcloud.dpfile.com/pc/IOf6VX3qaBgFXFVgp75w-KKJmWZjFc8GXDU8g9bQC6YGCpAmG00QbfT4vCCBj7njuzFvxlbkWx5uwqY2qcjixFEuLYk00OmSS1IdNpm8K8sG4JN9RIm2mTKcbLtc2o2vmIU_8ZGOT1OjpJmLxG6urQ.jpg','大关','金华路锦昌文华苑29号',120.149192,30.316078,80,0000004215,0000003035,37,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (2,'蔡馬洪涛烤肉·老北京铜锅涮羊肉',1,'https://p0.meituan.net/bbia/c1870d570e73accbc9fee90b48faca41195272.jpg,http://p0.meituan.net/mogu/397e40c28fc87715b3d5435710a9f88d706914.jpg,https://qcloud.dpfile.com/pc/MZTdRDqCZdbPDUO0Hk6lZENRKzpKRF7kavrkEI99OxqBZTzPfIxa5E33gBfGouhFuzFvxlbkWx5uwqY2qcjixFEuLYk00OmSS1IdNpm8K8sG4JN9RIm2mTKcbLtc2o2vmIU_8ZGOT1OjpJmLxG6urQ.jpg','拱宸桥/上塘','上塘路1035号（中国工商银行旁）',120.151505,30.333422,85,0000002160,0000001460,46,'11:30-03:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (3,'新白鹿餐厅(运河上街店)',1,'https://p0.meituan.net/biztone/694233_1619500156517.jpeg,https://img.meituan.net/msmerchant/876ca8983f7395556eda9ceb064e6bc51840883.png,https://img.meituan.net/msmerchant/86a76ed53c28eff709a36099aefe28b51554088.png','运河上街','台州路2号运河上街购物中心F5',120.151954,30.32497,61,0000012035,0000008045,47,'10:30-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (4,'Mamala(杭州远洋乐堤港店)',1,'https://img.meituan.net/msmerchant/232f8fdf09050838bd33fb24e79f30f9606056.jpg,https://qcloud.dpfile.com/pc/rDe48Xe15nQOHCcEEkmKUp5wEKWbimt-HDeqYRWsYJseXNncvMiXbuED7x1tXqN4uzFvxlbkWx5uwqY2qcjixFEuLYk00OmSS1IdNpm8K8sG4JN9RIm2mTKcbLtc2o2vmIU_8ZGOT1OjpJmLxG6urQ.jpg','拱宸桥/上塘','丽水路66号远洋乐堤港商城2期1层B115号',120.146659,30.312742,290,0000013519,0000009529,49,'11:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (5,'海底捞火锅(水晶城购物中心店)',1,'https://img.meituan.net/msmerchant/054b5de0ba0b50c18a620cc37482129a45739.jpg,https://img.meituan.net/msmerchant/59b7eff9b60908d52bd4aea9ff356e6d145920.jpg,https://qcloud.dpfile.com/pc/Qe2PTEuvtJ5skpUXKKoW9OQ20qc7nIpHYEqJGBStJx0mpoyeBPQOJE4vOdYZwm9AuzFvxlbkWx5uwqY2qcjixFEuLYk00OmSS1IdNpm8K8sG4JN9RIm2mTKcbLtc2o2vmIU_8ZGOT1OjpJmLxG6urQ.jpg','大关','上塘路458号水晶城购物中心F6',120.15778,30.310633,104,0000004125,0000002764,49,'10:00-07:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (6,'老头儿油爆虾(湖滨店)',1,'https://picsum.photos/seed/shop6a/400/300,https://picsum.photos/seed/shop6b/400/300,https://picsum.photos/seed/shop6c/400/300','湖滨/武林','延安路255号',120.165,30.257,75,0000008921,0000006230,48,'11:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (7,'外婆家(西湖天地店)',1,'https://picsum.photos/seed/shop7a/400/300,https://picsum.photos/seed/shop7b/400/300,https://picsum.photos/seed/shop7c/400/300','西湖','南山路147号西湖天地F2',120.146,30.241,65,0000015620,0000009870,46,'10:30-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (8,'绿茶餐厅(龙井路店)',1,'https://picsum.photos/seed/shop8a/400/300,https://picsum.photos/seed/shop8b/400/300,https://picsum.photos/seed/shop8c/400/300','西湖','龙井路89号',120.132,30.238,72,0000011200,0000007850,47,'11:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (9,'知味观(湖滨总店)',1,'https://picsum.photos/seed/shop9a/400/300,https://picsum.photos/seed/shop9b/400/300,https://picsum.photos/seed/shop9c/400/300','湖滨/武林','仁和路83号',120.168,30.254,45,0000025000,0000015200,45,'06:30-20:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (10,'楼外楼(孤山路店)',1,'https://picsum.photos/seed/shop10a/400/300,https://picsum.photos/seed/shop10b/400/300,https://picsum.photos/seed/shop10c/400/300','西湖','孤山路30号',120.142,30.248,150,0000018300,0000011200,44,'10:00-20:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (11,'卤儿道道(钱江新城店)',1,'https://picsum.photos/seed/shop11a/400/300,https://picsum.photos/seed/shop11b/400/300,https://picsum.photos/seed/shop11c/400/300','钱江新城','富春路701号万象城B1',120.212,30.243,55,0000006780,0000004210,44,'10:00-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (12,'蟹觅·蟹黄面(滨江店)',1,'https://picsum.photos/seed/shop12a/400/300,https://picsum.photos/seed/shop12b/400/300,https://picsum.photos/seed/shop12c/400/300','滨江','江南大道228号星光大道F3',120.201,30.196,88,0000003450,0000002100,46,'11:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (13,'开乐迪KTV(运河上街店)',2,'https://p0.meituan.net/joymerchant/a575fd4adb0b9099c5c410058148b307-674435191.jpg,https://p0.meituan.net/merchantpic/68f11bf850e25e437c5f67decfd694ab2541634.jpg,https://p0.meituan.net/dpdeal/cb3a12225860ba2875e4ea26c6d14fcc197016.jpg','运河上街','台州路2号运河上街购物中心F4',120.149093,30.324666,67,0000026891,0000000902,37,'00:00-24:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (14,'INLOVE KTV(水晶城店)',2,'https://p0.meituan.net/dpmerchantpic/53e74b200211d68988a4f02ae9912c6c1076826.jpg,https://qcloud.dpfile.com/pc/4iWtIvzLzwM2MGgyPu1PCDb4SWEaKqUeHm--YAt1EwR5tn8kypBcqNwHnjg96EvT_Gd2X_f-v9T8Yj4uLt25Gg.jpg,https://qcloud.dpfile.com/pc/WZsJWRI447x1VG2x48Ujgu7vwqksi_9WitdKI4j3jvIgX4MZOpGNaFtM93oSSizbGybIjx5eX6WNgCPvcASYAw.jpg','水晶城','上塘路458号水晶城购物中心6层',120.15853,30.310002,75,0000035977,0000005684,47,'11:30-06:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (15,'星聚会KTV(拱墅万达店)',2,'https://p0.meituan.net/dpmerchantpic/f4cd6d8d4eb1959c3ea826aa05a552c01840451.jpg,https://p0.meituan.net/dpmerchantpic/2efc07aed856a8ab0fc75c86f4b9b0061655777.jpg,https://qcloud.dpfile.com/pc/zWfzzIorCohKT0bFwsfAlHuayWjI6DBEMPHHncmz36EEMU9f48PuD9VxLLDAjdoU_Gd2X_f-v9T8Yj4uLt25Gg.jpg','北部新城','杭行路666号万达广场C座1-2F',120.128958,30.337252,60,0000017771,0000000685,47,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (16,'纯K(湖滨银泰店)',2,'https://picsum.photos/seed/shop16a/400/300,https://picsum.photos/seed/shop16b/400/300,https://picsum.photos/seed/shop16c/400/300','湖滨/武林','延安路258号湖滨银泰in77 C区F5',120.164,30.256,88,0000021200,0000004300,46,'12:00-06:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (17,'好乐迪KTV(武林店)',2,'https://picsum.photos/seed/shop17a/400/300,https://picsum.photos/seed/shop17b/400/300,https://picsum.photos/seed/shop17c/400/300','湖滨/武林','武林路163号',120.16,30.264,55,0000015800,0000003100,42,'11:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (18,'唱吧麦颂(滨江宝龙店)',2,'https://picsum.photos/seed/shop18a/400/300,https://picsum.photos/seed/shop18b/400/300,https://picsum.photos/seed/shop18c/400/300','滨江','滨盛路3867号宝龙城F4',120.195,30.191,49,0000012300,0000002400,43,'12:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (19,'侨治发型(武林店)',3,'https://picsum.photos/seed/shop19a/400/300,https://picsum.photos/seed/shop19b/400/300,https://picsum.photos/seed/shop19c/400/300','湖滨/武林','武林路217号',120.161,30.266,128,0000004200,0000001980,45,'10:00-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (20,'TONI&GUY(湖滨银泰店)',3,'https://picsum.photos/seed/shop20a/400/300,https://picsum.photos/seed/shop20b/400/300,https://picsum.photos/seed/shop20c/400/300','湖滨/武林','延安路258号湖滨银泰in77 B区F2',120.164,30.255,280,0000003100,0000001500,48,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (21,'杜尚发艺(城西银泰店)',3,'https://picsum.photos/seed/shop21a/400/300,https://picsum.photos/seed/shop21b/400/300,https://picsum.photos/seed/shop21c/400/300','城西','萍水街335号城西银泰F3',120.091,30.281,158,0000003800,0000001700,46,'09:30-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (22,'尚艺美容美发(滨江店)',3,'https://picsum.photos/seed/shop22a/400/300,https://picsum.photos/seed/shop22b/400/300,https://picsum.photos/seed/shop22c/400/300','滨江','江陵路2028号星耀城F2',120.205,30.197,68,0000005600,0000002300,42,'09:00-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (23,'东瀛美发(钱江新城店)',3,'https://picsum.photos/seed/shop23a/400/300,https://picsum.photos/seed/shop23b/400/300,https://picsum.photos/seed/shop23c/400/300','钱江新城','新业路228号来福士广场F3',120.212,30.241,198,0000002900,0000001200,47,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (24,'乐刻健身(武林店)',4,'https://picsum.photos/seed/shop24a/400/300,https://picsum.photos/seed/shop24b/400/300,https://picsum.photos/seed/shop24c/400/300','湖滨/武林','武林路189号',120.161,30.265,99,0000008900,0000004500,44,'06:00-23:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (25,'超级猩猩(湖滨店)',4,'https://picsum.photos/seed/shop25a/400/300,https://picsum.photos/seed/shop25b/400/300,https://picsum.photos/seed/shop25c/400/300','湖滨/武林','延安路239号',120.166,30.253,129,0000006700,0000003200,47,'07:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (26,'威尔仕健身(钱江新城店)',4,'https://picsum.photos/seed/shop26a/400/300,https://picsum.photos/seed/shop26b/400/300,https://picsum.photos/seed/shop26c/400/300','钱江新城','富春路701号万象城F5',120.212,30.243,199,0000005200,0000002600,46,'06:30-22:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (27,'舒适堡(城西银泰店)',4,'https://picsum.photos/seed/shop27a/400/300,https://picsum.photos/seed/shop27b/400/300,https://picsum.photos/seed/shop27c/400/300','城西','萍水街333号城西银泰F4',120.09,30.281,159,0000004500,0000002100,43,'07:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (28,'一兆韦德(滨江店)',4,'https://picsum.photos/seed/shop28a/400/300,https://picsum.photos/seed/shop28b/400/300,https://picsum.photos/seed/shop28c/400/300','滨江','江南大道288号',120.203,30.198,169,0000003900,0000001800,45,'07:00-23:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (29,'华夏良子(武林店)',5,'https://picsum.photos/seed/shop29a/400/300,https://picsum.photos/seed/shop29b/400/300,https://picsum.photos/seed/shop29c/400/300','湖滨/武林','武林路312号',120.162,30.268,198,0000005600,0000002800,45,'11:00-01:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (30,'康骏养生(城西店)',5,'https://picsum.photos/seed/shop30a/400/300,https://picsum.photos/seed/shop30b/400/300,https://picsum.photos/seed/shop30c/400/300','城西','文一路102号',120.095,30.275,168,0000004300,0000001900,44,'10:00-00:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (31,'颐尊会(钱江新城店)',5,'https://picsum.photos/seed/shop31a/400/300,https://picsum.photos/seed/shop31b/400/300,https://picsum.photos/seed/shop31c/400/300','钱江新城','新业路228号来福士广场F4',120.212,30.241,258,0000003200,0000001500,48,'11:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (32,'足生堂(拱宸桥店)',5,'https://picsum.photos/seed/shop32a/400/300,https://picsum.photos/seed/shop32b/400/300,https://picsum.photos/seed/shop32c/400/300','拱宸桥/上塘','上塘路1068号',120.152,30.327,128,0000005100,0000002400,43,'10:00-01:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (33,'良子健身(滨江店)',5,'https://picsum.photos/seed/shop33a/400/300,https://picsum.photos/seed/shop33b/400/300,https://picsum.photos/seed/shop33c/400/300','滨江','江陵路2056号',120.204,30.195,158,0000003800,0000001600,44,'11:00-00:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (34,'美丽田园(湖滨银泰店)',6,'https://picsum.photos/seed/shop34a/400/300,https://picsum.photos/seed/shop34b/400/300,https://picsum.photos/seed/shop34c/400/300','湖滨/武林','延安路258号湖滨银泰in77 D区F3',120.165,30.254,398,0000004800,0000002200,47,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (35,'思妍丽(钱江新城店)',6,'https://picsum.photos/seed/shop35a/400/300,https://picsum.photos/seed/shop35b/400/300,https://picsum.photos/seed/shop35c/400/300','钱江新城','富春路701号万象城F3',120.213,30.243,498,0000003500,0000001600,48,'10:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (36,'克丽缇娜(城西银泰店)',6,'https://picsum.photos/seed/shop36a/400/300,https://picsum.photos/seed/shop36b/400/300,https://picsum.photos/seed/shop36c/400/300','城西','萍水街335号城西银泰F2',120.09,30.28,298,0000004100,0000001800,45,'09:30-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (37,'伊美娜(滨江宝龙店)',6,'https://picsum.photos/seed/shop37a/400/300,https://picsum.photos/seed/shop37b/400/300,https://picsum.photos/seed/shop37c/400/300','滨江','滨盛路3867号宝龙城F2',120.196,30.19,268,0000003200,0000001300,44,'10:00-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (38,'诗泥SPA(西溪银泰店)',6,'https://picsum.photos/seed/shop38a/400/300,https://picsum.photos/seed/shop38b/400/300,https://picsum.photos/seed/shop38c/400/300','西溪','余杭塘路999号西溪银泰F3',120.072,30.275,358,0000002800,0000001100,46,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (39,'奈尔宝家庭中心(钱江新城店)',7,'https://picsum.photos/seed/shop39a/400/300,https://picsum.photos/seed/shop39b/400/300,https://picsum.photos/seed/shop39c/400/300','钱江新城','新业路228号来福士广场F3',120.212,30.241,298,0000008900,0000004500,48,'10:00-21:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (40,'meland儿童成长乐园(滨江店)',7,'https://picsum.photos/seed/shop40a/400/300,https://picsum.photos/seed/shop40b/400/300,https://picsum.photos/seed/shop40c/400/300','滨江','江南大道228号星光大道F2',120.201,30.196,198,0000007600,0000003800,47,'10:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (41,'乐高探索中心(城西店)',7,'https://picsum.photos/seed/shop41a/400/300,https://picsum.photos/seed/shop41b/400/300,https://picsum.photos/seed/shop41c/400/300','城西','文一路205号',120.098,30.278,180,0000006200,0000003100,46,'10:00-20:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (42,'汤姆熊欢乐世界(湖滨店)',7,'https://picsum.photos/seed/shop42a/400/300,https://picsum.photos/seed/shop42b/400/300,https://picsum.photos/seed/shop42c/400/300','湖滨/武林','延安路258号湖滨银泰in77 C区B1',120.164,30.256,120,0000009500,0000005200,44,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (43,'卡通尼乐园(萧山万象汇店)',7,'https://picsum.photos/seed/shop43a/400/300,https://picsum.photos/seed/shop43b/400/300,https://picsum.photos/seed/shop43c/400/300','萧山','金城路688号万象汇F3',120.264,30.172,138,0000005400,0000002600,45,'10:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (44,'MILL酒吧(湖滨店)',8,'https://picsum.photos/seed/shop44a/400/300,https://picsum.photos/seed/shop44b/400/300,https://picsum.photos/seed/shop44c/400/300','湖滨/武林','延安路223号',120.162,30.252,150,0000008700,0000004300,46,'18:00-03:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (45,'贰麻酒馆(武林店)',8,'https://picsum.photos/seed/shop45a/400/300,https://picsum.photos/seed/shop45b/400/300,https://picsum.photos/seed/shop45c/400/300','湖滨/武林','武林路256号',120.16,30.267,120,0000010200,0000005600,45,'17:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (46,'HELENS海伦司(下沙店)',8,'https://picsum.photos/seed/shop46a/400/300,https://picsum.photos/seed/shop46b/400/300,https://picsum.photos/seed/shop46c/400/300','钱江新城','学源街123号',120.215,30.245,60,0000015800,0000007800,43,'18:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (47,'酒隐(城西店)',8,'https://picsum.photos/seed/shop47a/400/300,https://picsum.photos/seed/shop47b/400/300,https://picsum.photos/seed/shop47c/400/300','城西','文一路335号',120.092,30.28,98,0000006500,0000003100,44,'18:00-01:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (48,'麦浪酒吧(滨江店)',8,'https://picsum.photos/seed/shop48a/400/300,https://picsum.photos/seed/shop48b/400/300,https://picsum.photos/seed/shop48c/400/300','滨江','滨盛路3890号',120.193,30.19,110,0000007300,0000003500,44,'18:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (49,'威廉古堡(西溪店)',9,'https://picsum.photos/seed/shop49a/400/300,https://picsum.photos/seed/shop49b/400/300,https://picsum.photos/seed/shop49c/400/300','西溪','五常大道158号',120.058,30.268,168,0000003800,0000001700,44,'10:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (50,'趣玩轰趴(滨江店)',9,'https://picsum.photos/seed/shop50a/400/300,https://picsum.photos/seed/shop50b/400/300,https://picsum.photos/seed/shop50c/400/300','滨江','江南大道358号',120.208,30.201,148,0000004200,0000001900,43,'10:00-00:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (51,'头号玩家轰趴馆(城西店)',9,'https://picsum.photos/seed/shop51a/400/300,https://picsum.photos/seed/shop51b/400/300,https://picsum.photos/seed/shop51c/400/300','城西','古墩路589号',120.1,30.283,158,0000003500,0000001500,45,'12:00-02:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (52,'派对联盟(下沙店)',9,'https://picsum.photos/seed/shop52a/400/300,https://picsum.photos/seed/shop52b/400/300,https://picsum.photos/seed/shop52c/400/300','钱江新城','学林街88号',120.218,30.246,128,0000004800,0000002200,42,'10:00-23:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (53,'大富翁轰趴(萧山店)',9,'https://picsum.photos/seed/shop53a/400/300,https://picsum.photos/seed/shop53b/400/300,https://picsum.photos/seed/shop53c/400/300','萧山','金城路915号',120.268,30.175,138,0000003100,0000001300,43,'12:00-01:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (54,'悦诗风吟美甲(湖滨店)',10,'https://picsum.photos/seed/shop54a/400/300,https://picsum.photos/seed/shop54b/400/300,https://picsum.photos/seed/shop54c/400/300','湖滨/武林','延安路258号湖滨银泰in77 B区B1',120.164,30.255,168,0000005600,0000002800,46,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (55,'指间印象(武林店)',10,'https://picsum.photos/seed/shop55a/400/300,https://picsum.photos/seed/shop55b/400/300,https://picsum.photos/seed/shop55c/400/300','湖滨/武林','武林路187号',120.161,30.264,128,0000004800,0000002100,44,'09:30-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (56,'U3美甲(滨江宝龙店)',10,'https://picsum.photos/seed/shop56a/400/300,https://picsum.photos/seed/shop56b/400/300,https://picsum.photos/seed/shop56c/400/300','滨江','滨盛路3867号宝龙城B1',120.196,30.19,158,0000004200,0000001900,45,'10:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (57,'瑞诗美甲(城西银泰店)',10,'https://picsum.photos/seed/shop57a/400/300,https://picsum.photos/seed/shop57b/400/300,https://picsum.photos/seed/shop57c/400/300','城西','萍水街335号城西银泰B1',120.09,30.281,198,0000003600,0000001600,47,'10:00-22:00','2026-05-01 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_shop VALUES (58,'艺美甲(西溪店)',10,'https://picsum.photos/seed/shop58a/400/300,https://picsum.photos/seed/shop58b/400/300,https://picsum.photos/seed/shop58c/400/300','西溪','余杭塘路999号西溪银泰B1',120.072,30.275,138,0000003900,0000001700,44,'10:00-21:30','2026-05-01 10:00:00','2026-05-10 08:00:00');

DROP TABLE IF EXISTS `tb_user`;
CREATE TABLE `tb_user` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `phone` varchar(11) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '手机号码',
  `password` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT '' COMMENT '密码',
  `nick_name` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT '' COMMENT '昵称',
  `icon` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT '' COMMENT '人物头像',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uniqe_key_phone`(`phone`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 13 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_user VALUES (1,'13686869696','','小鱼同学','/imgs/blogs/blog1.jpg','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (2,'13838411438','','可可今天不吃肉','/imgs/icons/kkjtbcr.jpg','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (3,'13688668889','','杭城小王子','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (4,'13688668890','','西湖边的猫','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (5,'13456789001','','可爱多','/imgs/icons/user5-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (6,'13456789011','','钱塘江边的人','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (7,'13456762069','','杭州小辣椒','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (8,'13688668891','','武林广场舞王','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (9,'13688668892','','龙井茶不茶','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (10,'13688668893','','滨江小霸王','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (11,'13688668894','','城西一枝花','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user VALUES (12,'13688668895','','萧山大哥大','/imgs/icons/default-icon.png','2026-03-15 10:00:00','2026-05-10 08:00:00');

DROP TABLE IF EXISTS `tb_user_info`;
CREATE TABLE `tb_user_info` (
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '主键，用户id',
  `city` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT '' COMMENT '城市名称',
  `introduce` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '个人介绍',
  `fans` int(8) UNSIGNED NULL DEFAULT 0 COMMENT '粉丝数量',
  `followee` int(8) UNSIGNED NULL DEFAULT 0 COMMENT '关注的人的数量',
  `gender` tinyint(1) UNSIGNED NULL DEFAULT 0 COMMENT '性别',
  `birthday` date NULL DEFAULT NULL COMMENT '生日',
  `credits` int(8) UNSIGNED NULL DEFAULT 0 COMMENT '积分',
  `level` tinyint(1) UNSIGNED NULL DEFAULT 0 COMMENT '会员级别',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`user_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_user_info VALUES (1,'杭州','爱探店的美食博主🍜 杭州土著，带你发现城市里的宝藏小店',4280,156,1,'1998-06-15',2560,3,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (2,'杭州','健身狂热爱好者💪 分享杭州最棒的健身和轻食好去处',3150,203,1,'1996-03-22',1980,2,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (3,'杭州','热爱生活的杭州男孩，喜欢探索城市每一个角落',1820,312,0,'1999-11-08',890,1,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (4,'杭州','摄影爱好者📷 记录杭州的美好瞬间',2350,178,1,'1997-07-30',1560,2,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (5,'杭州','宝妈一枚~分享杭州最好玩的亲子游乐和育儿心得👶',5600,95,1,'1993-12-03',3420,3,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (6,'杭州','KTV麦霸🎤 全杭州的KTV没有我没去过的',980,456,0,'2000-02-18',420,1,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (7,'杭州','美容SPA达人💆‍♀️ 试遍杭州大大小小的美容院',3100,134,1,'1995-09-25',2100,2,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (8,'杭州','吃喝玩乐样样通，杭州夜生活指南🌃',1450,267,0,'1997-04-12',760,1,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (9,'杭州','茶系青年🍵 喜欢安静的酒吧和文艺小店',2100,189,0,'1998-08-07',1250,2,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (10,'杭州','轰趴小王子🎉 组织过各种主题派对，轰趴找我准没错',1780,223,0,'2000-01-14',980,1,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (11,'杭州','美甲控💅 一个月不换美甲就浑身难受',2650,145,1,'1999-05-20',1890,2,'2026-03-15 10:00:00','2026-05-10 08:00:00');
INSERT INTO tb_user_info VALUES (12,'杭州','资深吃货😋 萧山片区的美食活地图',1980,198,0,'1994-10-01',1100,1,'2026-03-15 10:00:00','2026-05-10 08:00:00');

DROP TABLE IF EXISTS `tb_blog`;
CREATE TABLE `tb_blog` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `shop_id` bigint(20) NOT NULL COMMENT '商户id',
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '用户id',
  `title` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '标题',
  `images` varchar(2048) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '探店的照片',
  `content` varchar(2048) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '探店的文字描述',
  `liked` int(8) UNSIGNED NULL DEFAULT 0 COMMENT '点赞数量',
  `comments` int(8) UNSIGNED NOT NULL DEFAULT 0 COMMENT '评论数量',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 50 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_blog VALUES (1,1,3,'103茶餐厅｜杭州人必打卡的宝藏店铺💎亲测不踩雷','https://picsum.photos/seed/blog1a/400/300,https://picsum.photos/seed/blog1b/400/300','作为一个在杭州生活了20多年的土著，这家店我真的要吹爆💥

103茶餐厅位于大关，位置很好找，交通也方便🚇

来了不下5次了，每次都有新惊喜：

✨亮点一：品质稳定，每次来都是一个水准
✨亮点二：性价比高，人均80的消费完全对得起体验
✨亮点三：服务到位，不会过度热情也不会冷漠

最近他们家还出了新项目/新菜，试了一下果然没让我失望！

老规矩，结尾放攻略👇
⏰建议错开周末高峰期
📍地址：大关
💰人均：80元

#杭州打卡 #杭州周末去哪 #探店分享',43,20,'2026-04-11 01:00:00','2026-04-11 01:00:00');
INSERT INTO tb_blog VALUES (2,2,3,'谁懂啊！！拱宸桥/上塘这家蔡馬洪涛烤肉·老北京铜锅涮羊肉真的太绝了🥹💕','https://picsum.photos/seed/blog2a/400/300,https://picsum.photos/seed/blog2b/400/300','啊啊啊啊我真的会谢🫠

之前就听说拱宸桥/上塘有家很不错的美食，今天终于来打卡了！

🏪店名：蔡馬洪涛烤肉·老北京铜锅涮羊肉
📍地址：拱宸桥/上塘

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才85，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',188,45,'2026-04-13 23:00:00','2026-04-13 23:00:00');
INSERT INTO tb_blog VALUES (3,3,9,'杭州探店｜藏在运河上街的宝藏美食🔥绝绝子','https://picsum.photos/seed/blog3a/400/300,https://picsum.photos/seed/blog3b/400/300','挖到宝了家人们！！

在运河上街逛的时候发现了一家超级低调的宝藏店铺🏪

新白鹿餐厅(运河上街店)

一进门就被装修风格吸引了，太有感觉了！细节满满，每个角落都很用心✨

说说体验感受：

1️⃣ 环境氛围感拉满，灯光音乐都恰到好处
2️⃣ 服务态度超级好，很贴心
3️⃣ 性价比绝了，才花了不到61块

唯一的缺点就是：为什么我现在才发现啊！！

已经安利给身边所有朋友了，个个都说好👍

杭州的宝子们快冲！绝对不会后悔！

#杭州探店 #杭州生活 #美食推荐',52,8,'2026-05-02 21:00:00','2026-05-02 21:00:00');
INSERT INTO tb_blog VALUES (4,4,10,'谁懂啊！！拱宸桥/上塘这家Mamala(杭州远洋乐堤港店)真的太绝了🥹💕','https://picsum.photos/seed/blog4a/400/300,https://picsum.photos/seed/blog4b/400/300','啊啊啊啊我真的会谢🫠

之前就听说拱宸桥/上塘有家很不错的美食，今天终于来打卡了！

🏪店名：Mamala(杭州远洋乐堤港店)
📍地址：拱宸桥/上塘

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才290，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',29,16,'2026-05-10 12:00:00','2026-05-10 12:00:00');
INSERT INTO tb_blog VALUES (5,5,8,'谁懂啊！！大关这家海底捞火锅(水晶城购物中心店)真的太绝了🥹💕','https://picsum.photos/seed/blog5a/400/300,https://picsum.photos/seed/blog5b/400/300','啊啊啊啊我真的会谢🫠

之前就听说大关有家很不错的美食，今天终于来打卡了！

🏪店名：海底捞火锅(水晶城购物中心店)
📍地址：大关

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才104，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',81,30,'2026-04-02 02:00:00','2026-04-02 02:00:00');
INSERT INTO tb_blog VALUES (6,6,1,'被这家店的性价比震惊到了🤯人均75吃到撑','https://picsum.photos/seed/blog6a/400/300,https://picsum.photos/seed/blog6b/400/300','今天和姐妹在湖滨/武林逛街，无意间发现了这家老头儿油爆虾(湖滨店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才75块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：湖滨/武林
🕐营业时间：11:00-21:30
💰人均：75元
⭐推荐指数：🌟🌟🌟🌟🌟',167,31,'2026-04-28 18:00:00','2026-04-28 18:00:00');
INSERT INTO tb_blog VALUES (7,7,5,'被这家店的性价比震惊到了🤯人均65吃到撑','https://picsum.photos/seed/blog7a/400/300,https://picsum.photos/seed/blog7b/400/300','今天和姐妹在西湖逛街，无意间发现了这家外婆家(西湖天地店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才65块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：西湖
🕐营业时间：10:30-21:00
💰人均：65元
⭐推荐指数：🌟🌟🌟🌟🌟',108,20,'2026-03-31 21:00:00','2026-03-31 21:00:00');
INSERT INTO tb_blog VALUES (8,8,5,'被这家店的性价比震惊到了🤯人均72吃到撑','https://picsum.photos/seed/blog8a/400/300,https://picsum.photos/seed/blog8b/400/300','今天和姐妹在西湖逛街，无意间发现了这家绿茶餐厅(龙井路店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才72块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：西湖
🕐营业时间：11:00-21:30
💰人均：72元
⭐推荐指数：🌟🌟🌟🌟🌟',225,11,'2026-04-20 04:00:00','2026-04-20 04:00:00');
INSERT INTO tb_blog VALUES (9,9,10,'周末探店｜知味观(湖滨总店)体验报告📋杭州美食天花板','https://picsum.photos/seed/blog9a/400/300,https://picsum.photos/seed/blog9b/400/300','杭州的美食我去过不少，但这家的体验真的是天花板级别的🏆

【店铺信息】
🏪 店名：知味观(湖滨总店)
📍 地址：湖滨/武林
💰 人均：45元

【探店体验】

🧡环境：空间很大不拥挤，干净整洁，氛围感绝了

🧡服务：店员很专业，会耐心讲解，不会强行推销

🧡体验：真的是物超所值，每一项都让人满意

【总结】
这绝对是我今年去过最值得推荐的美食之一！
不管是和朋友一起还是一个人来都很合适～

姐妹们信我，闭眼冲就完事了💨

#杭州探店 #美食 #周末去哪儿 #杭州吃喝玩乐',111,25,'2026-05-13 13:00:00','2026-05-13 13:00:00');
INSERT INTO tb_blog VALUES (10,10,10,'周末探店｜楼外楼(孤山路店)体验报告📋杭州美食天花板','https://picsum.photos/seed/blog10a/400/300,https://picsum.photos/seed/blog10b/400/300','杭州的美食我去过不少，但这家的体验真的是天花板级别的🏆

【店铺信息】
🏪 店名：楼外楼(孤山路店)
📍 地址：西湖
💰 人均：150元

【探店体验】

🧡环境：空间很大不拥挤，干净整洁，氛围感绝了

🧡服务：店员很专业，会耐心讲解，不会强行推销

🧡体验：真的是物超所值，每一项都让人满意

【总结】
这绝对是我今年去过最值得推荐的美食之一！
不管是和朋友一起还是一个人来都很合适～

姐妹们信我，闭眼冲就完事了💨

#杭州探店 #美食 #周末去哪儿 #杭州吃喝玩乐',229,17,'2026-04-11 03:00:00','2026-04-11 03:00:00');
INSERT INTO tb_blog VALUES (11,11,8,'周末探店｜卤儿道道(钱江新城店)体验报告📋杭州美食天花板','https://picsum.photos/seed/blog11a/400/300,https://picsum.photos/seed/blog11b/400/300','杭州的美食我去过不少，但这家的体验真的是天花板级别的🏆

【店铺信息】
🏪 店名：卤儿道道(钱江新城店)
📍 地址：钱江新城
💰 人均：55元

【探店体验】

🧡环境：空间很大不拥挤，干净整洁，氛围感绝了

🧡服务：店员很专业，会耐心讲解，不会强行推销

🧡体验：真的是物超所值，每一项都让人满意

【总结】
这绝对是我今年去过最值得推荐的美食之一！
不管是和朋友一起还是一个人来都很合适～

姐妹们信我，闭眼冲就完事了💨

#杭州探店 #美食 #周末去哪儿 #杭州吃喝玩乐',68,44,'2026-05-05 20:00:00','2026-05-05 20:00:00');
INSERT INTO tb_blog VALUES (12,12,11,'周末探店｜蟹觅·蟹黄面(滨江店)体验报告📋杭州美食天花板','https://picsum.photos/seed/blog12a/400/300,https://picsum.photos/seed/blog12b/400/300','杭州的美食我去过不少，但这家的体验真的是天花板级别的🏆

【店铺信息】
🏪 店名：蟹觅·蟹黄面(滨江店)
📍 地址：滨江
💰 人均：88元

【探店体验】

🧡环境：空间很大不拥挤，干净整洁，氛围感绝了

🧡服务：店员很专业，会耐心讲解，不会强行推销

🧡体验：真的是物超所值，每一项都让人满意

【总结】
这绝对是我今年去过最值得推荐的美食之一！
不管是和朋友一起还是一个人来都很合适～

姐妹们信我，闭眼冲就完事了💨

#杭州探店 #美食 #周末去哪儿 #杭州吃喝玩乐',108,28,'2026-05-04 00:00:00','2026-05-04 00:00:00');
INSERT INTO tb_blog VALUES (13,13,6,'杭州探店｜藏在运河上街的宝藏KTV🔥绝绝子','https://picsum.photos/seed/blog13a/400/300,https://picsum.photos/seed/blog13b/400/300','挖到宝了家人们！！

在运河上街逛的时候发现了一家超级低调的宝藏店铺🏪

开乐迪KTV(运河上街店)

一进门就被装修风格吸引了，太有感觉了！细节满满，每个角落都很用心✨

说说体验感受：

1️⃣ 环境氛围感拉满，灯光音乐都恰到好处
2️⃣ 服务态度超级好，很贴心
3️⃣ 性价比绝了，才花了不到67块

唯一的缺点就是：为什么我现在才发现啊！！

已经安利给身边所有朋友了，个个都说好👍

杭州的宝子们快冲！绝对不会后悔！

#杭州探店 #杭州生活 #KTV推荐',56,18,'2026-03-31 10:00:00','2026-03-31 10:00:00');
INSERT INTO tb_blog VALUES (14,14,5,'INLOVE KTV(水晶城店)｜杭州人必打卡的宝藏店铺💎亲测不踩雷','https://picsum.photos/seed/blog14a/400/300,https://picsum.photos/seed/blog14b/400/300','作为一个在杭州生活了20多年的土著，这家店我真的要吹爆💥

INLOVE KTV(水晶城店)位于水晶城，位置很好找，交通也方便🚇

来了不下5次了，每次都有新惊喜：

✨亮点一：品质稳定，每次来都是一个水准
✨亮点二：性价比高，人均75的消费完全对得起体验
✨亮点三：服务到位，不会过度热情也不会冷漠

最近他们家还出了新项目/新菜，试了一下果然没让我失望！

老规矩，结尾放攻略👇
⏰建议错开周末高峰期
📍地址：水晶城
💰人均：75元

#杭州打卡 #杭州周末去哪 #探店分享',192,29,'2026-04-27 16:00:00','2026-04-27 16:00:00');
INSERT INTO tb_blog VALUES (15,15,4,'谁懂啊！！北部新城这家星聚会KTV(拱墅万达店)真的太绝了🥹💕','https://picsum.photos/seed/blog15a/400/300,https://picsum.photos/seed/blog15b/400/300','啊啊啊啊我真的会谢🫠

之前就听说北部新城有家很不错的KTV，今天终于来打卡了！

🏪店名：星聚会KTV(拱墅万达店)
📍地址：北部新城

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才60，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',67,3,'2026-05-01 23:00:00','2026-05-01 23:00:00');
INSERT INTO tb_blog VALUES (16,16,6,'谁懂啊！！湖滨/武林这家纯K(湖滨银泰店)真的太绝了🥹💕','https://picsum.photos/seed/blog16a/400/300,https://picsum.photos/seed/blog16b/400/300','啊啊啊啊我真的会谢🫠

之前就听说湖滨/武林有家很不错的KTV，今天终于来打卡了！

🏪店名：纯K(湖滨银泰店)
📍地址：湖滨/武林

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才88，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',216,4,'2026-05-08 15:00:00','2026-05-08 15:00:00');
INSERT INTO tb_blog VALUES (17,17,8,'谁懂啊！！湖滨/武林这家好乐迪KTV(武林店)真的太绝了🥹💕','https://picsum.photos/seed/blog17a/400/300,https://picsum.photos/seed/blog17b/400/300','啊啊啊啊我真的会谢🫠

之前就听说湖滨/武林有家很不错的KTV，今天终于来打卡了！

🏪店名：好乐迪KTV(武林店)
📍地址：湖滨/武林

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才55，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',87,35,'2026-04-19 23:00:00','2026-04-19 23:00:00');
INSERT INTO tb_blog VALUES (18,18,10,'周末探店｜唱吧麦颂(滨江宝龙店)体验报告📋杭州KTV天花板','https://picsum.photos/seed/blog18a/400/300,https://picsum.photos/seed/blog18b/400/300','杭州的KTV我去过不少，但这家的体验真的是天花板级别的🏆

【店铺信息】
🏪 店名：唱吧麦颂(滨江宝龙店)
📍 地址：滨江
💰 人均：49元

【探店体验】

🧡环境：空间很大不拥挤，干净整洁，氛围感绝了

🧡服务：店员很专业，会耐心讲解，不会强行推销

🧡体验：真的是物超所值，每一项都让人满意

【总结】
这绝对是我今年去过最值得推荐的KTV之一！
不管是和朋友一起还是一个人来都很合适～

姐妹们信我，闭眼冲就完事了💨

#杭州探店 #KTV #周末去哪儿 #杭州吃喝玩乐',102,29,'2026-05-12 12:00:00','2026-05-12 12:00:00');
INSERT INTO tb_blog VALUES (19,19,1,'谁懂啊！！湖滨/武林这家侨治发型(武林店)真的太绝了🥹💕','https://picsum.photos/seed/blog19a/400/300,https://picsum.photos/seed/blog19b/400/300','啊啊啊啊我真的会谢🫠

之前就听说湖滨/武林有家很不错的丽人·美发，今天终于来打卡了！

🏪店名：侨治发型(武林店)
📍地址：湖滨/武林

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才128，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',77,33,'2026-04-02 12:00:00','2026-04-02 12:00:00');
INSERT INTO tb_blog VALUES (20,20,5,'被这家店的性价比震惊到了🤯人均280吃到撑','https://picsum.photos/seed/blog20a/400/300,https://picsum.photos/seed/blog20b/400/300','今天和姐妹在湖滨/武林逛街，无意间发现了这家TONI&GUY(湖滨银泰店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才280块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：湖滨/武林
🕐营业时间：10:00-22:00
💰人均：280元
⭐推荐指数：🌟🌟🌟🌟🌟',30,9,'2026-04-24 18:00:00','2026-04-24 18:00:00');
INSERT INTO tb_blog VALUES (21,21,11,'谁懂啊！！城西这家杜尚发艺(城西银泰店)真的太绝了🥹💕','https://picsum.photos/seed/blog21a/400/300,https://picsum.photos/seed/blog21b/400/300','啊啊啊啊我真的会谢🫠

之前就听说城西有家很不错的丽人·美发，今天终于来打卡了！

🏪店名：杜尚发艺(城西银泰店)
📍地址：城西

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才158，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',120,38,'2026-04-04 03:00:00','2026-04-04 03:00:00');
INSERT INTO tb_blog VALUES (22,22,1,'谁懂啊！！滨江这家尚艺美容美发(滨江店)真的太绝了🥹💕','https://picsum.photos/seed/blog22a/400/300,https://picsum.photos/seed/blog22b/400/300','啊啊啊啊我真的会谢🫠

之前就听说滨江有家很不错的丽人·美发，今天终于来打卡了！

🏪店名：尚艺美容美发(滨江店)
📍地址：滨江

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才68，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',130,3,'2026-05-14 21:00:00','2026-05-14 21:00:00');
INSERT INTO tb_blog VALUES (23,23,5,'谁懂啊！！钱江新城这家东瀛美发(钱江新城店)真的太绝了🥹💕','https://picsum.photos/seed/blog23a/400/300,https://picsum.photos/seed/blog23b/400/300','啊啊啊啊我真的会谢🫠

之前就听说钱江新城有家很不错的丽人·美发，今天终于来打卡了！

🏪店名：东瀛美发(钱江新城店)
📍地址：钱江新城

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才198，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',160,28,'2026-05-09 08:00:00','2026-05-09 08:00:00');
INSERT INTO tb_blog VALUES (24,24,9,'被这家店的性价比震惊到了🤯人均99吃到撑','https://picsum.photos/seed/blog24a/400/300,https://picsum.photos/seed/blog24b/400/300','今天和姐妹在湖滨/武林逛街，无意间发现了这家乐刻健身(武林店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才99块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：湖滨/武林
🕐营业时间：06:00-23:00
💰人均：99元
⭐推荐指数：🌟🌟🌟🌟🌟',231,24,'2026-04-02 01:00:00','2026-04-02 01:00:00');
INSERT INTO tb_blog VALUES (25,25,8,'被这家店的性价比震惊到了🤯人均129吃到撑','https://picsum.photos/seed/blog25a/400/300,https://picsum.photos/seed/blog25b/400/300','今天和姐妹在湖滨/武林逛街，无意间发现了这家超级猩猩(湖滨店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才129块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：湖滨/武林
🕐营业时间：07:00-22:00
💰人均：129元
⭐推荐指数：🌟🌟🌟🌟🌟',76,15,'2026-04-02 12:00:00','2026-04-02 12:00:00');
INSERT INTO tb_blog VALUES (26,26,1,'威尔仕健身(钱江新城店)｜杭州人必打卡的宝藏店铺💎亲测不踩雷','https://picsum.photos/seed/blog26a/400/300,https://picsum.photos/seed/blog26b/400/300','作为一个在杭州生活了20多年的土著，这家店我真的要吹爆💥

威尔仕健身(钱江新城店)位于钱江新城，位置很好找，交通也方便🚇

来了不下5次了，每次都有新惊喜：

✨亮点一：品质稳定，每次来都是一个水准
✨亮点二：性价比高，人均199的消费完全对得起体验
✨亮点三：服务到位，不会过度热情也不会冷漠

最近他们家还出了新项目/新菜，试了一下果然没让我失望！

老规矩，结尾放攻略👇
⏰建议错开周末高峰期
📍地址：钱江新城
💰人均：199元

#杭州打卡 #杭州周末去哪 #探店分享',21,31,'2026-04-24 19:00:00','2026-04-24 19:00:00');
INSERT INTO tb_blog VALUES (27,27,1,'舒适堡(城西银泰店)｜杭州人必打卡的宝藏店铺💎亲测不踩雷','https://picsum.photos/seed/blog27a/400/300,https://picsum.photos/seed/blog27b/400/300','作为一个在杭州生活了20多年的土著，这家店我真的要吹爆💥

舒适堡(城西银泰店)位于城西，位置很好找，交通也方便🚇

来了不下5次了，每次都有新惊喜：

✨亮点一：品质稳定，每次来都是一个水准
✨亮点二：性价比高，人均159的消费完全对得起体验
✨亮点三：服务到位，不会过度热情也不会冷漠

最近他们家还出了新项目/新菜，试了一下果然没让我失望！

老规矩，结尾放攻略👇
⏰建议错开周末高峰期
📍地址：城西
💰人均：159元

#杭州打卡 #杭州周末去哪 #探店分享',249,44,'2026-05-04 13:00:00','2026-05-04 13:00:00');
INSERT INTO tb_blog VALUES (28,28,2,'被这家店的性价比震惊到了🤯人均169吃到撑','https://picsum.photos/seed/blog28a/400/300,https://picsum.photos/seed/blog28b/400/300','今天和姐妹在滨江逛街，无意间发现了这家一兆韦德(滨江店)！真的一整个爱住❤️

先说环境：店面很大，装修风格超ins，拍照📷超级出片！

重点当然是吃的啦～我们点了招牌菜，每一道都不踩雷：
🥇 招牌必点：一端上来就被香到了，份量也很良心
🥈 甜品：颜值和味道都在线，甜而不腻
🥉 饮品：清爽解腻，颜值在线

最后结账的时候真的惊了，人均才169块！在杭州这个价位真的太难得了

服务也很nice，小姐姐全程微笑，上菜速度也很快～

下次一定会再来！强烈安利给各位宝子们✨

📍地址：滨江
🕐营业时间：07:00-23:00
💰人均：169元
⭐推荐指数：🌟🌟🌟🌟🌟',62,22,'2026-04-22 01:00:00','2026-04-22 01:00:00');
INSERT INTO tb_blog VALUES (29,29,11,'谁懂啊！！湖滨/武林这家华夏良子(武林店)真的太绝了🥹💕','https://picsum.photos/seed/blog29a/400/300,https://picsum.photos/seed/blog29b/400/300','啊啊啊啊我真的会谢🫠

之前就听说湖滨/武林有家很不错的按摩·足疗，今天终于来打卡了！

🏪店名：华夏良子(武林店)
📍地址：湖滨/武林

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才198，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',178,6,'2026-05-08 01:00:00','2026-05-08 01:00:00');
INSERT INTO tb_blog VALUES (30,30,3,'谁懂啊！！城西这家康骏养生(城西店)真的太绝了🥹💕','https://picsum.photos/seed/blog30a/400/300,https://picsum.photos/seed/blog30b/400/300','啊啊啊啊我真的会谢🫠

之前就听说城西有家很不错的按摩·足疗，今天终于来打卡了！

🏪店名：康骏养生(城西店)
📍地址：城西

一进门就被惊艳到了！比我想象的还要好！

几个让我印象深刻的点：

⭐️ 第一，环境真的没话说，每个角落都适合拍照打卡📸
⭐️ 第二，人均才168，这个价位有这样的体验真的很良心
⭐️ 第三，细节做得很到位，看得出老板很用心在经营

一定是会二刷三刷的店！

杭州的宝子们千万不要错过啊，趁着还没排长队赶紧去！

#杭州神仙店铺 #探店 #杭州必打卡 #种草',39,12,'2026-05-05 12:00:00','2026-05-05 12:00:00');

DROP TABLE IF EXISTS `tb_blog_comments`;
CREATE TABLE `tb_blog_comments` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '用户id',
  `blog_id` bigint(20) UNSIGNED NOT NULL COMMENT '探店id',
  `parent_id` bigint(20) UNSIGNED NOT NULL COMMENT '关联的1级评论id',
  `answer_id` bigint(20) UNSIGNED NOT NULL COMMENT '回复的评论id',
  `content` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '回复的内容',
  `liked` int(8) UNSIGNED NULL DEFAULT NULL COMMENT '点赞数',
  `status` tinyint(1) UNSIGNED NULL DEFAULT NULL COMMENT '状态',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 100 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_blog_comments VALUES (1,2,1,0,0,'姐妹请问停车方便吗？',9,0,'2026-04-14 13:00:00','2026-04-14 13:00:00');
INSERT INTO tb_blog_comments VALUES (2,4,1,0,0,'杭州居然还有这种宝藏地方！',5,0,'2026-04-13 16:00:00','2026-04-13 16:00:00');
INSERT INTO tb_blog_comments VALUES (3,2,2,0,0,'请问周末人多吗？需要排队吗',8,0,'2026-04-15 10:00:00','2026-04-15 10:00:00');
INSERT INTO tb_blog_comments VALUES (4,8,2,0,0,'太好看啦！！已收藏✨',17,0,'2026-04-15 11:00:00','2026-04-15 11:00:00');
INSERT INTO tb_blog_comments VALUES (5,9,2,0,0,'姐妹请问停车方便吗？',10,0,'2026-04-15 12:00:00','2026-04-15 12:00:00');
INSERT INTO tb_blog_comments VALUES (6,5,3,0,0,'姐妹请问停车方便吗？',14,0,'2026-05-05 14:00:00','2026-05-05 14:00:00');
INSERT INTO tb_blog_comments VALUES (7,1,3,0,0,'写得真好，种草了🌿',9,0,'2026-05-04 16:00:00','2026-05-04 16:00:00');
INSERT INTO tb_blog_comments VALUES (8,7,4,0,0,'杭州居然还有这种宝藏地方！',17,0,'2026-05-11 10:00:00','2026-05-11 10:00:00');
INSERT INTO tb_blog_comments VALUES (9,1,4,0,0,'这家我也去过！真的不错👍',9,0,'2026-05-11 21:00:00','2026-05-11 21:00:00');
INSERT INTO tb_blog_comments VALUES (10,2,4,0,0,'请问适不适合带小朋友去呀？',5,0,'2026-05-12 19:00:00','2026-05-12 19:00:00');
INSERT INTO tb_blog_comments VALUES (11,3,5,0,0,'太好看啦！！已收藏✨',9,0,'2026-04-05 10:00:00','2026-04-05 10:00:00');
INSERT INTO tb_blog_comments VALUES (12,11,5,0,0,'太好看啦！！已收藏✨',19,0,'2026-04-03 17:00:00','2026-04-03 17:00:00');
INSERT INTO tb_blog_comments VALUES (13,4,6,0,0,'这家我也去过！真的不错👍',18,0,'2026-04-30 19:00:00','2026-04-30 19:00:00');
INSERT INTO tb_blog_comments VALUES (14,10,6,0,0,'杭州居然还有这种宝藏地方！',6,0,'2026-04-29 13:00:00','2026-04-29 13:00:00');
INSERT INTO tb_blog_comments VALUES (15,2,7,0,0,'收藏了！下次约会就去这里',19,0,'2026-04-02 15:00:00','2026-04-02 15:00:00');
INSERT INTO tb_blog_comments VALUES (16,7,8,0,0,'环境看起来好棒，适合拍照吗？',5,0,'2026-04-21 15:00:00','2026-04-21 15:00:00');
INSERT INTO tb_blog_comments VALUES (17,4,8,0,0,'姐妹请问停车方便吗？',13,0,'2026-04-21 16:00:00','2026-04-21 16:00:00');
INSERT INTO tb_blog_comments VALUES (18,5,8,17,4,'回复 @西湖边的猫：周末人挺多的，建议工作日去',10,0,'2026-04-21 18:00:00','2026-04-21 18:00:00');
INSERT INTO tb_blog_comments VALUES (19,9,9,0,0,'姐妹请问停车方便吗？',17,0,'2026-05-14 11:00:00','2026-05-14 11:00:00');
INSERT INTO tb_blog_comments VALUES (20,8,9,0,0,'写得真好，种草了🌿',20,0,'2026-05-16 10:00:00','2026-05-16 10:00:00');
INSERT INTO tb_blog_comments VALUES (21,9,9,0,0,'这家我也去过！真的不错👍',13,0,'2026-05-15 14:00:00','2026-05-15 14:00:00');
INSERT INTO tb_blog_comments VALUES (22,2,10,0,0,'杭州居然还有这种宝藏地方！',15,0,'2026-04-13 17:00:00','2026-04-13 17:00:00');
INSERT INTO tb_blog_comments VALUES (23,8,10,0,0,'收藏了！下次约会就去这里',2,0,'2026-04-13 21:00:00','2026-04-13 21:00:00');
INSERT INTO tb_blog_comments VALUES (24,10,10,23,8,'回复 @武林广场舞王：有地下停车场，很方便！',4,0,'2026-04-13 10:00:00','2026-04-13 10:00:00');
INSERT INTO tb_blog_comments VALUES (25,3,11,0,0,'写得真好，种草了🌿',16,0,'2026-05-07 15:00:00','2026-05-07 15:00:00');
INSERT INTO tb_blog_comments VALUES (26,9,11,0,0,'这家我也去过！真的不错👍',19,0,'2026-05-06 17:00:00','2026-05-06 17:00:00');
INSERT INTO tb_blog_comments VALUES (27,8,11,26,9,'回复 @龙井茶不茶：周末人挺多的，建议工作日去',17,0,'2026-05-06 20:00:00','2026-05-06 20:00:00');
INSERT INTO tb_blog_comments VALUES (28,6,12,0,0,'姐妹请问停车方便吗？',1,0,'2026-05-05 14:00:00','2026-05-05 14:00:00');
INSERT INTO tb_blog_comments VALUES (29,5,12,0,0,'拍得好好看！请问需要预约吗？',4,0,'2026-05-05 12:00:00','2026-05-05 12:00:00');
INSERT INTO tb_blog_comments VALUES (30,12,12,0,0,'写得真好，种草了🌿',18,0,'2026-05-07 19:00:00','2026-05-07 19:00:00');
INSERT INTO tb_blog_comments VALUES (31,11,12,30,12,'回复 @萧山大哥大：有地下停车场，很方便！',10,0,'2026-05-06 13:00:00','2026-05-06 13:00:00');
INSERT INTO tb_blog_comments VALUES (32,12,13,0,0,'请问适不适合带小朋友去呀？',14,0,'2026-04-02 16:00:00','2026-04-02 16:00:00');
INSERT INTO tb_blog_comments VALUES (33,6,13,32,12,'回复 @萧山大哥大：人均大概在67左右哦～',2,0,'2026-04-01 20:00:00','2026-04-01 20:00:00');
INSERT INTO tb_blog_comments VALUES (34,7,14,0,0,'姐妹请问停车方便吗？',11,0,'2026-04-29 11:00:00','2026-04-29 11:00:00');
INSERT INTO tb_blog_comments VALUES (35,5,14,34,7,'回复 @杭州小辣椒：人均大概在75左右哦～',10,0,'2026-04-29 15:00:00','2026-04-29 15:00:00');
INSERT INTO tb_blog_comments VALUES (36,1,15,0,0,'写得真好，种草了🌿',3,0,'2026-05-04 22:00:00','2026-05-04 22:00:00');
INSERT INTO tb_blog_comments VALUES (37,10,16,0,0,'拍得好好看！请问需要预约吗？',5,0,'2026-05-11 15:00:00','2026-05-11 15:00:00');
INSERT INTO tb_blog_comments VALUES (38,3,16,0,0,'请问周末人多吗？需要排队吗',14,0,'2026-05-09 14:00:00','2026-05-09 14:00:00');
INSERT INTO tb_blog_comments VALUES (39,12,17,0,0,'收藏了！下次约会就去这里',20,0,'2026-04-21 22:00:00','2026-04-21 22:00:00');
INSERT INTO tb_blog_comments VALUES (40,2,17,0,0,'请问适不适合带小朋友去呀？',13,0,'2026-04-21 19:00:00','2026-04-21 19:00:00');
INSERT INTO tb_blog_comments VALUES (41,5,18,0,0,'拍得好好看！请问需要预约吗？',19,0,'2026-05-14 22:00:00','2026-05-14 22:00:00');
INSERT INTO tb_blog_comments VALUES (42,6,19,0,0,'哇塞，看着就好心动啊',1,0,'2026-04-05 09:00:00','2026-04-05 09:00:00');
INSERT INTO tb_blog_comments VALUES (43,1,19,42,6,'回复 @钱塘江边的人：完全适合！我带娃去过两次了',1,0,'2026-04-04 19:00:00','2026-04-04 19:00:00');
INSERT INTO tb_blog_comments VALUES (44,9,20,0,0,'请问周末人多吗？需要排队吗',9,0,'2026-04-26 11:00:00','2026-04-26 11:00:00');
INSERT INTO tb_blog_comments VALUES (45,4,20,0,0,'太好看啦！！已收藏✨',17,0,'2026-04-25 15:00:00','2026-04-25 15:00:00');
INSERT INTO tb_blog_comments VALUES (46,6,20,0,0,'哇塞，看着就好心动啊',13,0,'2026-04-27 12:00:00','2026-04-27 12:00:00');
INSERT INTO tb_blog_comments VALUES (47,5,20,46,6,'回复 @钱塘江边的人：人均大概在280左右哦～',13,0,'2026-04-25 15:00:00','2026-04-25 15:00:00');
INSERT INTO tb_blog_comments VALUES (48,8,21,0,0,'杭州居然还有这种宝藏地方！',15,0,'2026-04-07 16:00:00','2026-04-07 16:00:00');
INSERT INTO tb_blog_comments VALUES (49,7,21,0,0,'这家我也去过！真的不错👍',10,0,'2026-04-07 17:00:00','2026-04-07 17:00:00');
INSERT INTO tb_blog_comments VALUES (50,8,21,0,0,'哇塞，看着就好心动啊',9,0,'2026-04-07 16:00:00','2026-04-07 16:00:00');
INSERT INTO tb_blog_comments VALUES (51,10,22,0,0,'拍得好好看！请问需要预约吗？',0,0,'2026-05-15 19:00:00','2026-05-15 19:00:00');
INSERT INTO tb_blog_comments VALUES (52,1,22,51,10,'回复 @滨江小霸王：有地下停车场，很方便！',20,0,'2026-05-16 19:00:00','2026-05-16 19:00:00');
INSERT INTO tb_blog_comments VALUES (53,11,23,0,0,'环境看起来好棒，适合拍照吗？',15,0,'2026-05-11 19:00:00','2026-05-11 19:00:00');
INSERT INTO tb_blog_comments VALUES (54,8,24,0,0,'人均多少呀？想去试试～',11,0,'2026-04-03 09:00:00','2026-04-03 09:00:00');
INSERT INTO tb_blog_comments VALUES (55,7,24,0,0,'太好看啦！！已收藏✨',11,0,'2026-04-05 14:00:00','2026-04-05 14:00:00');
INSERT INTO tb_blog_comments VALUES (56,4,24,0,0,'收藏了！下次约会就去这里',7,0,'2026-04-04 09:00:00','2026-04-04 09:00:00');
INSERT INTO tb_blog_comments VALUES (57,11,25,0,0,'请问周末人多吗？需要排队吗',20,0,'2026-04-03 09:00:00','2026-04-03 09:00:00');
INSERT INTO tb_blog_comments VALUES (58,2,25,0,0,'请问适不适合带小朋友去呀？',6,0,'2026-04-03 19:00:00','2026-04-03 19:00:00');
INSERT INTO tb_blog_comments VALUES (59,8,25,58,2,'回复 @可可今天不吃肉：周末人挺多的，建议工作日去',11,0,'2026-04-04 17:00:00','2026-04-04 17:00:00');
INSERT INTO tb_blog_comments VALUES (60,3,26,0,0,'太好看啦！！已收藏✨',5,0,'2026-04-25 12:00:00','2026-04-25 12:00:00');
INSERT INTO tb_blog_comments VALUES (61,6,26,0,0,'姐妹请问停车方便吗？',1,0,'2026-04-26 11:00:00','2026-04-26 11:00:00');
INSERT INTO tb_blog_comments VALUES (62,1,26,61,6,'回复 @钱塘江边的人：有地下停车场，很方便！',1,0,'2026-04-26 11:00:00','2026-04-26 11:00:00');
INSERT INTO tb_blog_comments VALUES (63,9,27,0,0,'杭州居然还有这种宝藏地方！',14,0,'2026-05-05 10:00:00','2026-05-05 10:00:00');
INSERT INTO tb_blog_comments VALUES (64,9,27,0,0,'哇塞，看着就好心动啊',5,0,'2026-05-06 16:00:00','2026-05-06 16:00:00');
INSERT INTO tb_blog_comments VALUES (65,7,27,0,0,'请问适不适合带小朋友去呀？',14,0,'2026-05-07 13:00:00','2026-05-07 13:00:00');
INSERT INTO tb_blog_comments VALUES (66,5,28,0,0,'杭州居然还有这种宝藏地方！',6,0,'2026-04-25 18:00:00','2026-04-25 18:00:00');
INSERT INTO tb_blog_comments VALUES (67,10,28,0,0,'杭州居然还有这种宝藏地方！',19,0,'2026-04-23 21:00:00','2026-04-23 21:00:00');
INSERT INTO tb_blog_comments VALUES (68,10,28,0,0,'真的超级棒！下次还要来🤩',2,0,'2026-04-24 11:00:00','2026-04-24 11:00:00');
INSERT INTO tb_blog_comments VALUES (69,4,29,0,0,'这家我也去过！真的不错👍',0,0,'2026-05-09 22:00:00','2026-05-09 22:00:00');
INSERT INTO tb_blog_comments VALUES (70,11,29,69,4,'回复 @西湖边的猫：有地下停车场，很方便！',9,0,'2026-05-09 21:00:00','2026-05-09 21:00:00');
INSERT INTO tb_blog_comments VALUES (71,10,30,0,0,'写得真好，种草了🌿',20,0,'2026-05-06 15:00:00','2026-05-06 15:00:00');
INSERT INTO tb_blog_comments VALUES (72,3,30,71,10,'回复 @滨江小霸王：人均大概在168左右哦～',1,0,'2026-05-06 12:00:00','2026-05-06 12:00:00');

DROP TABLE IF EXISTS `tb_follow`;
CREATE TABLE `tb_follow` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '用户id',
  `follow_user_id` bigint(20) UNSIGNED NOT NULL COMMENT '关联的用户id',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 100 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_follow VALUES (1,1,10,'2026-04-14 02:00:00');
INSERT INTO tb_follow VALUES (2,1,9,'2026-04-14 02:00:00');
INSERT INTO tb_follow VALUES (3,1,11,'2026-04-02 02:00:00');
INSERT INTO tb_follow VALUES (4,1,4,'2026-03-24 02:00:00');
INSERT INTO tb_follow VALUES (5,2,1,'2026-05-07 02:00:00');
INSERT INTO tb_follow VALUES (6,2,5,'2026-04-14 02:00:00');
INSERT INTO tb_follow VALUES (7,2,7,'2026-04-08 02:00:00');
INSERT INTO tb_follow VALUES (8,3,8,'2026-05-04 02:00:00');
INSERT INTO tb_follow VALUES (9,3,11,'2026-04-04 02:00:00');
INSERT INTO tb_follow VALUES (10,3,6,'2026-03-28 02:00:00');
INSERT INTO tb_follow VALUES (11,4,8,'2026-04-17 02:00:00');
INSERT INTO tb_follow VALUES (12,4,11,'2026-04-29 02:00:00');
INSERT INTO tb_follow VALUES (13,5,11,'2026-04-02 02:00:00');
INSERT INTO tb_follow VALUES (14,5,6,'2026-03-19 02:00:00');
INSERT INTO tb_follow VALUES (15,5,4,'2026-04-04 02:00:00');
INSERT INTO tb_follow VALUES (16,5,2,'2026-04-05 02:00:00');
INSERT INTO tb_follow VALUES (17,5,1,'2026-03-28 02:00:00');
INSERT INTO tb_follow VALUES (18,6,4,'2026-03-30 02:00:00');
INSERT INTO tb_follow VALUES (19,6,7,'2026-04-05 02:00:00');
INSERT INTO tb_follow VALUES (20,7,11,'2026-04-12 02:00:00');
INSERT INTO tb_follow VALUES (21,7,3,'2026-04-27 02:00:00');
INSERT INTO tb_follow VALUES (22,7,9,'2026-04-16 02:00:00');
INSERT INTO tb_follow VALUES (23,7,2,'2026-03-25 02:00:00');
INSERT INTO tb_follow VALUES (24,7,5,'2026-03-20 02:00:00');
INSERT INTO tb_follow VALUES (25,8,2,'2026-04-22 02:00:00');
INSERT INTO tb_follow VALUES (26,8,7,'2026-04-11 02:00:00');
INSERT INTO tb_follow VALUES (27,8,11,'2026-04-22 02:00:00');
INSERT INTO tb_follow VALUES (28,8,1,'2026-03-24 02:00:00');
INSERT INTO tb_follow VALUES (29,9,7,'2026-05-06 02:00:00');
INSERT INTO tb_follow VALUES (30,9,8,'2026-04-09 02:00:00');
INSERT INTO tb_follow VALUES (31,9,2,'2026-03-17 02:00:00');
INSERT INTO tb_follow VALUES (32,10,9,'2026-05-02 02:00:00');
INSERT INTO tb_follow VALUES (33,10,5,'2026-05-02 02:00:00');
INSERT INTO tb_follow VALUES (34,10,12,'2026-05-07 02:00:00');
INSERT INTO tb_follow VALUES (35,11,2,'2026-04-22 02:00:00');
INSERT INTO tb_follow VALUES (36,11,7,'2026-05-06 02:00:00');
INSERT INTO tb_follow VALUES (37,11,8,'2026-04-18 02:00:00');
INSERT INTO tb_follow VALUES (38,11,4,'2026-03-28 02:00:00');
INSERT INTO tb_follow VALUES (39,11,10,'2026-04-29 02:00:00');
INSERT INTO tb_follow VALUES (40,11,1,'2026-03-22 02:00:00');
INSERT INTO tb_follow VALUES (41,12,8,'2026-03-20 02:00:00');
INSERT INTO tb_follow VALUES (42,12,7,'2026-04-16 02:00:00');
INSERT INTO tb_follow VALUES (43,12,9,'2026-04-25 02:00:00');
INSERT INTO tb_follow VALUES (44,12,6,'2026-05-10 02:00:00');

DROP TABLE IF EXISTS `tb_voucher`;
CREATE TABLE `tb_voucher` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `shop_id` bigint(20) UNSIGNED NULL DEFAULT NULL COMMENT '商铺id',
  `title` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '代金券标题',
  `sub_title` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '副标题',
  `rules` varchar(1024) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '使用规则',
  `pay_value` bigint(10) UNSIGNED NOT NULL COMMENT '支付金额',
  `actual_value` bigint(10) NOT NULL COMMENT '抵扣金额',
  `type` tinyint(1) UNSIGNED NOT NULL DEFAULT 0 COMMENT '0,普通券；1,秒杀券',
  `status` tinyint(1) UNSIGNED NOT NULL DEFAULT 1 COMMENT '1,上架; 2,下架; 3,过期',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 13 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_voucher VALUES (1,1,'50元代金券','周一至周日通用','全场通用\\n无需预约\\n可无限叠加\\n不兑现、不找零\\n仅限堂食',4750,5000,0,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (2,3,'30元代金券','新白鹿专享优惠','全场通用\\n无需预约\\n每桌限用一张\\n不兑现、不找零',2750,3000,0,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (3,5,'海底捞100元券','火锅专享','仅限堂食\\n需提前预约\\n不可叠加使用\\n不兑现、不找零',8500,10000,0,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (4,7,'20元饮品券','外婆家饮品专享','仅限饮品\\n无需预约\\n可叠加使用\\n不兑现',1500,2000,0,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (5,11,'蟹觅尝鲜券','新品体验','仅限指定新品\\n需提前一天预约\\n每桌限一张\\n不兑现',4800,6000,0,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (6,18,'侨治理发抵扣券','全场通用','需提前预约\\n周末可用\\n不兑现、不找零',6800,8000,0,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (7,2,'🔥68元抵100元','限时秒杀·蔡馬洪涛','全场通用\\n不可叠加\\n有效期30天\\n不兑现、不找零',6800,10000,1,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (8,4,'🔥128元双人餐','限时秒杀·Mamala','仅限双人套餐\\n需预约\\n不可叠加\\n不兑现',8800,12800,1,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (9,13,'🔥29.9欢唱3小时','限时秒杀·纯K','仅限小包\\n需预约\\n周一至周四可用\\n不兑现',2990,8000,1,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (10,26,'🔥88元足疗体验','限时秒杀·华夏良子','仅限指定项目\\n需预约\\n有效期15天\\n不兑现',8800,12800,1,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (11,39,'🔥9.9元鸡尾酒','限时秒杀·MILL酒吧','仅限指定鸡尾酒\\n每人限购1张\\n需预约\\n不兑现',990,5800,1,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');
INSERT INTO tb_voucher VALUES (12,52,'🔥19.9元美甲体验','限时秒杀·悦诗风吟','仅限纯色美甲\\n需预约\\n有效期15天\\n不兑现',1990,6800,1,1,'2026-04-01 10:00:00','2026-04-15 08:00:00');

DROP TABLE IF EXISTS `tb_seckill_voucher`;
CREATE TABLE `tb_seckill_voucher` (
  `voucher_id` bigint(20) UNSIGNED NOT NULL COMMENT '关联的优惠券的id',
  `stock` int(8) NOT NULL COMMENT '库存',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `begin_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生效时间',
  `end_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '失效时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`voucher_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '秒杀优惠券表' ROW_FORMAT = Compact;

INSERT INTO tb_seckill_voucher VALUES (7,200,'2026-04-01 10:00:00','2026-05-01 00:00:00','2026-06-30 23:59:59','2026-04-15 08:00:00');
INSERT INTO tb_seckill_voucher VALUES (8,150,'2026-04-01 10:00:00','2026-05-01 00:00:00','2026-06-30 23:59:59','2026-04-15 08:00:00');
INSERT INTO tb_seckill_voucher VALUES (9,300,'2026-04-01 10:00:00','2026-04-15 00:00:00','2026-07-15 23:59:59','2026-04-15 08:00:00');
INSERT INTO tb_seckill_voucher VALUES (10,100,'2026-04-01 10:00:00','2026-05-10 00:00:00','2026-06-10 23:59:59','2026-04-15 08:00:00');
INSERT INTO tb_seckill_voucher VALUES (11,500,'2026-04-01 10:00:00','2026-05-01 00:00:00','2026-05-31 23:59:59','2026-04-15 08:00:00');
INSERT INTO tb_seckill_voucher VALUES (12,250,'2026-04-01 10:00:00','2026-05-15 00:00:00','2026-06-15 23:59:59','2026-04-15 08:00:00');

DROP TABLE IF EXISTS `tb_voucher_order`;
CREATE TABLE `tb_voucher_order` (
  `id` bigint(20) NOT NULL COMMENT '主键',
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '下单的用户id',
  `voucher_id` bigint(20) UNSIGNED NOT NULL COMMENT '购买的代金券id',
  `pay_type` tinyint(1) UNSIGNED NOT NULL DEFAULT 1 COMMENT '支付方式',
  `status` tinyint(1) UNSIGNED NOT NULL DEFAULT 1 COMMENT '订单状态',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下单时间',
  `pay_time` timestamp NULL DEFAULT NULL COMMENT '支付时间',
  `use_time` timestamp NULL DEFAULT NULL COMMENT '核销时间',
  `refund_time` timestamp NULL DEFAULT NULL COMMENT '退款时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_voucher_order VALUES (1001,9,7,1,2,'2026-05-06 02:00:00','2026-05-11 02:00:00','2026-05-01 02:00:00',NULL,'2026-05-06 02:00:00');
INSERT INTO tb_voucher_order VALUES (1002,6,2,2,2,'2026-04-23 02:00:00','2026-04-13 02:00:00',NULL,NULL,'2026-04-23 02:00:00');
INSERT INTO tb_voucher_order VALUES (1003,3,5,1,2,'2026-04-25 02:00:00','2026-04-11 02:00:00','2026-05-06 02:00:00',NULL,'2026-04-25 02:00:00');
INSERT INTO tb_voucher_order VALUES (1004,10,4,2,6,'2026-04-26 02:00:00','2026-04-24 02:00:00',NULL,'2026-05-08 02:00:00','2026-04-26 02:00:00');
INSERT INTO tb_voucher_order VALUES (1005,7,4,2,2,'2026-04-24 02:00:00','2026-04-23 02:00:00',NULL,NULL,'2026-04-24 02:00:00');
INSERT INTO tb_voucher_order VALUES (1006,12,10,3,2,'2026-05-06 02:00:00','2026-04-27 02:00:00','2026-04-22 02:00:00',NULL,'2026-05-06 02:00:00');
INSERT INTO tb_voucher_order VALUES (1007,9,10,3,6,'2026-05-12 02:00:00','2026-04-07 02:00:00',NULL,'2026-05-05 02:00:00','2026-05-12 02:00:00');
INSERT INTO tb_voucher_order VALUES (1008,10,8,3,2,'2026-04-14 02:00:00','2026-04-22 02:00:00','2026-04-27 02:00:00',NULL,'2026-04-14 02:00:00');
INSERT INTO tb_voucher_order VALUES (1009,3,4,1,2,'2026-05-03 02:00:00','2026-05-14 02:00:00',NULL,NULL,'2026-05-03 02:00:00');
INSERT INTO tb_voucher_order VALUES (1010,5,8,3,2,'2026-05-08 02:00:00','2026-05-04 02:00:00','2026-05-09 02:00:00',NULL,'2026-05-08 02:00:00');
INSERT INTO tb_voucher_order VALUES (1011,5,4,3,6,'2026-04-20 02:00:00','2026-05-10 02:00:00',NULL,'2026-05-10 02:00:00','2026-04-20 02:00:00');
INSERT INTO tb_voucher_order VALUES (1012,12,8,2,2,'2026-05-06 02:00:00','2026-04-08 02:00:00',NULL,NULL,'2026-05-06 02:00:00');
INSERT INTO tb_voucher_order VALUES (1013,12,4,2,2,'2026-04-09 02:00:00','2026-05-08 02:00:00','2026-05-14 02:00:00',NULL,'2026-04-09 02:00:00');
INSERT INTO tb_voucher_order VALUES (1014,9,3,3,6,'2026-05-14 02:00:00','2026-04-07 02:00:00',NULL,'2026-05-09 02:00:00','2026-05-14 02:00:00');
INSERT INTO tb_voucher_order VALUES (1015,2,3,3,2,'2026-04-21 02:00:00','2026-05-05 02:00:00','2026-05-10 02:00:00',NULL,'2026-04-21 02:00:00');
INSERT INTO tb_voucher_order VALUES (1016,4,10,1,2,'2026-04-05 02:00:00','2026-05-04 02:00:00',NULL,NULL,'2026-04-05 02:00:00');
INSERT INTO tb_voucher_order VALUES (1017,9,8,1,2,'2026-04-24 02:00:00','2026-05-09 02:00:00','2026-04-30 02:00:00',NULL,'2026-04-24 02:00:00');
INSERT INTO tb_voucher_order VALUES (1018,12,3,2,6,'2026-05-12 02:00:00','2026-04-26 02:00:00',NULL,'2026-05-08 02:00:00','2026-05-12 02:00:00');
INSERT INTO tb_voucher_order VALUES (1019,7,4,2,2,'2026-04-13 02:00:00','2026-04-29 02:00:00',NULL,NULL,'2026-04-13 02:00:00');
INSERT INTO tb_voucher_order VALUES (1020,2,6,3,2,'2026-05-14 02:00:00','2026-04-27 02:00:00','2026-05-08 02:00:00',NULL,'2026-05-14 02:00:00');
INSERT INTO tb_voucher_order VALUES (1021,8,4,3,6,'2026-04-06 02:00:00','2026-04-12 02:00:00',NULL,'2026-05-07 02:00:00','2026-04-06 02:00:00');
INSERT INTO tb_voucher_order VALUES (1022,2,2,1,2,'2026-04-11 02:00:00','2026-04-08 02:00:00','2026-04-15 02:00:00',NULL,'2026-04-11 02:00:00');
INSERT INTO tb_voucher_order VALUES (1023,5,10,2,2,'2026-04-27 02:00:00','2026-04-22 02:00:00',NULL,NULL,'2026-04-27 02:00:00');
INSERT INTO tb_voucher_order VALUES (1024,12,2,2,2,'2026-04-30 02:00:00','2026-05-05 02:00:00','2026-04-24 02:00:00',NULL,'2026-04-30 02:00:00');
INSERT INTO tb_voucher_order VALUES (1025,1,11,1,6,'2026-04-24 02:00:00','2026-04-19 02:00:00',NULL,'2026-05-05 02:00:00','2026-04-24 02:00:00');
INSERT INTO tb_voucher_order VALUES (1026,4,8,1,2,'2026-04-08 02:00:00','2026-04-29 02:00:00',NULL,NULL,'2026-04-08 02:00:00');
INSERT INTO tb_voucher_order VALUES (1027,3,10,3,2,'2026-04-23 02:00:00','2026-05-14 02:00:00','2026-04-19 02:00:00',NULL,'2026-04-23 02:00:00');
INSERT INTO tb_voucher_order VALUES (1028,10,10,3,6,'2026-05-09 02:00:00','2026-05-08 02:00:00',NULL,'2026-05-07 02:00:00','2026-05-09 02:00:00');

DROP TABLE IF EXISTS `tb_sign`;
CREATE TABLE `tb_sign` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '用户id',
  `year` year NOT NULL COMMENT '签到的年',
  `month` tinyint(2) NOT NULL COMMENT '签到的月',
  `date` date NOT NULL COMMENT '签到的日期',
  `is_backup` tinyint(1) UNSIGNED NULL DEFAULT NULL COMMENT '是否补签',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 100 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_sign VALUES (1,1,2026,5,'2026-05-03',0);
INSERT INTO tb_sign VALUES (2,1,2026,5,'2026-05-04',0);
INSERT INTO tb_sign VALUES (3,1,2026,5,'2026-05-05',0);
INSERT INTO tb_sign VALUES (4,1,2026,5,'2026-05-06',0);
INSERT INTO tb_sign VALUES (5,1,2026,5,'2026-05-07',0);
INSERT INTO tb_sign VALUES (6,1,2026,5,'2026-05-08',0);
INSERT INTO tb_sign VALUES (7,1,2026,5,'2026-05-11',0);
INSERT INTO tb_sign VALUES (8,1,2026,5,'2026-05-12',0);
INSERT INTO tb_sign VALUES (9,1,2026,5,'2026-05-13',1);
INSERT INTO tb_sign VALUES (10,1,2026,4,'2026-04-22',0);
INSERT INTO tb_sign VALUES (11,1,2026,4,'2026-04-23',0);
INSERT INTO tb_sign VALUES (12,1,2026,4,'2026-04-24',0);
INSERT INTO tb_sign VALUES (13,1,2026,4,'2026-04-26',0);
INSERT INTO tb_sign VALUES (14,1,2026,4,'2026-04-30',0);
INSERT INTO tb_sign VALUES (15,2,2026,5,'2026-05-02',0);
INSERT INTO tb_sign VALUES (16,2,2026,5,'2026-05-03',0);
INSERT INTO tb_sign VALUES (17,2,2026,5,'2026-05-04',1);
INSERT INTO tb_sign VALUES (18,2,2026,5,'2026-05-05',0);
INSERT INTO tb_sign VALUES (19,2,2026,5,'2026-05-06',0);
INSERT INTO tb_sign VALUES (20,2,2026,5,'2026-05-07',0);
INSERT INTO tb_sign VALUES (21,2,2026,5,'2026-05-08',0);
INSERT INTO tb_sign VALUES (22,2,2026,5,'2026-05-09',1);
INSERT INTO tb_sign VALUES (23,2,2026,5,'2026-05-10',0);
INSERT INTO tb_sign VALUES (24,2,2026,5,'2026-05-13',0);
INSERT INTO tb_sign VALUES (25,2,2026,5,'2026-05-15',0);
INSERT INTO tb_sign VALUES (26,2,2026,4,'2026-04-20',0);
INSERT INTO tb_sign VALUES (27,2,2026,4,'2026-04-23',0);
INSERT INTO tb_sign VALUES (28,2,2026,4,'2026-04-24',0);
INSERT INTO tb_sign VALUES (29,2,2026,4,'2026-04-27',0);
INSERT INTO tb_sign VALUES (30,2,2026,4,'2026-04-28',0);
INSERT INTO tb_sign VALUES (31,2,2026,4,'2026-04-29',0);
INSERT INTO tb_sign VALUES (32,3,2026,5,'2026-05-01',0);
INSERT INTO tb_sign VALUES (33,3,2026,5,'2026-05-02',0);
INSERT INTO tb_sign VALUES (34,3,2026,5,'2026-05-03',1);
INSERT INTO tb_sign VALUES (35,3,2026,5,'2026-05-06',0);
INSERT INTO tb_sign VALUES (36,3,2026,5,'2026-05-08',0);
INSERT INTO tb_sign VALUES (37,3,2026,5,'2026-05-09',0);
INSERT INTO tb_sign VALUES (38,3,2026,5,'2026-05-10',0);
INSERT INTO tb_sign VALUES (39,3,2026,5,'2026-05-12',0);
INSERT INTO tb_sign VALUES (40,3,2026,5,'2026-05-13',0);
INSERT INTO tb_sign VALUES (41,3,2026,4,'2026-04-21',0);
INSERT INTO tb_sign VALUES (42,3,2026,4,'2026-04-22',0);
INSERT INTO tb_sign VALUES (43,3,2026,4,'2026-04-23',0);
INSERT INTO tb_sign VALUES (44,3,2026,4,'2026-04-24',0);
INSERT INTO tb_sign VALUES (45,3,2026,4,'2026-04-27',0);
INSERT INTO tb_sign VALUES (46,3,2026,4,'2026-04-28',0);
INSERT INTO tb_sign VALUES (47,3,2026,4,'2026-04-29',0);
INSERT INTO tb_sign VALUES (48,5,2026,5,'2026-05-01',0);
INSERT INTO tb_sign VALUES (49,5,2026,5,'2026-05-02',0);
INSERT INTO tb_sign VALUES (50,5,2026,5,'2026-05-05',1);
INSERT INTO tb_sign VALUES (51,5,2026,5,'2026-05-07',0);
INSERT INTO tb_sign VALUES (52,5,2026,5,'2026-05-08',0);
INSERT INTO tb_sign VALUES (53,5,2026,5,'2026-05-09',0);
INSERT INTO tb_sign VALUES (54,5,2026,5,'2026-05-10',0);
INSERT INTO tb_sign VALUES (55,5,2026,5,'2026-05-12',0);
INSERT INTO tb_sign VALUES (56,5,2026,5,'2026-05-13',1);
INSERT INTO tb_sign VALUES (57,5,2026,5,'2026-05-14',0);
INSERT INTO tb_sign VALUES (58,5,2026,5,'2026-05-15',1);
INSERT INTO tb_sign VALUES (59,5,2026,4,'2026-04-21',0);
INSERT INTO tb_sign VALUES (60,5,2026,4,'2026-04-27',0);
INSERT INTO tb_sign VALUES (61,5,2026,4,'2026-04-28',0);
INSERT INTO tb_sign VALUES (62,5,2026,4,'2026-04-29',0);
INSERT INTO tb_sign VALUES (63,7,2026,5,'2026-05-01',0);
INSERT INTO tb_sign VALUES (64,7,2026,5,'2026-05-02',1);
INSERT INTO tb_sign VALUES (65,7,2026,5,'2026-05-03',0);
INSERT INTO tb_sign VALUES (66,7,2026,5,'2026-05-04',0);
INSERT INTO tb_sign VALUES (67,7,2026,5,'2026-05-05',0);
INSERT INTO tb_sign VALUES (68,7,2026,5,'2026-05-06',0);
INSERT INTO tb_sign VALUES (69,7,2026,5,'2026-05-09',0);
INSERT INTO tb_sign VALUES (70,7,2026,5,'2026-05-11',0);
INSERT INTO tb_sign VALUES (71,7,2026,5,'2026-05-12',0);
INSERT INTO tb_sign VALUES (72,7,2026,5,'2026-05-13',0);
INSERT INTO tb_sign VALUES (73,7,2026,5,'2026-05-14',1);
INSERT INTO tb_sign VALUES (74,7,2026,5,'2026-05-15',1);
INSERT INTO tb_sign VALUES (75,7,2026,4,'2026-04-20',0);
INSERT INTO tb_sign VALUES (76,7,2026,4,'2026-04-22',0);
INSERT INTO tb_sign VALUES (77,7,2026,4,'2026-04-24',0);
INSERT INTO tb_sign VALUES (78,7,2026,4,'2026-04-25',0);
INSERT INTO tb_sign VALUES (79,7,2026,4,'2026-04-26',0);
INSERT INTO tb_sign VALUES (80,7,2026,4,'2026-04-27',0);
INSERT INTO tb_sign VALUES (81,7,2026,4,'2026-04-29',0);

DROP TABLE IF EXISTS `tb_shop_review`;
CREATE TABLE `tb_shop_review` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `shop_id` bigint(20) UNSIGNED NOT NULL COMMENT '店铺id',
  `user_id` bigint(20) UNSIGNED NOT NULL COMMENT '用户id',
  `rating` tinyint(1) UNSIGNED NOT NULL COMMENT '评分 1-5',
  `content` varchar(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '评价内容',
  `images` varchar(1024) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '评价图片',
  `liked` int(8) UNSIGNED NULL DEFAULT 0 COMMENT '点赞数',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_shop_id`(`shop_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 500 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Compact;

INSERT INTO tb_shop_review VALUES (1,1,3,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,22,'2026-02-21 02:00:00','2026-02-21 02:00:00');
INSERT INTO tb_shop_review VALUES (2,1,11,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。','https://picsum.photos/seed/review2_0/300/300,https://picsum.photos/seed/review2_1/300/300',35,'2026-03-12 02:00:00','2026-03-12 02:00:00');
INSERT INTO tb_shop_review VALUES (3,1,12,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,4,'2026-05-09 02:00:00','2026-05-09 02:00:00');
INSERT INTO tb_shop_review VALUES (4,2,1,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,12,'2026-03-12 02:00:00','2026-03-12 02:00:00');
INSERT INTO tb_shop_review VALUES (5,2,12,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。',NULL,4,'2026-02-15 02:00:00','2026-02-15 02:00:00');
INSERT INTO tb_shop_review VALUES (6,2,6,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,35,'2026-03-23 02:00:00','2026-03-23 02:00:00');
INSERT INTO tb_shop_review VALUES (7,2,10,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。','https://picsum.photos/seed/review7_0/300/300,https://picsum.photos/seed/review7_1/300/300',8,'2026-03-18 02:00:00','2026-03-18 02:00:00');
INSERT INTO tb_shop_review VALUES (8,2,8,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏','https://picsum.photos/seed/review8_0/300/300,https://picsum.photos/seed/review8_1/300/300,https://picsum.photos/seed/review8_2/300/300',6,'2026-02-15 02:00:00','2026-02-15 02:00:00');
INSERT INTO tb_shop_review VALUES (9,3,11,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。','https://picsum.photos/seed/review9_0/300/300,https://picsum.photos/seed/review9_1/300/300,https://picsum.photos/seed/review9_2/300/300',18,'2026-04-08 02:00:00','2026-04-08 02:00:00');
INSERT INTO tb_shop_review VALUES (10,3,10,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。',NULL,8,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (11,3,2,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,27,'2026-03-06 02:00:00','2026-03-06 02:00:00');
INSERT INTO tb_shop_review VALUES (12,3,4,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。','https://picsum.photos/seed/review12_0/300/300,https://picsum.photos/seed/review12_1/300/300,https://picsum.photos/seed/review12_2/300/300',33,'2026-02-22 02:00:00','2026-02-22 02:00:00');
INSERT INTO tb_shop_review VALUES (13,3,10,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏',NULL,9,'2026-04-29 02:00:00','2026-04-29 02:00:00');
INSERT INTO tb_shop_review VALUES (14,4,9,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,13,'2026-03-20 02:00:00','2026-03-20 02:00:00');
INSERT INTO tb_shop_review VALUES (15,4,7,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。',NULL,3,'2026-03-27 02:00:00','2026-03-27 02:00:00');
INSERT INTO tb_shop_review VALUES (16,4,1,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,21,'2026-04-11 02:00:00','2026-04-11 02:00:00');
INSERT INTO tb_shop_review VALUES (17,4,3,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。',NULL,5,'2026-05-13 02:00:00','2026-05-13 02:00:00');
INSERT INTO tb_shop_review VALUES (18,4,11,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏','https://picsum.photos/seed/review18_0/300/300,https://picsum.photos/seed/review18_1/300/300,https://picsum.photos/seed/review18_2/300/300',4,'2026-05-14 02:00:00','2026-05-14 02:00:00');
INSERT INTO tb_shop_review VALUES (19,5,5,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。','https://picsum.photos/seed/review19_0/300/300,https://picsum.photos/seed/review19_1/300/300',0,'2026-04-05 02:00:00','2026-04-05 02:00:00');
INSERT INTO tb_shop_review VALUES (20,5,9,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。',NULL,14,'2026-05-14 02:00:00','2026-05-14 02:00:00');
INSERT INTO tb_shop_review VALUES (21,5,2,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,35,'2026-04-14 02:00:00','2026-04-14 02:00:00');
INSERT INTO tb_shop_review VALUES (22,5,8,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。',NULL,35,'2026-04-11 02:00:00','2026-04-11 02:00:00');
INSERT INTO tb_shop_review VALUES (23,6,11,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,17,'2026-03-24 02:00:00','2026-03-24 02:00:00');
INSERT INTO tb_shop_review VALUES (24,6,3,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。','https://picsum.photos/seed/review24_0/300/300,https://picsum.photos/seed/review24_1/300/300,https://picsum.photos/seed/review24_2/300/300',12,'2026-04-22 02:00:00','2026-04-22 02:00:00');
INSERT INTO tb_shop_review VALUES (25,6,2,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,8,'2026-03-21 02:00:00','2026-03-21 02:00:00');
INSERT INTO tb_shop_review VALUES (26,6,7,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。',NULL,13,'2026-02-16 02:00:00','2026-02-16 02:00:00');
INSERT INTO tb_shop_review VALUES (27,6,6,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏',NULL,19,'2026-02-24 02:00:00','2026-02-24 02:00:00');
INSERT INTO tb_shop_review VALUES (28,6,8,4,'工作日中午来的，人不是很多。点了几道推荐菜，味道都还可以。价格适中，适合当工作餐。就是停车位有点难找。',NULL,15,'2026-05-08 02:00:00','2026-05-08 02:00:00');
INSERT INTO tb_shop_review VALUES (29,7,10,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。','https://picsum.photos/seed/review29_0/300/300,https://picsum.photos/seed/review29_1/300/300',28,'2026-02-23 02:00:00','2026-02-23 02:00:00');
INSERT INTO tb_shop_review VALUES (30,7,2,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。','https://picsum.photos/seed/review30_0/300/300',10,'2026-03-28 02:00:00','2026-03-28 02:00:00');
INSERT INTO tb_shop_review VALUES (31,7,6,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,24,'2026-03-15 02:00:00','2026-03-15 02:00:00');
INSERT INTO tb_shop_review VALUES (32,7,4,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。',NULL,19,'2026-03-02 02:00:00','2026-03-02 02:00:00');
INSERT INTO tb_shop_review VALUES (33,7,5,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏',NULL,20,'2026-04-02 02:00:00','2026-04-02 02:00:00');
INSERT INTO tb_shop_review VALUES (34,7,11,4,'工作日中午来的，人不是很多。点了几道推荐菜，味道都还可以。价格适中，适合当工作餐。就是停车位有点难找。',NULL,14,'2026-04-03 02:00:00','2026-04-03 02:00:00');
INSERT INTO tb_shop_review VALUES (35,8,3,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。','https://picsum.photos/seed/review35_0/300/300',9,'2026-03-27 02:00:00','2026-03-27 02:00:00');
INSERT INTO tb_shop_review VALUES (36,8,6,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。','https://picsum.photos/seed/review36_0/300/300,https://picsum.photos/seed/review36_1/300/300',28,'2026-03-08 02:00:00','2026-03-08 02:00:00');
INSERT INTO tb_shop_review VALUES (37,8,10,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,9,'2026-03-30 02:00:00','2026-03-30 02:00:00');
INSERT INTO tb_shop_review VALUES (38,8,1,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。','https://picsum.photos/seed/review38_0/300/300,https://picsum.photos/seed/review38_1/300/300',28,'2026-03-08 02:00:00','2026-03-08 02:00:00');
INSERT INTO tb_shop_review VALUES (39,8,7,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏','https://picsum.photos/seed/review39_0/300/300',14,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (40,8,12,4,'工作日中午来的，人不是很多。点了几道推荐菜，味道都还可以。价格适中，适合当工作餐。就是停车位有点难找。',NULL,25,'2026-04-09 02:00:00','2026-04-09 02:00:00');
INSERT INTO tb_shop_review VALUES (41,9,1,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。','https://picsum.photos/seed/review41_0/300/300',3,'2026-02-22 02:00:00','2026-02-22 02:00:00');
INSERT INTO tb_shop_review VALUES (42,9,12,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。',NULL,10,'2026-03-10 02:00:00','2026-03-10 02:00:00');
INSERT INTO tb_shop_review VALUES (43,9,1,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。','https://picsum.photos/seed/review43_0/300/300',21,'2026-05-05 02:00:00','2026-05-05 02:00:00');
INSERT INTO tb_shop_review VALUES (44,10,4,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,23,'2026-04-04 02:00:00','2026-04-04 02:00:00');
INSERT INTO tb_shop_review VALUES (45,10,8,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。','https://picsum.photos/seed/review45_0/300/300',32,'2026-02-21 02:00:00','2026-02-21 02:00:00');
INSERT INTO tb_shop_review VALUES (46,10,7,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。','https://picsum.photos/seed/review46_0/300/300,https://picsum.photos/seed/review46_1/300/300',21,'2026-03-11 02:00:00','2026-03-11 02:00:00');
INSERT INTO tb_shop_review VALUES (47,10,11,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。',NULL,11,'2026-04-06 02:00:00','2026-04-06 02:00:00');
INSERT INTO tb_shop_review VALUES (48,10,9,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏',NULL,31,'2026-04-03 02:00:00','2026-04-03 02:00:00');
INSERT INTO tb_shop_review VALUES (49,11,8,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,25,'2026-02-17 02:00:00','2026-02-17 02:00:00');
INSERT INTO tb_shop_review VALUES (50,11,7,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。','https://picsum.photos/seed/review50_0/300/300,https://picsum.photos/seed/review50_1/300/300',31,'2026-03-22 02:00:00','2026-03-22 02:00:00');
INSERT INTO tb_shop_review VALUES (51,11,4,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,31,'2026-03-12 02:00:00','2026-03-12 02:00:00');
INSERT INTO tb_shop_review VALUES (52,11,1,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。','https://picsum.photos/seed/review52_0/300/300',9,'2026-03-29 02:00:00','2026-03-29 02:00:00');
INSERT INTO tb_shop_review VALUES (53,11,10,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏','https://picsum.photos/seed/review53_0/300/300,https://picsum.photos/seed/review53_1/300/300,https://picsum.photos/seed/review53_2/300/300',12,'2026-03-13 02:00:00','2026-03-13 02:00:00');
INSERT INTO tb_shop_review VALUES (54,12,8,5,'超级好吃！已经是第N次来吃了，每一次都不会让人失望。招牌菜必点，味道一如既往的赞👍 环境也很干净，服务态度很好，上菜速度快。',NULL,25,'2026-04-20 02:00:00','2026-04-20 02:00:00');
INSERT INTO tb_shop_review VALUES (55,12,9,5,'朋友推荐来的，果然名不虚传！菜品新鲜，口味正宗，价格也很亲民。特别推荐他们家的招牌，真的绝了😋 下次还会带家人来。',NULL,31,'2026-02-27 02:00:00','2026-02-27 02:00:00');
INSERT INTO tb_shop_review VALUES (56,12,12,4,'味道确实不错，分量也很足。就是周末人太多了，排队等了快半小时。建议工作日来，体验会好很多。菜品种类丰富，选择性很多。',NULL,31,'2026-02-28 02:00:00','2026-02-28 02:00:00');
INSERT INTO tb_shop_review VALUES (57,12,6,4,'整体体验还不错，环境挺好的，适合朋友聚餐。菜品基本没有踩雷的，就是个别菜有点偏咸。性价比在杭州算是不错的了。',NULL,29,'2026-04-23 02:00:00','2026-04-23 02:00:00');
INSERT INTO tb_shop_review VALUES (58,12,5,5,'杭州必吃榜上榜餐厅！每次来杭州都要打卡。口味地道，用料实在，服务也很贴心。强烈推荐给外地来的朋友👏','https://picsum.photos/seed/review58_0/300/300',14,'2026-03-24 02:00:00','2026-03-24 02:00:00');
INSERT INTO tb_shop_review VALUES (59,13,7,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！',NULL,10,'2026-03-25 02:00:00','2026-03-25 02:00:00');
INSERT INTO tb_shop_review VALUES (60,13,11,4,'环境不错，包厢装修挺新的。音响效果还可以，就是某些歌的伴奏版本不太好。服务态度挺好的，送餐速度也快。','https://picsum.photos/seed/review60_0/300/300,https://picsum.photos/seed/review60_1/300/300,https://picsum.photos/seed/review60_2/300/300',21,'2026-02-20 02:00:00','2026-02-20 02:00:00');
INSERT INTO tb_shop_review VALUES (61,13,8,5,'经常来的一家KTV，位置好找，停车方便。曲库更新及时，最新最热的歌都有。小吃味道也不错，推荐炸鸡和果盘🍗',NULL,18,'2026-04-26 02:00:00','2026-04-26 02:00:00');
INSERT INTO tb_shop_review VALUES (62,13,12,4,'和朋友一起来的，整体体验不错。包厢够大，我们6个人也不挤。设备比较新，操作界面也简单。就是价格稍微贵了点。','https://picsum.photos/seed/review62_0/300/300,https://picsum.photos/seed/review62_1/300/300',24,'2026-04-14 02:00:00','2026-04-14 02:00:00');
INSERT INTO tb_shop_review VALUES (63,13,6,3,'音响效果一般般，有些歌音质不太好。包厢有点小，四个人就感觉挤了。服务还行，但性价比不是很高。有更好的选择。',NULL,26,'2026-03-18 02:00:00','2026-03-18 02:00:00');
INSERT INTO tb_shop_review VALUES (64,13,1,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！','https://picsum.photos/seed/review64_0/300/300,https://picsum.photos/seed/review64_1/300/300',27,'2026-03-23 02:00:00','2026-03-23 02:00:00');
INSERT INTO tb_shop_review VALUES (65,14,8,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！','https://picsum.photos/seed/review65_0/300/300,https://picsum.photos/seed/review65_1/300/300',2,'2026-04-02 02:00:00','2026-04-02 02:00:00');
INSERT INTO tb_shop_review VALUES (66,14,5,4,'环境不错，包厢装修挺新的。音响效果还可以，就是某些歌的伴奏版本不太好。服务态度挺好的，送餐速度也快。',NULL,31,'2026-03-13 02:00:00','2026-03-13 02:00:00');
INSERT INTO tb_shop_review VALUES (67,14,6,5,'经常来的一家KTV，位置好找，停车方便。曲库更新及时，最新最热的歌都有。小吃味道也不错，推荐炸鸡和果盘🍗',NULL,32,'2026-02-26 02:00:00','2026-02-26 02:00:00');
INSERT INTO tb_shop_review VALUES (68,14,1,4,'和朋友一起来的，整体体验不错。包厢够大，我们6个人也不挤。设备比较新，操作界面也简单。就是价格稍微贵了点。',NULL,26,'2026-04-02 02:00:00','2026-04-02 02:00:00');
INSERT INTO tb_shop_review VALUES (69,14,12,3,'音响效果一般般，有些歌音质不太好。包厢有点小，四个人就感觉挤了。服务还行，但性价比不是很高。有更好的选择。','https://picsum.photos/seed/review69_0/300/300,https://picsum.photos/seed/review69_1/300/300',1,'2026-04-25 02:00:00','2026-04-25 02:00:00');
INSERT INTO tb_shop_review VALUES (70,15,4,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！',NULL,0,'2026-04-17 02:00:00','2026-04-17 02:00:00');
INSERT INTO tb_shop_review VALUES (71,15,8,4,'环境不错，包厢装修挺新的。音响效果还可以，就是某些歌的伴奏版本不太好。服务态度挺好的，送餐速度也快。','https://picsum.photos/seed/review71_0/300/300,https://picsum.photos/seed/review71_1/300/300,https://picsum.photos/seed/review71_2/300/300',12,'2026-04-17 02:00:00','2026-04-17 02:00:00');
INSERT INTO tb_shop_review VALUES (72,15,3,5,'经常来的一家KTV，位置好找，停车方便。曲库更新及时，最新最热的歌都有。小吃味道也不错，推荐炸鸡和果盘🍗',NULL,1,'2026-03-03 02:00:00','2026-03-03 02:00:00');
INSERT INTO tb_shop_review VALUES (73,16,4,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！',NULL,16,'2026-04-08 02:00:00','2026-04-08 02:00:00');
INSERT INTO tb_shop_review VALUES (74,16,5,4,'环境不错，包厢装修挺新的。音响效果还可以，就是某些歌的伴奏版本不太好。服务态度挺好的，送餐速度也快。',NULL,1,'2026-03-20 02:00:00','2026-03-20 02:00:00');
INSERT INTO tb_shop_review VALUES (75,16,11,5,'经常来的一家KTV，位置好找，停车方便。曲库更新及时，最新最热的歌都有。小吃味道也不错，推荐炸鸡和果盘🍗',NULL,14,'2026-03-17 02:00:00','2026-03-17 02:00:00');
INSERT INTO tb_shop_review VALUES (76,16,7,4,'和朋友一起来的，整体体验不错。包厢够大，我们6个人也不挤。设备比较新，操作界面也简单。就是价格稍微贵了点。','https://picsum.photos/seed/review76_0/300/300',22,'2026-03-31 02:00:00','2026-03-31 02:00:00');
INSERT INTO tb_shop_review VALUES (77,17,11,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！','https://picsum.photos/seed/review77_0/300/300,https://picsum.photos/seed/review77_1/300/300,https://picsum.photos/seed/review77_2/300/300',34,'2026-03-05 02:00:00','2026-03-05 02:00:00');
INSERT INTO tb_shop_review VALUES (78,17,12,4,'环境不错，包厢装修挺新的。音响效果还可以，就是某些歌的伴奏版本不太好。服务态度挺好的，送餐速度也快。',NULL,15,'2026-04-03 02:00:00','2026-04-03 02:00:00');
INSERT INTO tb_shop_review VALUES (79,17,9,5,'经常来的一家KTV，位置好找，停车方便。曲库更新及时，最新最热的歌都有。小吃味道也不错，推荐炸鸡和果盘🍗',NULL,25,'2026-03-11 02:00:00','2026-03-11 02:00:00');
INSERT INTO tb_shop_review VALUES (80,17,4,4,'和朋友一起来的，整体体验不错。包厢够大，我们6个人也不挤。设备比较新，操作界面也简单。就是价格稍微贵了点。',NULL,28,'2026-05-14 02:00:00','2026-05-14 02:00:00');
INSERT INTO tb_shop_review VALUES (81,18,8,5,'音质超好！歌单也很全，想唱的歌都有。包厢空间大，沙发舒服，屏幕清晰。性价比很高，团购更划算。下次还来！',NULL,20,'2026-04-16 02:00:00','2026-04-16 02:00:00');
INSERT INTO tb_shop_review VALUES (82,18,9,4,'环境不错，包厢装修挺新的。音响效果还可以，就是某些歌的伴奏版本不太好。服务态度挺好的，送餐速度也快。',NULL,25,'2026-04-21 02:00:00','2026-04-21 02:00:00');
INSERT INTO tb_shop_review VALUES (83,18,2,5,'经常来的一家KTV，位置好找，停车方便。曲库更新及时，最新最热的歌都有。小吃味道也不错，推荐炸鸡和果盘🍗','https://picsum.photos/seed/review83_0/300/300',1,'2026-03-09 02:00:00','2026-03-09 02:00:00');
INSERT INTO tb_shop_review VALUES (84,18,6,4,'和朋友一起来的，整体体验不错。包厢够大，我们6个人也不挤。设备比较新，操作界面也简单。就是价格稍微贵了点。',NULL,2,'2026-03-26 02:00:00','2026-03-26 02:00:00');
INSERT INTO tb_shop_review VALUES (85,19,7,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇','https://picsum.photos/seed/review85_0/300/300',7,'2026-04-09 02:00:00','2026-04-09 02:00:00');
INSERT INTO tb_shop_review VALUES (86,19,8,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。','https://picsum.photos/seed/review86_0/300/300,https://picsum.photos/seed/review86_1/300/300,https://picsum.photos/seed/review86_2/300/300',19,'2026-03-27 02:00:00','2026-03-27 02:00:00');
INSERT INTO tb_shop_review VALUES (87,19,6,5,'回头客了！每次都找Tony老师，技术稳定，从来没让我失望过。店里用的产品也很好，做完头发很顺很亮✨',NULL,33,'2026-05-01 02:00:00','2026-05-01 02:00:00');
INSERT INTO tb_shop_review VALUES (88,19,3,4,'整体还可以，洗头按摩很舒服。剪发效果也不错，就是等待时间有点长，明明预约了还要等。建议加强时间管理。',NULL,16,'2026-04-20 02:00:00','2026-04-20 02:00:00');
INSERT INTO tb_shop_review VALUES (89,19,2,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇','https://picsum.photos/seed/review89_0/300/300,https://picsum.photos/seed/review89_1/300/300',3,'2026-02-16 02:00:00','2026-02-16 02:00:00');
INSERT INTO tb_shop_review VALUES (90,19,12,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。','https://picsum.photos/seed/review90_0/300/300',34,'2026-04-25 02:00:00','2026-04-25 02:00:00');
INSERT INTO tb_shop_review VALUES (91,20,3,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇',NULL,18,'2026-02-16 02:00:00','2026-02-16 02:00:00');
INSERT INTO tb_shop_review VALUES (92,20,8,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。',NULL,15,'2026-04-04 02:00:00','2026-04-04 02:00:00');
INSERT INTO tb_shop_review VALUES (93,20,12,5,'回头客了！每次都找Tony老师，技术稳定，从来没让我失望过。店里用的产品也很好，做完头发很顺很亮✨',NULL,21,'2026-03-17 02:00:00','2026-03-17 02:00:00');
INSERT INTO tb_shop_review VALUES (94,20,5,4,'整体还可以，洗头按摩很舒服。剪发效果也不错，就是等待时间有点长，明明预约了还要等。建议加强时间管理。',NULL,18,'2026-04-14 02:00:00','2026-04-14 02:00:00');
INSERT INTO tb_shop_review VALUES (95,20,9,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇',NULL,33,'2026-05-02 02:00:00','2026-05-02 02:00:00');
INSERT INTO tb_shop_review VALUES (96,20,8,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。','https://picsum.photos/seed/review96_0/300/300,https://picsum.photos/seed/review96_1/300/300,https://picsum.photos/seed/review96_2/300/300',7,'2026-03-03 02:00:00','2026-03-03 02:00:00');
INSERT INTO tb_shop_review VALUES (97,21,7,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇','https://picsum.photos/seed/review97_0/300/300,https://picsum.photos/seed/review97_1/300/300,https://picsum.photos/seed/review97_2/300/300',34,'2026-05-09 02:00:00','2026-05-09 02:00:00');
INSERT INTO tb_shop_review VALUES (98,21,3,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。','https://picsum.photos/seed/review98_0/300/300',23,'2026-04-15 02:00:00','2026-04-15 02:00:00');
INSERT INTO tb_shop_review VALUES (99,21,6,5,'回头客了！每次都找Tony老师，技术稳定，从来没让我失望过。店里用的产品也很好，做完头发很顺很亮✨',NULL,7,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (100,21,4,4,'整体还可以，洗头按摩很舒服。剪发效果也不错，就是等待时间有点长，明明预约了还要等。建议加强时间管理。',NULL,2,'2026-04-04 02:00:00','2026-04-04 02:00:00');
INSERT INTO tb_shop_review VALUES (101,22,5,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇','https://picsum.photos/seed/review101_0/300/300,https://picsum.photos/seed/review101_1/300/300',32,'2026-04-01 02:00:00','2026-04-01 02:00:00');
INSERT INTO tb_shop_review VALUES (102,22,5,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。','https://picsum.photos/seed/review102_0/300/300',27,'2026-05-01 02:00:00','2026-05-01 02:00:00');
INSERT INTO tb_shop_review VALUES (103,22,4,5,'回头客了！每次都找Tony老师，技术稳定，从来没让我失望过。店里用的产品也很好，做完头发很顺很亮✨','https://picsum.photos/seed/review103_0/300/300',8,'2026-04-23 02:00:00','2026-04-23 02:00:00');
INSERT INTO tb_shop_review VALUES (104,23,9,5,'发型师技术超级好！沟通很耐心，会根据脸型和需求给建议。做出来的效果比我想象的还要好，超级满意！已经办了会员卡💇','https://picsum.photos/seed/review104_0/300/300,https://picsum.photos/seed/review104_1/300/300',13,'2026-03-15 02:00:00','2026-03-15 02:00:00');
INSERT INTO tb_shop_review VALUES (105,23,4,4,'第一次来这家，环境很干净舒适。发型师很专业，剪发很细致。价格合理，不会有隐形消费。就是预约有点难，要提前好几天。','https://picsum.photos/seed/review105_0/300/300,https://picsum.photos/seed/review105_1/300/300',25,'2026-02-14 02:00:00','2026-02-14 02:00:00');
INSERT INTO tb_shop_review VALUES (106,23,7,5,'回头客了！每次都找Tony老师，技术稳定，从来没让我失望过。店里用的产品也很好，做完头发很顺很亮✨',NULL,15,'2026-04-17 02:00:00','2026-04-17 02:00:00');
INSERT INTO tb_shop_review VALUES (107,24,6,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪','https://picsum.photos/seed/review107_0/300/300,https://picsum.photos/seed/review107_1/300/300',7,'2026-02-19 02:00:00','2026-02-19 02:00:00');
INSERT INTO tb_shop_review VALUES (108,24,10,4,'环境不错，器材都是新的。高峰期人比较多，需要排队等器械。建议避开下班时间。更衣室很大，这点好评。','https://picsum.photos/seed/review108_0/300/300',8,'2026-04-12 02:00:00','2026-04-12 02:00:00');
INSERT INTO tb_shop_review VALUES (109,24,6,3,'办了月卡来的，整体感觉一般。器材种类还算全，但有些已经有点旧了。教练会推销私教课，有点烦。淋浴水温不太稳定。','https://picsum.photos/seed/review109_0/300/300',23,'2026-03-20 02:00:00','2026-03-20 02:00:00');
INSERT INTO tb_shop_review VALUES (110,24,5,5,'氛围超好的健身房！大家都是认真来锻炼的，不会有那种占着器械玩手机的人。团课也很有意思，瑜伽课老师超温柔🧘',NULL,11,'2026-04-29 02:00:00','2026-04-29 02:00:00');
INSERT INTO tb_shop_review VALUES (111,24,7,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪','https://picsum.photos/seed/review111_0/300/300,https://picsum.photos/seed/review111_1/300/300',19,'2026-05-09 02:00:00','2026-05-09 02:00:00');
INSERT INTO tb_shop_review VALUES (112,24,5,4,'环境不错，器材都是新的。高峰期人比较多，需要排队等器械。建议避开下班时间。更衣室很大，这点好评。',NULL,3,'2026-03-31 02:00:00','2026-03-31 02:00:00');
INSERT INTO tb_shop_review VALUES (113,25,3,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪',NULL,32,'2026-03-20 02:00:00','2026-03-20 02:00:00');
INSERT INTO tb_shop_review VALUES (114,25,11,4,'环境不错，器材都是新的。高峰期人比较多，需要排队等器械。建议避开下班时间。更衣室很大，这点好评。',NULL,23,'2026-03-01 02:00:00','2026-03-01 02:00:00');
INSERT INTO tb_shop_review VALUES (115,25,9,3,'办了月卡来的，整体感觉一般。器材种类还算全，但有些已经有点旧了。教练会推销私教课，有点烦。淋浴水温不太稳定。','https://picsum.photos/seed/review115_0/300/300',23,'2026-02-17 02:00:00','2026-02-17 02:00:00');
INSERT INTO tb_shop_review VALUES (116,25,4,5,'氛围超好的健身房！大家都是认真来锻炼的，不会有那种占着器械玩手机的人。团课也很有意思，瑜伽课老师超温柔🧘','https://picsum.photos/seed/review116_0/300/300',12,'2026-05-09 02:00:00','2026-05-09 02:00:00');
INSERT INTO tb_shop_review VALUES (117,26,9,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪','https://picsum.photos/seed/review117_0/300/300,https://picsum.photos/seed/review117_1/300/300,https://picsum.photos/seed/review117_2/300/300',5,'2026-02-22 02:00:00','2026-02-22 02:00:00');
INSERT INTO tb_shop_review VALUES (118,26,4,4,'环境不错，器材都是新的。高峰期人比较多，需要排队等器械。建议避开下班时间。更衣室很大，这点好评。',NULL,3,'2026-02-15 02:00:00','2026-02-15 02:00:00');
INSERT INTO tb_shop_review VALUES (119,26,8,3,'办了月卡来的，整体感觉一般。器材种类还算全，但有些已经有点旧了。教练会推销私教课，有点烦。淋浴水温不太稳定。','https://picsum.photos/seed/review119_0/300/300,https://picsum.photos/seed/review119_1/300/300,https://picsum.photos/seed/review119_2/300/300',10,'2026-04-13 02:00:00','2026-04-13 02:00:00');
INSERT INTO tb_shop_review VALUES (120,27,1,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪','https://picsum.photos/seed/review120_0/300/300,https://picsum.photos/seed/review120_1/300/300,https://picsum.photos/seed/review120_2/300/300',13,'2026-03-10 02:00:00','2026-03-10 02:00:00');
INSERT INTO tb_shop_review VALUES (121,27,5,4,'环境不错，器材都是新的。高峰期人比较多，需要排队等器械。建议避开下班时间。更衣室很大，这点好评。','https://picsum.photos/seed/review121_0/300/300,https://picsum.photos/seed/review121_1/300/300,https://picsum.photos/seed/review121_2/300/300',14,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (122,27,6,3,'办了月卡来的，整体感觉一般。器材种类还算全，但有些已经有点旧了。教练会推销私教课，有点烦。淋浴水温不太稳定。','https://picsum.photos/seed/review122_0/300/300,https://picsum.photos/seed/review122_1/300/300,https://picsum.photos/seed/review122_2/300/300',24,'2026-04-02 02:00:00','2026-04-02 02:00:00');
INSERT INTO tb_shop_review VALUES (123,27,12,5,'氛围超好的健身房！大家都是认真来锻炼的，不会有那种占着器械玩手机的人。团课也很有意思，瑜伽课老师超温柔🧘',NULL,8,'2026-02-23 02:00:00','2026-02-23 02:00:00');
INSERT INTO tb_shop_review VALUES (124,27,10,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪',NULL,26,'2026-03-20 02:00:00','2026-03-20 02:00:00');
INSERT INTO tb_shop_review VALUES (125,28,7,5,'超棒的健身房！器械齐全，环境干净，淋浴间也很整洁。教练很专业，私教课效果明显。已经坚持来了三个月了💪','https://picsum.photos/seed/review125_0/300/300,https://picsum.photos/seed/review125_1/300/300,https://picsum.photos/seed/review125_2/300/300',17,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (126,28,10,4,'环境不错，器材都是新的。高峰期人比较多，需要排队等器械。建议避开下班时间。更衣室很大，这点好评。',NULL,14,'2026-03-20 02:00:00','2026-03-20 02:00:00');
INSERT INTO tb_shop_review VALUES (127,28,5,3,'办了月卡来的，整体感觉一般。器材种类还算全，但有些已经有点旧了。教练会推销私教课，有点烦。淋浴水温不太稳定。',NULL,22,'2026-04-04 02:00:00','2026-04-04 02:00:00');
INSERT INTO tb_shop_review VALUES (128,29,12,5,'手法太专业了！技师很懂穴位，按完浑身轻松。环境也很舒适，灯光音乐都让人很放松。已经推荐给好几个朋友了。',NULL,27,'2026-05-02 02:00:00','2026-05-02 02:00:00');
INSERT INTO tb_shop_review VALUES (129,29,3,4,'体验不错，技师手法到位，力度可以随时调整。房间很干净，一次性的用品也很齐全。就是周末价格贵了点。',NULL,0,'2026-04-22 02:00:00','2026-04-22 02:00:00');
INSERT INTO tb_shop_review VALUES (130,29,9,5,'经常来的一家足疗店，技师都很专业，不会偷懒。按完脚整个人都轻快了。服务态度也很好，还会提供小点心🍵',NULL,10,'2026-04-28 02:00:00','2026-04-28 02:00:00');
INSERT INTO tb_shop_review VALUES (131,30,1,5,'手法太专业了！技师很懂穴位，按完浑身轻松。环境也很舒适，灯光音乐都让人很放松。已经推荐给好几个朋友了。','https://picsum.photos/seed/review131_0/300/300,https://picsum.photos/seed/review131_1/300/300',13,'2026-03-05 02:00:00','2026-03-05 02:00:00');
INSERT INTO tb_shop_review VALUES (132,30,12,4,'体验不错，技师手法到位，力度可以随时调整。房间很干净，一次性的用品也很齐全。就是周末价格贵了点。','https://picsum.photos/seed/review132_0/300/300',35,'2026-03-21 02:00:00','2026-03-21 02:00:00');
INSERT INTO tb_shop_review VALUES (133,30,6,5,'经常来的一家足疗店，技师都很专业，不会偷懒。按完脚整个人都轻快了。服务态度也很好，还会提供小点心🍵',NULL,31,'2026-03-28 02:00:00','2026-03-28 02:00:00');
INSERT INTO tb_shop_review VALUES (134,30,2,4,'整体还可以，环境挺好的。技师手法偏重，喜欢力道大的会很合适。我比较怕疼所以有点受不了😅 但朋友说很舒服。','https://picsum.photos/seed/review134_0/300/300,https://picsum.photos/seed/review134_1/300/300,https://picsum.photos/seed/review134_2/300/300',6,'2026-02-22 02:00:00','2026-02-22 02:00:00');
INSERT INTO tb_shop_review VALUES (135,31,10,5,'手法太专业了！技师很懂穴位，按完浑身轻松。环境也很舒适，灯光音乐都让人很放松。已经推荐给好几个朋友了。',NULL,11,'2026-02-22 02:00:00','2026-02-22 02:00:00');
INSERT INTO tb_shop_review VALUES (136,31,7,4,'体验不错，技师手法到位，力度可以随时调整。房间很干净，一次性的用品也很齐全。就是周末价格贵了点。','https://picsum.photos/seed/review136_0/300/300,https://picsum.photos/seed/review136_1/300/300',31,'2026-04-06 02:00:00','2026-04-06 02:00:00');
INSERT INTO tb_shop_review VALUES (137,31,12,5,'经常来的一家足疗店，技师都很专业，不会偷懒。按完脚整个人都轻快了。服务态度也很好，还会提供小点心🍵',NULL,26,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (138,31,1,4,'整体还可以，环境挺好的。技师手法偏重，喜欢力道大的会很合适。我比较怕疼所以有点受不了😅 但朋友说很舒服。',NULL,9,'2026-02-17 02:00:00','2026-02-17 02:00:00');
INSERT INTO tb_shop_review VALUES (139,31,4,5,'手法太专业了！技师很懂穴位，按完浑身轻松。环境也很舒适，灯光音乐都让人很放松。已经推荐给好几个朋友了。',NULL,35,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (140,32,7,5,'手法太专业了！技师很懂穴位，按完浑身轻松。环境也很舒适，灯光音乐都让人很放松。已经推荐给好几个朋友了。',NULL,10,'2026-03-30 02:00:00','2026-03-30 02:00:00');
INSERT INTO tb_shop_review VALUES (141,32,5,4,'体验不错，技师手法到位，力度可以随时调整。房间很干净，一次性的用品也很齐全。就是周末价格贵了点。','https://picsum.photos/seed/review141_0/300/300,https://picsum.photos/seed/review141_1/300/300,https://picsum.photos/seed/review141_2/300/300',30,'2026-04-07 02:00:00','2026-04-07 02:00:00');
INSERT INTO tb_shop_review VALUES (142,32,9,5,'经常来的一家足疗店，技师都很专业，不会偷懒。按完脚整个人都轻快了。服务态度也很好，还会提供小点心🍵','https://picsum.photos/seed/review142_0/300/300,https://picsum.photos/seed/review142_1/300/300',28,'2026-02-28 02:00:00','2026-02-28 02:00:00');
INSERT INTO tb_shop_review VALUES (143,32,8,4,'整体还可以，环境挺好的。技师手法偏重，喜欢力道大的会很合适。我比较怕疼所以有点受不了😅 但朋友说很舒服。','https://picsum.photos/seed/review143_0/300/300',2,'2026-04-19 02:00:00','2026-04-19 02:00:00');
INSERT INTO tb_shop_review VALUES (144,33,9,5,'手法太专业了！技师很懂穴位，按完浑身轻松。环境也很舒适，灯光音乐都让人很放松。已经推荐给好几个朋友了。','https://picsum.photos/seed/review144_0/300/300,https://picsum.photos/seed/review144_1/300/300,https://picsum.photos/seed/review144_2/300/300',6,'2026-04-09 02:00:00','2026-04-09 02:00:00');
INSERT INTO tb_shop_review VALUES (145,33,12,4,'体验不错，技师手法到位，力度可以随时调整。房间很干净，一次性的用品也很齐全。就是周末价格贵了点。',NULL,13,'2026-04-20 02:00:00','2026-04-20 02:00:00');
INSERT INTO tb_shop_review VALUES (146,33,6,5,'经常来的一家足疗店，技师都很专业，不会偷懒。按完脚整个人都轻快了。服务态度也很好，还会提供小点心🍵',NULL,0,'2026-03-16 02:00:00','2026-03-16 02:00:00');
INSERT INTO tb_shop_review VALUES (147,33,11,4,'整体还可以，环境挺好的。技师手法偏重，喜欢力道大的会很合适。我比较怕疼所以有点受不了😅 但朋友说很舒服。',NULL,9,'2026-03-21 02:00:00','2026-03-21 02:00:00');
INSERT INTO tb_shop_review VALUES (148,34,5,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！',NULL,21,'2026-04-27 02:00:00','2026-04-27 02:00:00');
INSERT INTO tb_shop_review VALUES (149,34,6,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。',NULL,26,'2026-03-19 02:00:00','2026-03-19 02:00:00');
INSERT INTO tb_shop_review VALUES (150,34,12,5,'杭州最好的SPA馆！环境、服务、技术都是一流的。每次来都是一种享受✨ 虽然价格不便宜，但绝对物超所值。','https://picsum.photos/seed/review150_0/300/300,https://picsum.photos/seed/review150_1/300/300,https://picsum.photos/seed/review150_2/300/300',12,'2026-04-12 02:00:00','2026-04-12 02:00:00');
INSERT INTO tb_shop_review VALUES (151,34,8,3,'环境确实好，但效果一般。做完感觉和没做差别不大，可能是期望太高了。价格偏贵，性价比不高。不会再来。','https://picsum.photos/seed/review151_0/300/300',24,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (152,35,7,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！','https://picsum.photos/seed/review152_0/300/300,https://picsum.photos/seed/review152_1/300/300,https://picsum.photos/seed/review152_2/300/300',8,'2026-04-03 02:00:00','2026-04-03 02:00:00');
INSERT INTO tb_shop_review VALUES (153,35,6,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。',NULL,26,'2026-03-25 02:00:00','2026-03-25 02:00:00');
INSERT INTO tb_shop_review VALUES (154,35,7,5,'杭州最好的SPA馆！环境、服务、技术都是一流的。每次来都是一种享受✨ 虽然价格不便宜，但绝对物超所值。',NULL,30,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (155,35,11,3,'环境确实好，但效果一般。做完感觉和没做差别不大，可能是期望太高了。价格偏贵，性价比不高。不会再来。',NULL,28,'2026-03-06 02:00:00','2026-03-06 02:00:00');
INSERT INTO tb_shop_review VALUES (156,35,9,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！',NULL,11,'2026-04-03 02:00:00','2026-04-03 02:00:00');
INSERT INTO tb_shop_review VALUES (157,35,5,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。',NULL,35,'2026-04-24 02:00:00','2026-04-24 02:00:00');
INSERT INTO tb_shop_review VALUES (158,36,4,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！','https://picsum.photos/seed/review158_0/300/300',31,'2026-02-17 02:00:00','2026-02-17 02:00:00');
INSERT INTO tb_shop_review VALUES (159,36,1,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。',NULL,12,'2026-05-08 02:00:00','2026-05-08 02:00:00');
INSERT INTO tb_shop_review VALUES (160,36,11,5,'杭州最好的SPA馆！环境、服务、技术都是一流的。每次来都是一种享受✨ 虽然价格不便宜，但绝对物超所值。',NULL,3,'2026-03-06 02:00:00','2026-03-06 02:00:00');
INSERT INTO tb_shop_review VALUES (161,36,3,3,'环境确实好，但效果一般。做完感觉和没做差别不大，可能是期望太高了。价格偏贵，性价比不高。不会再来。',NULL,3,'2026-05-12 02:00:00','2026-05-12 02:00:00');
INSERT INTO tb_shop_review VALUES (162,36,12,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！','https://picsum.photos/seed/review162_0/300/300',2,'2026-03-07 02:00:00','2026-03-07 02:00:00');
INSERT INTO tb_shop_review VALUES (163,37,8,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！','https://picsum.photos/seed/review163_0/300/300,https://picsum.photos/seed/review163_1/300/300,https://picsum.photos/seed/review163_2/300/300',32,'2026-03-06 02:00:00','2026-03-06 02:00:00');
INSERT INTO tb_shop_review VALUES (164,37,10,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。','https://picsum.photos/seed/review164_0/300/300',13,'2026-04-01 02:00:00','2026-04-01 02:00:00');
INSERT INTO tb_shop_review VALUES (165,37,12,5,'杭州最好的SPA馆！环境、服务、技术都是一流的。每次来都是一种享受✨ 虽然价格不便宜，但绝对物超所值。',NULL,10,'2026-05-10 02:00:00','2026-05-10 02:00:00');
INSERT INTO tb_shop_review VALUES (166,37,1,3,'环境确实好，但效果一般。做完感觉和没做差别不大，可能是期望太高了。价格偏贵，性价比不高。不会再来。','https://picsum.photos/seed/review166_0/300/300,https://picsum.photos/seed/review166_1/300/300',9,'2026-04-26 02:00:00','2026-04-26 02:00:00');
INSERT INTO tb_shop_review VALUES (167,37,2,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！',NULL,17,'2026-03-12 02:00:00','2026-03-12 02:00:00');
INSERT INTO tb_shop_review VALUES (168,37,6,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。',NULL,12,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (169,38,2,5,'环境太美了！一进门就感觉整个人都放松下来了。美容师手法温柔专业，用的产品也很好。做完皮肤明显变好，超级推荐！',NULL,11,'2026-04-29 02:00:00','2026-04-29 02:00:00');
INSERT INTO tb_shop_review VALUES (170,38,7,4,'朋友推荐的店，整体体验不错。项目选择多，价格也透明。做的面部护理很舒服，效果也挺好的。就是不太好停车。','https://picsum.photos/seed/review170_0/300/300',29,'2026-04-13 02:00:00','2026-04-13 02:00:00');
INSERT INTO tb_shop_review VALUES (171,38,3,5,'杭州最好的SPA馆！环境、服务、技术都是一流的。每次来都是一种享受✨ 虽然价格不便宜，但绝对物超所值。',NULL,18,'2026-04-22 02:00:00','2026-04-22 02:00:00');
INSERT INTO tb_shop_review VALUES (172,39,9,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶',NULL,30,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (173,39,2,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。','https://picsum.photos/seed/review173_0/300/300,https://picsum.photos/seed/review173_1/300/300,https://picsum.photos/seed/review173_2/300/300',21,'2026-05-04 02:00:00','2026-05-04 02:00:00');
INSERT INTO tb_shop_review VALUES (174,39,4,5,'已经是第三次来了！宝宝每次来都超开心。环境很安全，地面都是软的，不用担心摔伤。停车也方便，适合带孩子来放电⚡',NULL,15,'2026-04-15 02:00:00','2026-04-15 02:00:00');
INSERT INTO tb_shop_review VALUES (175,39,12,4,'挺好的亲子乐园，价格合理。工作人员很有耐心，会和小朋友互动。就是有些区域需要排队，建议工作日来体验更好。','https://picsum.photos/seed/review175_0/300/300,https://picsum.photos/seed/review175_1/300/300',17,'2026-04-21 02:00:00','2026-04-21 02:00:00');
INSERT INTO tb_shop_review VALUES (176,40,3,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶','https://picsum.photos/seed/review176_0/300/300,https://picsum.photos/seed/review176_1/300/300',13,'2026-02-21 02:00:00','2026-02-21 02:00:00');
INSERT INTO tb_shop_review VALUES (177,40,10,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。','https://picsum.photos/seed/review177_0/300/300,https://picsum.photos/seed/review177_1/300/300,https://picsum.photos/seed/review177_2/300/300',32,'2026-02-17 02:00:00','2026-02-17 02:00:00');
INSERT INTO tb_shop_review VALUES (178,40,10,5,'已经是第三次来了！宝宝每次来都超开心。环境很安全，地面都是软的，不用担心摔伤。停车也方便，适合带孩子来放电⚡','https://picsum.photos/seed/review178_0/300/300,https://picsum.photos/seed/review178_1/300/300',23,'2026-02-26 02:00:00','2026-02-26 02:00:00');
INSERT INTO tb_shop_review VALUES (179,40,12,4,'挺好的亲子乐园，价格合理。工作人员很有耐心，会和小朋友互动。就是有些区域需要排队，建议工作日来体验更好。',NULL,22,'2026-03-10 02:00:00','2026-03-10 02:00:00');
INSERT INTO tb_shop_review VALUES (180,41,5,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶',NULL,24,'2026-03-25 02:00:00','2026-03-25 02:00:00');
INSERT INTO tb_shop_review VALUES (181,41,9,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。',NULL,28,'2026-04-13 02:00:00','2026-04-13 02:00:00');
INSERT INTO tb_shop_review VALUES (182,41,6,5,'已经是第三次来了！宝宝每次来都超开心。环境很安全，地面都是软的，不用担心摔伤。停车也方便，适合带孩子来放电⚡',NULL,2,'2026-04-19 02:00:00','2026-04-19 02:00:00');
INSERT INTO tb_shop_review VALUES (183,41,8,4,'挺好的亲子乐园，价格合理。工作人员很有耐心，会和小朋友互动。就是有些区域需要排队，建议工作日来体验更好。','https://picsum.photos/seed/review183_0/300/300',4,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (184,41,11,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶','https://picsum.photos/seed/review184_0/300/300',20,'2026-04-19 02:00:00','2026-04-19 02:00:00');
INSERT INTO tb_shop_review VALUES (185,41,4,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。','https://picsum.photos/seed/review185_0/300/300,https://picsum.photos/seed/review185_1/300/300',34,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (186,42,6,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶',NULL,30,'2026-03-13 02:00:00','2026-03-13 02:00:00');
INSERT INTO tb_shop_review VALUES (187,42,3,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。',NULL,14,'2026-04-17 02:00:00','2026-04-17 02:00:00');
INSERT INTO tb_shop_review VALUES (188,42,2,5,'已经是第三次来了！宝宝每次来都超开心。环境很安全，地面都是软的，不用担心摔伤。停车也方便，适合带孩子来放电⚡',NULL,22,'2026-04-22 02:00:00','2026-04-22 02:00:00');
INSERT INTO tb_shop_review VALUES (189,42,12,4,'挺好的亲子乐园，价格合理。工作人员很有耐心，会和小朋友互动。就是有些区域需要排队，建议工作日来体验更好。',NULL,25,'2026-03-16 02:00:00','2026-03-16 02:00:00');
INSERT INTO tb_shop_review VALUES (190,42,11,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶','https://picsum.photos/seed/review190_0/300/300,https://picsum.photos/seed/review190_1/300/300,https://picsum.photos/seed/review190_2/300/300',32,'2026-04-28 02:00:00','2026-04-28 02:00:00');
INSERT INTO tb_shop_review VALUES (191,42,9,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。','https://picsum.photos/seed/review191_0/300/300,https://picsum.photos/seed/review191_1/300/300',0,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (192,43,3,5,'孩子玩疯了！乐园很大很干净，安全措施做得也很好。工作人员很负责，会时刻关注小朋友的安全。家长有休息区，很贴心👶',NULL,19,'2026-04-24 02:00:00','2026-04-24 02:00:00');
INSERT INTO tb_shop_review VALUES (193,43,9,4,'周末带孩子来的，人不少但不算拥挤。项目挺丰富的，孩子玩了一下午都不愿意走。卫生条件不错，就是餐饮选择少了点。','https://picsum.photos/seed/review193_0/300/300,https://picsum.photos/seed/review193_1/300/300',3,'2026-03-10 02:00:00','2026-03-10 02:00:00');
INSERT INTO tb_shop_review VALUES (194,43,1,5,'已经是第三次来了！宝宝每次来都超开心。环境很安全，地面都是软的，不用担心摔伤。停车也方便，适合带孩子来放电⚡',NULL,11,'2026-05-03 02:00:00','2026-05-03 02:00:00');
INSERT INTO tb_shop_review VALUES (195,44,2,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸','https://picsum.photos/seed/review195_0/300/300',27,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (196,44,3,4,'环境很有格调，不太吵，适合聊天。鸡尾酒做得很好喝，价格也合理。就是位置有点隐蔽，第一次来不太好找。','https://picsum.photos/seed/review196_0/300/300,https://picsum.photos/seed/review196_1/300/300',33,'2026-03-12 02:00:00','2026-03-12 02:00:00');
INSERT INTO tb_shop_review VALUES (197,44,11,5,'杭州最爱的酒吧没有之一！每次来都有惊喜。调酒师很有创意，特调鸡尾酒超级好喝。服务也很贴心，会记住老客人的喜好🥂','https://picsum.photos/seed/review197_0/300/300',14,'2026-03-18 02:00:00','2026-03-18 02:00:00');
INSERT INTO tb_shop_review VALUES (198,44,9,3,'周五晚上去的，太吵了，说话基本靠吼。酒的价格偏贵，性价比一般。装修还不错，但不会再特意来了。',NULL,29,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (199,45,11,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸',NULL,24,'2026-03-04 02:00:00','2026-03-04 02:00:00');
INSERT INTO tb_shop_review VALUES (200,45,4,4,'环境很有格调，不太吵，适合聊天。鸡尾酒做得很好喝，价格也合理。就是位置有点隐蔽，第一次来不太好找。',NULL,3,'2026-04-17 02:00:00','2026-04-17 02:00:00');
INSERT INTO tb_shop_review VALUES (201,45,12,5,'杭州最爱的酒吧没有之一！每次来都有惊喜。调酒师很有创意，特调鸡尾酒超级好喝。服务也很贴心，会记住老客人的喜好🥂',NULL,9,'2026-02-27 02:00:00','2026-02-27 02:00:00');
INSERT INTO tb_shop_review VALUES (202,45,10,3,'周五晚上去的，太吵了，说话基本靠吼。酒的价格偏贵，性价比一般。装修还不错，但不会再特意来了。','https://picsum.photos/seed/review202_0/300/300',21,'2026-03-30 02:00:00','2026-03-30 02:00:00');
INSERT INTO tb_shop_review VALUES (203,46,3,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸','https://picsum.photos/seed/review203_0/300/300',21,'2026-04-04 02:00:00','2026-04-04 02:00:00');
INSERT INTO tb_shop_review VALUES (204,46,2,4,'环境很有格调，不太吵，适合聊天。鸡尾酒做得很好喝，价格也合理。就是位置有点隐蔽，第一次来不太好找。','https://picsum.photos/seed/review204_0/300/300',20,'2026-05-12 02:00:00','2026-05-12 02:00:00');
INSERT INTO tb_shop_review VALUES (205,46,6,5,'杭州最爱的酒吧没有之一！每次来都有惊喜。调酒师很有创意，特调鸡尾酒超级好喝。服务也很贴心，会记住老客人的喜好🥂',NULL,0,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (206,46,11,3,'周五晚上去的，太吵了，说话基本靠吼。酒的价格偏贵，性价比一般。装修还不错，但不会再特意来了。',NULL,14,'2026-03-16 02:00:00','2026-03-16 02:00:00');
INSERT INTO tb_shop_review VALUES (207,47,4,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸','https://picsum.photos/seed/review207_0/300/300',13,'2026-04-07 02:00:00','2026-04-07 02:00:00');
INSERT INTO tb_shop_review VALUES (208,47,10,4,'环境很有格调，不太吵，适合聊天。鸡尾酒做得很好喝，价格也合理。就是位置有点隐蔽，第一次来不太好找。','https://picsum.photos/seed/review208_0/300/300,https://picsum.photos/seed/review208_1/300/300',30,'2026-03-16 02:00:00','2026-03-16 02:00:00');
INSERT INTO tb_shop_review VALUES (209,47,4,5,'杭州最爱的酒吧没有之一！每次来都有惊喜。调酒师很有创意，特调鸡尾酒超级好喝。服务也很贴心，会记住老客人的喜好🥂',NULL,12,'2026-02-26 02:00:00','2026-02-26 02:00:00');
INSERT INTO tb_shop_review VALUES (210,47,12,3,'周五晚上去的，太吵了，说话基本靠吼。酒的价格偏贵，性价比一般。装修还不错，但不会再特意来了。',NULL,35,'2026-02-23 02:00:00','2026-02-23 02:00:00');
INSERT INTO tb_shop_review VALUES (211,47,6,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸',NULL,10,'2026-03-03 02:00:00','2026-03-03 02:00:00');
INSERT INTO tb_shop_review VALUES (212,48,3,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸',NULL,13,'2026-04-08 02:00:00','2026-04-08 02:00:00');
INSERT INTO tb_shop_review VALUES (213,48,2,4,'环境很有格调，不太吵，适合聊天。鸡尾酒做得很好喝，价格也合理。就是位置有点隐蔽，第一次来不太好找。','https://picsum.photos/seed/review213_0/300/300,https://picsum.photos/seed/review213_1/300/300,https://picsum.photos/seed/review213_2/300/300',31,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (214,48,7,5,'杭州最爱的酒吧没有之一！每次来都有惊喜。调酒师很有创意，特调鸡尾酒超级好喝。服务也很贴心，会记住老客人的喜好🥂','https://picsum.photos/seed/review214_0/300/300,https://picsum.photos/seed/review214_1/300/300',33,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (215,48,6,3,'周五晚上去的，太吵了，说话基本靠吼。酒的价格偏贵，性价比一般。装修还不错，但不会再特意来了。','https://picsum.photos/seed/review215_0/300/300,https://picsum.photos/seed/review215_1/300/300',33,'2026-04-26 02:00:00','2026-04-26 02:00:00');
INSERT INTO tb_shop_review VALUES (216,48,9,5,'氛围超赞！音乐品味很好，DJ很会带动气氛。酒的种类很多，调酒师技术也不错。很适合周末和朋友来放松🍸','https://picsum.photos/seed/review216_0/300/300,https://picsum.photos/seed/review216_1/300/300',15,'2026-03-22 02:00:00','2026-03-22 02:00:00');
INSERT INTO tb_shop_review VALUES (217,49,12,5,'太好玩了！设施很全，KTV、桌游、台球、电竞什么都有。空间很大，我们20个人完全不挤。老板人也很好，服务周到🎉',NULL,24,'2026-03-31 02:00:00','2026-03-31 02:00:00');
INSERT INTO tb_shop_review VALUES (218,49,1,4,'公司团建来的，大家都玩得很开心。设备齐全，环境干净。自助厨房也很好用。就是音响效果一般般，唱歌体验差点。',NULL,17,'2026-04-09 02:00:00','2026-04-09 02:00:00');
INSERT INTO tb_shop_review VALUES (219,49,10,5,'生日派对在这里办的，超出预期！布置得很好看，游戏设施很丰富。朋友们都说好，下次聚会还选这里🎂','https://picsum.photos/seed/review219_0/300/300,https://picsum.photos/seed/review219_1/300/300,https://picsum.photos/seed/review219_2/300/300',9,'2026-05-04 02:00:00','2026-05-04 02:00:00');
INSERT INTO tb_shop_review VALUES (220,49,2,4,'整体体验不错，适合多人聚会。项目选择多，不会无聊。价格按人头算，还算公道。就是位置偏了一点，开车要导航。','https://picsum.photos/seed/review220_0/300/300,https://picsum.photos/seed/review220_1/300/300,https://picsum.photos/seed/review220_2/300/300',5,'2026-04-13 02:00:00','2026-04-13 02:00:00');
INSERT INTO tb_shop_review VALUES (221,50,3,5,'太好玩了！设施很全，KTV、桌游、台球、电竞什么都有。空间很大，我们20个人完全不挤。老板人也很好，服务周到🎉','https://picsum.photos/seed/review221_0/300/300,https://picsum.photos/seed/review221_1/300/300,https://picsum.photos/seed/review221_2/300/300',12,'2026-03-03 02:00:00','2026-03-03 02:00:00');
INSERT INTO tb_shop_review VALUES (222,50,6,4,'公司团建来的，大家都玩得很开心。设备齐全，环境干净。自助厨房也很好用。就是音响效果一般般，唱歌体验差点。',NULL,25,'2026-04-21 02:00:00','2026-04-21 02:00:00');
INSERT INTO tb_shop_review VALUES (223,50,2,5,'生日派对在这里办的，超出预期！布置得很好看，游戏设施很丰富。朋友们都说好，下次聚会还选这里🎂',NULL,27,'2026-02-17 02:00:00','2026-02-17 02:00:00');
INSERT INTO tb_shop_review VALUES (224,50,4,4,'整体体验不错，适合多人聚会。项目选择多，不会无聊。价格按人头算，还算公道。就是位置偏了一点，开车要导航。',NULL,13,'2026-03-21 02:00:00','2026-03-21 02:00:00');
INSERT INTO tb_shop_review VALUES (225,51,12,5,'太好玩了！设施很全，KTV、桌游、台球、电竞什么都有。空间很大，我们20个人完全不挤。老板人也很好，服务周到🎉','https://picsum.photos/seed/review225_0/300/300,https://picsum.photos/seed/review225_1/300/300',17,'2026-03-04 02:00:00','2026-03-04 02:00:00');
INSERT INTO tb_shop_review VALUES (226,51,3,4,'公司团建来的，大家都玩得很开心。设备齐全，环境干净。自助厨房也很好用。就是音响效果一般般，唱歌体验差点。',NULL,14,'2026-03-04 02:00:00','2026-03-04 02:00:00');
INSERT INTO tb_shop_review VALUES (227,51,7,5,'生日派对在这里办的，超出预期！布置得很好看，游戏设施很丰富。朋友们都说好，下次聚会还选这里🎂',NULL,17,'2026-04-11 02:00:00','2026-04-11 02:00:00');
INSERT INTO tb_shop_review VALUES (228,51,1,4,'整体体验不错，适合多人聚会。项目选择多，不会无聊。价格按人头算，还算公道。就是位置偏了一点，开车要导航。','https://picsum.photos/seed/review228_0/300/300,https://picsum.photos/seed/review228_1/300/300',33,'2026-03-29 02:00:00','2026-03-29 02:00:00');
INSERT INTO tb_shop_review VALUES (229,52,4,5,'太好玩了！设施很全，KTV、桌游、台球、电竞什么都有。空间很大，我们20个人完全不挤。老板人也很好，服务周到🎉','https://picsum.photos/seed/review229_0/300/300',25,'2026-03-19 02:00:00','2026-03-19 02:00:00');
INSERT INTO tb_shop_review VALUES (230,52,7,4,'公司团建来的，大家都玩得很开心。设备齐全，环境干净。自助厨房也很好用。就是音响效果一般般，唱歌体验差点。','https://picsum.photos/seed/review230_0/300/300,https://picsum.photos/seed/review230_1/300/300,https://picsum.photos/seed/review230_2/300/300',0,'2026-03-21 02:00:00','2026-03-21 02:00:00');
INSERT INTO tb_shop_review VALUES (231,52,2,5,'生日派对在这里办的，超出预期！布置得很好看，游戏设施很丰富。朋友们都说好，下次聚会还选这里🎂',NULL,34,'2026-02-20 02:00:00','2026-02-20 02:00:00');
INSERT INTO tb_shop_review VALUES (232,52,11,4,'整体体验不错，适合多人聚会。项目选择多，不会无聊。价格按人头算，还算公道。就是位置偏了一点，开车要导航。',NULL,35,'2026-05-12 02:00:00','2026-05-12 02:00:00');
INSERT INTO tb_shop_review VALUES (233,52,10,5,'太好玩了！设施很全，KTV、桌游、台球、电竞什么都有。空间很大，我们20个人完全不挤。老板人也很好，服务周到🎉',NULL,14,'2026-02-23 02:00:00','2026-02-23 02:00:00');
INSERT INTO tb_shop_review VALUES (234,52,9,4,'公司团建来的，大家都玩得很开心。设备齐全，环境干净。自助厨房也很好用。就是音响效果一般般，唱歌体验差点。','https://picsum.photos/seed/review234_0/300/300',9,'2026-04-23 02:00:00','2026-04-23 02:00:00');
INSERT INTO tb_shop_review VALUES (235,53,9,5,'太好玩了！设施很全，KTV、桌游、台球、电竞什么都有。空间很大，我们20个人完全不挤。老板人也很好，服务周到🎉',NULL,8,'2026-04-23 02:00:00','2026-04-23 02:00:00');
INSERT INTO tb_shop_review VALUES (236,53,12,4,'公司团建来的，大家都玩得很开心。设备齐全，环境干净。自助厨房也很好用。就是音响效果一般般，唱歌体验差点。','https://picsum.photos/seed/review236_0/300/300,https://picsum.photos/seed/review236_1/300/300,https://picsum.photos/seed/review236_2/300/300',21,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (237,53,8,5,'生日派对在这里办的，超出预期！布置得很好看，游戏设施很丰富。朋友们都说好，下次聚会还选这里🎂',NULL,0,'2026-02-25 02:00:00','2026-02-25 02:00:00');
INSERT INTO tb_shop_review VALUES (238,54,2,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅',NULL,3,'2026-04-18 02:00:00','2026-04-18 02:00:00');
INSERT INTO tb_shop_review VALUES (239,54,2,4,'环境挺干净的，工具都是一次性的很放心。美甲师很有耐心，会反复确认颜色和款式。价格合理，效果也很满意。',NULL,27,'2026-03-23 02:00:00','2026-03-23 02:00:00');
INSERT INTO tb_shop_review VALUES (240,54,10,5,'这家美甲店太赞了！做的款式超级好看，和图片一样。美甲师小姐姐很温柔，全程不会疼。保持时间也很久，性价比高✨',NULL,6,'2026-04-22 02:00:00','2026-04-22 02:00:00');
INSERT INTO tb_shop_review VALUES (241,54,7,3,'款式选择挺多的，但做出来效果和图片差有点大。价格在同类型店里偏贵。服务态度还行，但技术有待提高。',NULL,1,'2026-05-14 02:00:00','2026-05-14 02:00:00');
INSERT INTO tb_shop_review VALUES (242,54,12,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅',NULL,16,'2026-04-10 02:00:00','2026-04-10 02:00:00');
INSERT INTO tb_shop_review VALUES (243,55,1,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅','https://picsum.photos/seed/review243_0/300/300',12,'2026-04-19 02:00:00','2026-04-19 02:00:00');
INSERT INTO tb_shop_review VALUES (244,55,3,4,'环境挺干净的，工具都是一次性的很放心。美甲师很有耐心，会反复确认颜色和款式。价格合理，效果也很满意。',NULL,34,'2026-03-28 02:00:00','2026-03-28 02:00:00');
INSERT INTO tb_shop_review VALUES (245,55,7,5,'这家美甲店太赞了！做的款式超级好看，和图片一样。美甲师小姐姐很温柔，全程不会疼。保持时间也很久，性价比高✨','https://picsum.photos/seed/review245_0/300/300',22,'2026-03-02 02:00:00','2026-03-02 02:00:00');
INSERT INTO tb_shop_review VALUES (246,55,11,3,'款式选择挺多的，但做出来效果和图片差有点大。价格在同类型店里偏贵。服务态度还行，但技术有待提高。','https://picsum.photos/seed/review246_0/300/300,https://picsum.photos/seed/review246_1/300/300',1,'2026-05-12 02:00:00','2026-05-12 02:00:00');
INSERT INTO tb_shop_review VALUES (247,56,6,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅','https://picsum.photos/seed/review247_0/300/300,https://picsum.photos/seed/review247_1/300/300',5,'2026-03-05 02:00:00','2026-03-05 02:00:00');
INSERT INTO tb_shop_review VALUES (248,56,5,4,'环境挺干净的，工具都是一次性的很放心。美甲师很有耐心，会反复确认颜色和款式。价格合理，效果也很满意。',NULL,9,'2026-03-12 02:00:00','2026-03-12 02:00:00');
INSERT INTO tb_shop_review VALUES (249,56,8,5,'这家美甲店太赞了！做的款式超级好看，和图片一样。美甲师小姐姐很温柔，全程不会疼。保持时间也很久，性价比高✨','https://picsum.photos/seed/review249_0/300/300,https://picsum.photos/seed/review249_1/300/300,https://picsum.photos/seed/review249_2/300/300',17,'2026-04-02 02:00:00','2026-04-02 02:00:00');
INSERT INTO tb_shop_review VALUES (250,57,3,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅',NULL,32,'2026-03-22 02:00:00','2026-03-22 02:00:00');
INSERT INTO tb_shop_review VALUES (251,57,1,4,'环境挺干净的，工具都是一次性的很放心。美甲师很有耐心，会反复确认颜色和款式。价格合理，效果也很满意。',NULL,4,'2026-04-04 02:00:00','2026-04-04 02:00:00');
INSERT INTO tb_shop_review VALUES (252,57,8,5,'这家美甲店太赞了！做的款式超级好看，和图片一样。美甲师小姐姐很温柔，全程不会疼。保持时间也很久，性价比高✨','https://picsum.photos/seed/review252_0/300/300,https://picsum.photos/seed/review252_1/300/300,https://picsum.photos/seed/review252_2/300/300',34,'2026-02-21 02:00:00','2026-02-21 02:00:00');
INSERT INTO tb_shop_review VALUES (253,57,5,3,'款式选择挺多的，但做出来效果和图片差有点大。价格在同类型店里偏贵。服务态度还行，但技术有待提高。',NULL,24,'2026-04-09 02:00:00','2026-04-09 02:00:00');
INSERT INTO tb_shop_review VALUES (254,58,12,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅',NULL,9,'2026-02-16 02:00:00','2026-02-16 02:00:00');
INSERT INTO tb_shop_review VALUES (255,58,11,4,'环境挺干净的，工具都是一次性的很放心。美甲师很有耐心，会反复确认颜色和款式。价格合理，效果也很满意。',NULL,33,'2026-02-18 02:00:00','2026-02-18 02:00:00');
INSERT INTO tb_shop_review VALUES (256,58,12,5,'这家美甲店太赞了！做的款式超级好看，和图片一样。美甲师小姐姐很温柔，全程不会疼。保持时间也很久，性价比高✨','https://picsum.photos/seed/review256_0/300/300',11,'2026-03-03 02:00:00','2026-03-03 02:00:00');
INSERT INTO tb_shop_review VALUES (257,58,2,3,'款式选择挺多的，但做出来效果和图片差有点大。价格在同类型店里偏贵。服务态度还行，但技术有待提高。',NULL,7,'2026-03-29 02:00:00','2026-03-29 02:00:00');
INSERT INTO tb_shop_review VALUES (258,58,3,5,'做完美甲心情都变好了！款式超多，美甲师技术很好，画得很精细。用的胶也很好，快一个月了还没掉。已经推荐给姐妹们了💅','https://picsum.photos/seed/review258_0/300/300',1,'2026-04-11 02:00:00','2026-04-11 02:00:00');

SET FOREIGN_KEY_CHECKS = 1;