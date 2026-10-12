"""FishAgent M2 MVP 服务端包.

把 M1 已验证的引擎（坐标转换 / 水域 POI 双路召回 / 网格分片 / 车程精算 / 鱼情规则）
组织为可内测的服务端，并对齐实现红线：

    R1 坐标唯一定义入口 (coord.wgs84_to_gcj02)
    R2 高德 radius 硬校验 (poi.validate_radius)
    R3 密钥仅服务端持有 (config 只读环境变量)
    R4 往返车程分别计算且 <=7200s (route)
    R5 禁钓过滤 (spot_filter, 保守排除)
    R6 AI 生成内容标识 / R8 不播报气象预报 (factors.render_explanation)

对应 Spec/Roadmap.md 第三章 M2 MVP（M2-B01..B14）。
"""

__version__ = "0.2.0-m2"
