# Substation Electrical Design

变电站电气设计工具集。根据原始资料、负荷统计和电源条件，实现主接线设计、短路电流计算、设备选型与设计报告生成的自动化流程。

## 功能特性

- **负荷计算**：最大综合负荷、主变容量、站用变容量、无功补偿容量推荐
- **短路电流计算**：基于 Pandapower 的多电压等级短路电流计算，支持详细公式输出
- **主接线设计**：根据电压等级、回路数、可靠性要求自动推荐主接线型式
- **设备选型**：数据库驱动的断路器、隔离开关、电流互感器等设备优选选型
- **报告生成**：自动生成包含完整设计计算的 Markdown 格式设计报告

## 项目结构

```
substation-electrical-design/
├── SKILL.md                      # 技能定义和工作流程
├── skill.yaml                    # 技能配置文件
├── substation_curated.sqlite     # 精简设备数据库
├── scripts/                      # 核心计算脚本
│   ├── equipment_db.py           # 数据库访问层
│   ├── calc_load.py              # 负荷与容量计算
│   ├── calc_short_circuit.py     # 短路电流计算
│   ├── generate_main_wiring.py   # 主接线方案生成
│   ├── select_equipment.py       # 设备选型
│   └── design_35kv_substation.py # 完整设计示例
├── references/                   # 参考文档
│   ├── wiring_types.md           # 主接线类型说明
│   ├── voltage_35kv.md          # 35kV 系统参考
│   ├── voltage_110kv.md         # 110kV 系统参考
│   └── equipment_selection.md    # 设备选型指导
├── assets/                       # 资源文件
│   └── templates/                # 报告模板
└── 35kV变电站电气设计计算报告.md   # 设计报告示例
```

## 快速开始

### 环境要求

```bash
pip install pandas numpy pandapower
```

### Windows 编码设置

在 Windows 环境下运行脚本前，需要设置 UTF-8 编码：

```python
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

### 基本使用

```python
# 1. 设置工作目录
import os
os.chdir("substation-electrical-design/scripts/")

# 2. 初始化计算器
from calc_load import Calculator as LoadCalculator
from calc_short_circuit import get_calculator
from select_equipment import EquipmentSelector

# 3. 执行完整设计流程
# 参考 design_35kv_substation.py 获取完整示例
```

## 工作流程

### 1. 负荷与容量计算

```python
from calc_load import Calculator

calc = Calculator(max_load=5000, class_1_2_load=4000, station_load=100)
calc.calculate_all()
result = calc.get_all_results()
```

### 2. 短路电流计算

```python
from calc_short_circuit import get_calculator

# 初始化计算器
sc_calc = get_calculator(base_power=100.0)

# 多电压等级短路计算
sc_result = sc_calc.calc_substation_short_circuit(
    voltage_levels={"35kV": 37.0, "10kV": 10.5},
    fault_points=[
        {
            "name": "d1",
            "voltage_level": "35kV",
            "label": "35kV母线三相短路",
            "impedance_chain": [
                {"name": "系统阻抗", "impedance": z_system, "detail": "X*s=1.33"},
            ],
        },
    ],
)

# 格式化输出详细计算过程
print(ShortCircuitCalculator.format_fault_calculation_detail(sc_result[0]))
```

### 3. 主接线设计

```python
from generate_main_wiring import MainWiringDesigner

designer = MainWiringDesigner()
config = designer.generate_wiring_config(
    voltage_levels=["35kV", "10kV"],
    incoming_lines={"35kV": 1},
    outgoing_lines={"35kV": 2, "10kV": 6},
    main_transformer_count=2,
)
```

### 4. 设备选型

```python
from select_equipment import EquipmentSelector

selector = EquipmentSelector()

# 选型断路器
breaker = selector.select_circuit_breaker(
    voltage=35.0,
    current=600,
    short_circuit_current=25.0,
    auto_upgrade=True,
)

# 校验设备
validity = selector.validate_equipment(breaker, current=600, sc_current=25.0)
```

## 数据库设计

项目使用精简数据库 `substation_curated.sqlite`，包含以下核心表：

- **导体表**：母线、电缆、硬导体等载流导体规格
- **断路器表**：各电压等级断路器的额定参数
- **隔离开关表**：隔离开关技术参数
- **电流互感器表**：CT 变比、二次负荷等参数
- **主变压器表**：常用主变技术规格
- **站用变压器表**：站用变规格

**重要规则**：
- 设计与选型时，优先读取 `substation_curated.sqlite`
- 不要在脚本内重新维护设备型号表
- 所有新增型号应直接维护在数据库中

## 选型原则

| 设备类型 | 校验条件 |
|---------|---------|
| 断路器 | Un ≥ Uns, In ≥ Imax, Ibreak ≥ I'' |
| 隔离开关 | Un ≥ Uns, In ≥ Imax |
| 导体 | 长期允许电流满足运行 + 热稳定校验 |
| 电流互感器 | 变比、二次负荷、热稳定、动稳定均满足 |
| 主变 | 优先选取不小于需求值的最小常用型号 |

## 技术依赖

- **Python 3.8+**
- **pandas**：数据处理与分析
- **numpy**：数值计算
- **pandapower**：电网仿真与短路计算

## 完整示例

参考 `scripts/design_35kv_substation.py`，该脚本展示了从负荷计算到设备选型再到报告输出的完整设计流程：

```bash
cd substation-electrical-design/scripts/
python design_35kv_substation.py
```

## 参考文档

- `SKILL.md`：详细的技能定义和工作流程说明
- `references/wiring_types.md`：主接线类型与选择原则
- `references/equipment_selection.md`：设备选型技术规范
- `references/voltage_*.md`：各电压等级设计参考

## 许可证

MIT License

## 作者

变电站电气设计技能开发团队
