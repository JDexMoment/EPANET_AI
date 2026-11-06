# Пакет задач для разметки Моделью-Учителем (город: тенино)

**Системная инструкция Учителю:**
> Ты — главный инженер-гидравлик систем водоснабжения (уровня авторов руководства Walski et al. 'Advanced Water Distribution Modeling and Management' и СП 31.13330.2021). Напиши глубокий, живой, профессиональный инженерный ответ для обучения младшей локальной модели EPANET-AI.

ЖЕЛЕЗНЫЕ ПРАВИЛА ДИСТИЛЛЯЦИИ (нарушение бракует пример!):
1. Опирайся ИСКЛЮЧИТЕЛЬНО на переданный JSON `facts_inline`.
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО считать в уме (не вычисляй проценты, разности или суммы, которых нет в JSON) и запрещено писать любые числа, отсутствующие во входном `facts_inline` (разрешены только константы нормативов: 10 м и +4 м на этаж по СП 31.13330.2021, 60 м макс. напор, 0.3 / 1.5 / 3.0 м/с скорости по Walski, 24 ч, 1440 шагов).
3. Обязательно указывай конкретные строковые ID узлов (c*), труб (e*), насосов (p*), кривых (u*, t*) и объясняй физику процессов.
4. Если спрашивают данные, которых нет в `facts_inline` (КПД двигателя, тариф в рублях, остаточный хлор), чётко перечисли недостающие таблицы и НЕ выдумывай оценочных цифр.

---
## Задача 1 (`тенино_teacher_exec_memo_fc356c43b2`)

Вопрос инженера: Подготовь аналитическую записку главному инженеру водоканала по расчёту сети «тенино»: оцени баланс, главные гидравлические риски и очерёдность мероприятий.

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 0,
    "pruned_standby_pumps_count": 0,
    "pruned_zero_consumers_count": 0
  },
  "nodes_overview": {
    "consumer_nodes_count": 214,
    "total_daily_consumption_m3_day": 10931.35,
    "sum_peak_node_demand_m3_h": 618.31,
    "free_pressure_network_min_m": 27.26,
    "free_pressure_network_max_m": 78.47,
    "deficit_nodes_count": 42,
    "excess_pressure_over_60m_nodes_count": 21,
    "floors_distribution": {
      "1_эт": 107,
      "2_эт": 1,
      "3_эт": 2,
      "5_эт": 13,
      "9_эт": 39,
      "10_эт": 40,
      "12_эт": 4,
      "14_эт": 3,
      "17_эт": 5
    }
  },
  "pipes_overview": {
    "pipes_count": 0,
    "total_length_km": 0.0,
    "total_internal_water_volume_m3": 0.0,
    "network_max_velocity_m_s": null,
    "pipes_over_1_5_m_s_count": 0,
    "pipes_over_3_0_m_s_water_hammer_risk_count": 0,
    "stagnant_pipes_under_0_3_m_s_count": 0,
    "reverse_flow_pipes_count": 0,
    "self_loop_topology_pipes_count": 0
  },
  "pumps_overview": {
    "total_pumps_declared": 21,
    "active_pumps_count": 6,
    "standby_off_pumps_count": 15,
    "total_pumped_volume_m3_day": 6751.67,
    "total_hydraulic_energy_kwh_day": 697.2
  },
  "data_quality_flags": []
}
```

---
## Задача 2 (`тенино_teacher_tu_developer_6cb86feebd`)

Вопрос инженера: Застройщик просит техусловия на подключение нового жилого дома в городе «тенино». Судя по свободным напорам и этажности существующих узлов, какие ограничения и риски просадки давления есть в сети?

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "nodes_summary": {
    "consumer_nodes_count": 214,
    "total_daily_consumption_m3_day": 10931.35,
    "sum_peak_node_demand_m3_h": 618.31,
    "free_pressure_network_min_m": 27.26,
    "free_pressure_network_max_m": 78.47,
    "deficit_nodes_count": 42,
    "excess_pressure_over_60m_nodes_count": 21,
    "floors_distribution": {
      "1_эт": 107,
      "2_эт": 1,
      "3_эт": 2,
      "5_эт": 13,
      "9_эт": 39,
      "10_эт": 40,
      "12_эт": 4,
      "14_эт": 3,
      "17_эт": 5
    },
    "worst_deficit_nodes": [
      {
        "node_id": "c539",
        "floors": 14,
        "required_pressure_m": 62.0,
        "free_pressure_min_m": 51.03,
        "margin_min_m": -10.97,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 5.5,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c541",
        "floors": 14,
        "required_pressure_m": 62.0,
        "free_pressure_min_m": 51.66,
        "margin_min_m": -10.34,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 5.28,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c250",
        "floors": 17,
        "required_pressure_m": 74.0,
        "free_pressure_min_m": 63.98,
        "margin_min_m": -10.02,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 10.72,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c598",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 40.89,
        "margin_min_m": -5.11,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 43.27,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c491",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 41.34,
        "margin_min_m": -4.66,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 7.23,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c614",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 41.37,
        "margin_min_m": -4.63,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 7.03,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c584",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 41.72,
        "margin_min_m": -4.28,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 53.44,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c409",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 42.1,
        "margin_min_m": -3.9,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 25.38,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "highest_excess_pressure_nodes": [
      {
        "node_id": "c360",
        "floors": 1,
        "free_pressure_max_m": 78.47,
        "pressure_max_bar": 7.7,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c357",
        "floors": 1,
        "free_pressure_max_m": 78.37,
        "pressure_max_bar": 7.68,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c361",
        "floors": 1,
        "free_pressure_max_m": 77.99,
        "pressure_max_bar": 7.65,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c358",
        "floors": 14,
        "free_pressure_max_m": 77.97,
        "pressure_max_bar": 7.65,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c347",
        "floors": 17,
        "free_pressure_max_m": 77.57,
        "pressure_max_bar": 7.61,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c349",
        "floors": 1,
        "free_pressure_max_m": 77.54,
        "pressure_max_bar": 7.6,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c326",
        "floors": 17,
        "free_pressure_max_m": 75.0,
        "pressure_max_bar": 7.36,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c327",
        "floors": 1,
        "free_pressure_max_m": 74.49,
        "pressure_max_bar": 7.3,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      }
    ]
  }
}
```

