# M1 实测数据目录

本目录存放 **A1–A4 的真实实测原始结果**（由 `prototype/measure_m1.py` 生成）。

> ⚠️ **不得手工编造数字。** 每条指标必须可追溯到一次真实调用记录（呼应立项文档 8.1
> 「分子 / 分母 / 样本量 / 观察窗口 / 测量人」披露要求）。

## 运行方式

```bash
cd prototype
export AMAP_KEY=<你的高德个人认证 Key>      # 服务端持有，严禁下发客户端（R3）

# A4 距离接口能力（先跑，决定 M2 精算方案）
python3 measure_m1.py a4 --lat 30.657 --lng 104.066

# A1 召回率（需真值集）
python3 measure_m1.py a1 --truth fixtures/ground_truth.chengdu.json

# A2 / T07 水域存量（需城市测试点）
python3 measure_m1.py a2 --cities fixtures/cities.json

# A3 配额（需在高德控制台核对绝对额度）
python3 measure_m1.py a3

# 全部
python3 measure_m1.py all --lat 30.657 --lng 104.066 \
    --truth fixtures/ground_truth.chengdu.json --cities fixtures/cities.json
```

无 Key 时可先自检工具链：加 `--dry-run`（使用 mock 合成数据，**结果不可作为实测结论**）。

## 产出

- `a1-<date>.json` / `a2-<date>.json` / `a3-<date>.json` / `a4-<date>.json`：原始结果
- `latest.md`：汇总的 markdown 表格，可直接粘贴回 `../poi-recall.md`、`../route-measurement.md`、
  `../weather-and-quota.md`、`../verification-report.md`

## 与报告文件的对应

| 实测项 | 回填位置 |
|---|---|
| A1 召回率 | `../poi-recall.md` §3 |
| A2 / T07 水域存量 | `../poi-recall.md` §4、`../verification-report.md` §一 |
| A3 配额 | `../weather-and-quota.md` §B.2 / §B.4 |
| A4 接口能力 | `../route-measurement.md` §3、`../verification-report.md` §一 |
| 汇总 | `../verification-report.md` §一 / §二（G1 判定） |
