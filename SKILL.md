---
name: substation-electrical-design
description: 变电站电气设计技能。根据原始资料、负荷统计和电源条件，生成主接线、短路电流、设备选型与设计报告。运行时只读取最终精简数据库，不依赖脚本内硬编码表。
---

# 变电站电气设计

## 默认数据源

- 默认工作库：`substation_curated.sqlite`

## 数据库规则

1. 设计与选型时，优先读取 `substation_curated.sqlite`。
2. skill 交付内容只保留最终工作库，不保留原始库、清洗脚本或中间导出。
3. 不要在脚本内重新维护设备型号表；常用型号应直接维护在最终数据库中，再由脚本查询。

## 工作流程

### 1. 确认数据库

- 先确认 `substation_curated.sqlite` 可用。

### 2. 收集设计输入

需要至少具备以下信息：

- 电压等级，如 `35/10kV`
- 进出线回路数
- 主变容量与台数
- 最大负荷、I/II 类负荷、站用电负荷
- 系统短路水平或短路电流
- 气象、海拔、污秽等级、接地方式等边界条件

### 3. 负荷与容量计算

使用 `scripts/calc_load.py`：

- 计算最大综合负荷
- 推荐主变容量
- 推荐站用变容量
- 推荐无功补偿容量
- 推荐消弧线圈或接地电阻

### 4. 短路电流计算

使用 `scripts/calc_short_circuit.py`：

**推荐方法：`calc_substation_short_circuit`（多电压等级）**

对于多电压等级变电站（如 35/10kV），必须使用此方法。该方法为每个短路点独立指定电压等级，自动使用正确的基准电流，避免电压等级混淆。同时输出详细的公式链用于报告生成。

```python
sc_calc = get_calculator(base_power=100.0)
sc_result = sc_calc.calc_substation_short_circuit(
    voltage_levels={"35kV": 37.0, "10kV": 10.5},
    fault_points=[
        {
            "name": "d1",
            "voltage_level": "35kV",
            "label": "35kV母线三相短路",
            "impedance_chain": [
                {"name": "系统阻抗", "impedance": z_system, "detail": "X*s=1.33"},
                {"name": "线路阻抗", "impedance": z_line, "detail": "71km"},
            ],
        },
        {
            "name": "d2",
            "voltage_level": "10kV",
            "label": "10kV母线三相短路",
            "impedance_chain": [
                {"name": "系统阻抗", "impedance": z_system, "detail": "X*s=1.33"},
                {"name": "线路阻抗", "impedance": z_line, "detail": "71km"},
                {"name": "变压器阻抗", "impedance": z_transformer, "detail": "uk=7%"},
            ],
        },
    ],
)
```

每个结果包含 `calculation_detail` 字段，记录了完整的阻抗归算、基准电流推导和短路电流计算公式，可直接用于报告：

```python
# 格式化单个短路点的详细计算过程
ShortCircuitCalculator.format_fault_calculation_detail(result)

# 格式化所有短路点的汇总表
ShortCircuitCalculator.format_sc_summary_table(sc_result)
```

**其他方法（单电压等级）：**
- `calc_all_scenarios`: 单电压等级下的全运行方式和故障点自动遍历
- `calc_bus_fault`: 单母线故障计算（基于 Pandapower）
- `calc_network_fault`: 复杂网络故障计算
- `fault_from_xjs` / `fault_from_impedance`: 简单的单点故障计算

### 5. 主接线方案生成

使用 `scripts/generate_main_wiring.py`：

- 根据电压等级、回路数、可靠性要求选择主接线型式
- 匹配数据库中的主变与站用变
- 生成一次设备配置建议

### 6. 设备选型

使用 `scripts/select_equipment.py`：

- 从数据库选择导体、断路器、隔离开关、电流互感器
- 可扩展读取电压互感器、避雷器等设备
- 按额定电压、额定电流、开断能力、热稳定、动稳定等条件筛选

### 7. 设计报告输出

生成 Markdown 报告，建议包含：

1. 摘要
2. 原始资料分析
3. 电气主接线设计
4. 短路电流计算
5. 导体及主要设备选型
6. 防雷与接地
7. 继电保护设计说明
8. 结论与附录

## 主要脚本

- `scripts/equipment_db.py`：统一数据库访问层
- `scripts/calc_load.py`：负荷、主变、站用变、补偿与接地推荐
- `scripts/calc_short_circuit.py`：基于Pandapower的短路电流计算
- `scripts/generate_main_wiring.py`：主接线方案与核心设备配置
- `scripts/select_equipment.py`：数据库驱动的设备选型

## 选型原则

- 断路器：`Un >= Uns`、`In >= Imax`、`Ibreak >= I''`
- 隔离开关：`Un >= Uns`、`In >= Imax`
- 导体：长期允许电流满足运行要求，并结合热稳定校验
- 电流互感器：变比、二次负荷、热稳定和动稳定满足要求
- 主变与站用变：优先在数据库中选取不小于需求值的最小常用型号

## 使用要求

- 设计阶段若需新增型号，直接更新最终数据库，再修改流程调用。
- 如果数据库与脚本输出不一致，以数据库中的设备数据为准。
- 所有新增的常用设备型号应写入最终工作库，以便后续流程复用。

## 脚本调用注意事项

### 编码

- Windows 环境下执行脚本前应设置 UTF-8 输出：
  ```python
  import sys
  if sys.platform == "win32":
      sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  ```

### 短路计算

- `ShortCircuitCalculator` 是唯一有效的计算类（通过 `get_calculator()` 获取）
- **多电压等级变电站必须使用 `calc_substation_short_circuit`**，它会为每个短路点使用正确的基准电流（`Ib = Sb / (√3 × Uav)`），避免电压等级混淆
- `calc_bus_fault()` 内部调用 `calc_network_fault()`，会自动使用 Pandapower 进行母线故障计算
- Pandapower 的 `res_bus_sc` 列名因版本而异，当前版本仅有 `ikss_ka`/`skss_mw`/`rk_ohm`/`xk_ohm`，峰值电流通过 IEC 60909 公式从 R/X 比计算
- 对于简单场景，可使用解析法（`I = Ib / Z_sigma`）直接计算，结果可靠
- 报告中的详细计算过程可直接使用 `format_fault_calculation_detail()` 和 `format_sc_summary_table()` 生成

### 设备选型

- `select_circuit_breaker()` 支持自动升级查找（`auto_upgrade=True`）
- 所有选型方法均返回包含 `checks`、`all_passed`、`passed_check_count` 的结果字典
- 使用 `validate_equipment()` / `validate_bay_equipment()` 生成校验报告

### 完整设计示例

参考 `scripts/design_35kv_substation.py`，这是一个完整的设计计算脚本，覆盖从负荷计算到设备选型再到报告输出的全流程。