---
## Задача 3 (`тенино_teacher_prv_zoning_07a94b0d39`)

Вопрос инженера: Проанализируй зоны минимального и избыточного (>60 м) свободного напора в «тенино». Где целесообразно зонирование сети или установка регуляторов давления PRV?

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "nodes_summary": {
    "consumer_nodes_count": 214,
    "total_daily_consumption_m3_day": 10931.35,
    "sum_peak_node_demand_m3_h": 618.31,
    "free_pressure_network_min_m": 27.26,
    "free_pressure_network_max_m": 78.47,
    "deficit_nodes_count": 42,
    "excess_pressure_over_60m_nodes_count": 21,
    "floors_distribution": {
      "1_эт": 107,
      "2_эт": 1,
      "3_эт": 2,
      "5_эт": 13,
      "9_эт": 39,
      "10_эт": 40,
      "12_эт": 4,
      "14_эт": 3,
      "17_эт": 5
    },
    "worst_deficit_nodes": [
      {
        "node_id": "c539",
        "floors": 14,
        "required_pressure_m": 62.0,
        "free_pressure_min_m": 51.03,
        "margin_min_m": -10.97,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 5.5,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c541",
        "floors": 14,
        "required_pressure_m": 62.0,
        "free_pressure_min_m": 51.66,
        "margin_min_m": -10.34,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 5.28,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c250",
        "floors": 17,
        "required_pressure_m": 74.0,
        "free_pressure_min_m": 63.98,
        "margin_min_m": -10.02,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 10.72,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c598",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 40.89,
        "margin_min_m": -5.11,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 43.27,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c491",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 41.34,
        "margin_min_m": -4.66,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 7.23,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c614",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 41.37,
        "margin_min_m": -4.63,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 7.03,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c584",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 41.72,
        "margin_min_m": -4.28,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 53.44,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c409",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": 42.1,
        "margin_min_m": -3.9,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 25.38,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "highest_excess_pressure_nodes": [
      {
        "node_id": "c360",
        "floors": 1,
        "free_pressure_max_m": 78.47,
        "pressure_max_bar": 7.7,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c357",
        "floors": 1,
        "free_pressure_max_m": 78.37,
        "pressure_max_bar": 7.68,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c361",
        "floors": 1,
        "free_pressure_max_m": 77.99,
        "pressure_max_bar": 7.65,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c358",
        "floors": 14,
        "free_pressure_max_m": 77.97,
        "pressure_max_bar": 7.65,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c347",
        "floors": 17,
        "free_pressure_max_m": 77.57,
        "pressure_max_bar": 7.61,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c349",
        "floors": 1,
        "free_pressure_max_m": 77.54,
        "pressure_max_bar": 7.6,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c326",
        "floors": 17,
        "free_pressure_max_m": 75.0,
        "pressure_max_bar": 7.36,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c327",
        "floors": 1,
        "free_pressure_max_m": 74.49,
        "pressure_max_bar": 7.3,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      }
    ]
  }
}
```

---
## Задача 4 (`тенино_teacher_water_hammer_8c846bd9b6`)

Вопрос инженера: Оцени трубопроводы города «тенино» по критериям книги Walski: какие участки работают с повышенной скоростью, риском гидравлического удара (>3.0 м/с) и частыми реверсами потока?

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "pipes_summary": {
    "pipes_count": 0,
    "total_length_km": 0.0,
    "total_internal_water_volume_m3": 0.0,
    "network_max_velocity_m_s": null,
    "pipes_over_1_5_m_s_count": 0,
    "pipes_over_3_0_m_s_water_hammer_risk_count": 0,
    "stagnant_pipes_under_0_3_m_s_count": 0,
    "reverse_flow_pipes_count": 0,
    "self_loop_topology_pipes_count": 0,
    "top_high_velocity_pipes": [],
    "top_stagnant_pipes": [],
    "top_reverse_flow_pipes": []
  }
}
```

---
## Задача 5 (`тенино_teacher_stagnation_flushing_6076137f86`)

Вопрос инженера: Выдели застойные участки сети «тенино» со скоростью ниже 0.3 м/с и большим временем пробега воды. Как это влияет на качество воды и где нужна промывка или переключение задвижек?

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "pipes_summary": {
    "pipes_count": 0,
    "total_length_km": 0.0,
    "total_internal_water_volume_m3": 0.0,
    "network_max_velocity_m_s": null,
    "pipes_over_1_5_m_s_count": 0,
    "pipes_over_3_0_m_s_water_hammer_risk_count": 0,
    "stagnant_pipes_under_0_3_m_s_count": 0,
    "reverse_flow_pipes_count": 0,
    "self_loop_topology_pipes_count": 0,
    "top_high_velocity_pipes": [],
    "top_stagnant_pipes": [],
    "top_reverse_flow_pipes": []
  }
}
```

---
## Задача 6 (`тенино_teacher_pump_vfd_audit_51a6ef909d`)

Вопрос инженера: Проведи энергоаудит насосов модели «тенино»: сколько агрегатов в резерве, какова наработка, число пусков и полезная гидравлическая мощность? Оцени целесообразность ЧРП.

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "pumps_summary": {
    "total_pumps_declared": 21,
    "active_pumps_count": 6,
    "standby_off_pumps_count": 15,
    "total_pumped_volume_m3_day": 6751.67,
    "total_hydraulic_energy_kwh_day": 697.2,
    "active_pumps_details": [
      {
        "pump_id": "p1268",
        "curve_id": "u124",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 215.72,
        "flow_max_m3_h": 291.1,
        "tdh_head_m": 38.0,
        "hydraulic_power_kw": 22.33,
        "hydraulic_energy_kwh_day": 535.92
      },
      {
        "pump_id": "p1270",
        "curve_id": "u151",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 15.63,
        "flow_max_m3_h": 21.37,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 1.92,
        "hydraulic_energy_kwh_day": 46.08
      },
      {
        "pump_id": "p1273",
        "curve_id": "u150",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 21.63,
        "flow_max_m3_h": 29.57,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 1.77,
        "hydraulic_energy_kwh_day": 42.48
      },
      {
        "pump_id": "p1276",
        "curve_id": "u153",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.16,
        "flow_max_m3_h": 7.77,
        "tdh_head_m": 22.0,
        "hydraulic_power_kw": 0.43,
        "hydraulic_energy_kwh_day": 10.32
      },
      {
        "pump_id": "p1279",
        "curve_id": "u143",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 13.94,
        "flow_max_m3_h": 19.06,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 1.71,
        "hydraulic_energy_kwh_day": 41.04
      },
      {
        "pump_id": "p1282",
        "curve_id": "u151",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.24,
        "flow_max_m3_h": 9.91,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 0.89,
        "hydraulic_energy_kwh_day": 21.36
      }
    ]
  },
  "excess_nodes_over_60m": 21
}
```

---
## Задача 7 (`тенино_teacher_dispatcher_shift_7e9211b5e8`)

Вопрос инженера: Объясни сменному диспетчеру особенности суточного режима сети «тенино»: где меняет направление поток в трубах, как включаются насосы и какие узлы требуют контроля?

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "top_reverse_flow_pipes": [],
  "pumps_summary": {
    "total_pumps_declared": 21,
    "active_pumps_count": 6,
    "standby_off_pumps_count": 15,
    "total_pumped_volume_m3_day": 6751.67,
    "total_hydraulic_energy_kwh_day": 697.2,
    "active_pumps_details": [
      {
        "pump_id": "p1268",
        "curve_id": "u124",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 215.72,
        "flow_max_m3_h": 291.1,
        "tdh_head_m": 38.0,
        "hydraulic_power_kw": 22.33,
        "hydraulic_energy_kwh_day": 535.92
      },
      {
        "pump_id": "p1270",
        "curve_id": "u151",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 15.63,
        "flow_max_m3_h": 21.37,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 1.92,
        "hydraulic_energy_kwh_day": 46.08
      },
      {
        "pump_id": "p1273",
        "curve_id": "u150",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 21.63,
        "flow_max_m3_h": 29.57,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 1.77,
        "hydraulic_energy_kwh_day": 42.48
      },
      {
        "pump_id": "p1276",
        "curve_id": "u153",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.16,
        "flow_max_m3_h": 7.77,
        "tdh_head_m": 22.0,
        "hydraulic_power_kw": 0.43,
        "hydraulic_energy_kwh_day": 10.32
      },
      {
        "pump_id": "p1279",
        "curve_id": "u143",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 13.94,
        "flow_max_m3_h": 19.06,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 1.71,
        "hydraulic_energy_kwh_day": 41.04
      },
      {
        "pump_id": "p1282",
        "curve_id": "u151",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.24,
        "flow_max_m3_h": 9.91,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 0.89,
        "hydraulic_energy_kwh_day": 21.36
      }
    ]
  },
  "worst_deficit_nodes": [
    {
      "node_id": "c539",
      "floors": 14,
      "required_pressure_m": 62.0,
      "free_pressure_min_m": 51.03,
      "margin_min_m": -10.97,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 5.5,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c541",
      "floors": 14,
      "required_pressure_m": 62.0,
      "free_pressure_min_m": 51.66,
      "margin_min_m": -10.34,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 5.28,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c250",
      "floors": 17,
      "required_pressure_m": 74.0,
      "free_pressure_min_m": 63.98,
      "margin_min_m": -10.02,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 10.72,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c598",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": 40.89,
      "margin_min_m": -5.11,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 43.27,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c491",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": 41.34,
      "margin_min_m": -4.66,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 7.23,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c614",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": 41.37,
      "margin_min_m": -4.63,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 7.03,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c584",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": 41.72,
      "margin_min_m": -4.28,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 53.44,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c409",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": 42.1,
      "margin_min_m": -3.9,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 25.38,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    }
  ]
}
```

---
## Задача 8 (`тенино_teacher_schema_quality_af39e6035f`)

Вопрос инженера: Проверь качество расчётной схемы «тенино» после удаления нулевых строк: сколько транзитных узлов и резервных насосов отфильтровано и есть ли ошибки топологии Начало==Конец?

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 0,
    "pruned_standby_pumps_count": 0,
    "pruned_zero_consumers_count": 0
  },
  "schedules_summary": {
    "schedules_count": 0,
    "all_24_hours_valid": true,
    "max_peaking_factor_k_max": null,
    "min_night_factor_k_min": null
  },
  "self_loop_topology_pipes_count": 0,
  "data_quality_flags": []
}
```

---
## Задача 9 (`тенино_teacher_refusal_trap_be5e2b76c3`)

Вопрос инженера: Рассчитай для водоканала «тенино» годовую экономию в рублях при замене насосов, их фактический электрический КПД и остаточный хлор на крайних узлах.

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "pumps_summary": {
    "active_pumps_count": 6,
    "total_hydraulic_energy_kwh_day": 697.2
  }
}
```

---
## Задача 10 (`тенино_teacher_node_deep_dive_d904e0d545`)

Вопрос инженера: Разбери детально причины нехватки свободного напора на узле c539 в городе «тенино» и предложи инженерные решения.

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "node_diagnostic": {
    "node_id": "c539",
    "floors": 14,
    "required_pressure_m": 62.0,
    "free_pressure_min_m": 51.03,
    "margin_min_m": -10.97,
    "deficit_minutes_per_day": 1440,
    "daily_demand_m3": 5.5,
    "source": {
      "file": "Узел_этажность_и_свободный_напор.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 11 (`тенино_teacher_node_deep_dive_24f67ba3ec`)

Вопрос инженера: Разбери детально причины нехватки свободного напора на узле c541 в городе «тенино» и предложи инженерные решения.

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "node_diagnostic": {
    "node_id": "c541",
    "floors": 14,
    "required_pressure_m": 62.0,
    "free_pressure_min_m": 51.66,
    "margin_min_m": -10.34,
    "deficit_minutes_per_day": 1440,
    "daily_demand_m3": 5.28,
    "source": {
      "file": "Узел_этажность_и_свободный_напор.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 12 (`тенино_teacher_node_deep_dive_86684dbda8`)

Вопрос инженера: Разбери детально причины нехватки свободного напора на узле c250 в городе «тенино» и предложи инженерные решения.

Факты расчёта (facts_inline):
```json
{
  "city_name": "тенино",
  "node_diagnostic": {
    "node_id": "c250",
    "floors": 17,
    "required_pressure_m": 74.0,
    "free_pressure_min_m": 63.98,
    "margin_min_m": -10.02,
    "deficit_minutes_per_day": 1440,
    "daily_demand_m3": 10.72,
    "source": {
      "file": "Узел_этажность_и_свободный_напор.csv",
      "aggregation": "row_exact"
    }
  }
}
```
