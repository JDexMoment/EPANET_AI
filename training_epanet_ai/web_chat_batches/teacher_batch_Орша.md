# Пакет задач для разметки Моделью-Учителем (город: Орша)

**Системная инструкция Учителю:**
> Ты — главный инженер-гидравлик систем водоснабжения (уровня авторов руководства Walski et al. 'Advanced Water Distribution Modeling and Management' и СП 31.13330.2021). Напиши глубокий, живой, профессиональный инженерный ответ для обучения младшей локальной модели EPANET-AI.

ЖЕЛЕЗНЫЕ ПРАВИЛА ДИСТИЛЛЯЦИИ (нарушение бракует пример!):
1. Опирайся ИСКЛЮЧИТЕЛЬНО на переданный JSON `facts_inline`.
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО считать в уме (не вычисляй проценты, разности или суммы, которых нет в JSON) и запрещено писать любые числа, отсутствующие во входном `facts_inline` (разрешены только константы нормативов: 10 м и +4 м на этаж по СП 31.13330.2021, 60 м макс. напор, 0.3 / 1.5 / 3.0 м/с скорости по Walski, 24 ч, 1440 шагов).
3. Обязательно указывай конкретные строковые ID узлов (c*), труб (e*), насосов (p*), кривых (u*, t*) и объясняй физику процессов.
4. Если спрашивают данные, которых нет в `facts_inline` (КПД двигателя, тариф в рублях, остаточный хлор), чётко перечисли недостающие таблицы и НЕ выдумывай оценочных цифр.

---
## Задача 1 (`Орша_teacher_exec_memo_96fa45d3a2`)

Вопрос инженера: Подготовь аналитическую записку главному инженеру водоканала по расчёту сети «Орша»: оцени баланс, главные гидравлические риски и очерёдность мероприятий.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 0,
    "pruned_standby_pumps_count": 0,
    "pruned_zero_consumers_count": 0
  },
  "nodes_overview": {
    "consumer_nodes_count": 9360,
    "total_daily_consumption_m3_day": 10516.43,
    "sum_peak_node_demand_m3_h": 977.32,
    "free_pressure_network_min_m": -96.07,
    "free_pressure_network_max_m": 112.28,
    "deficit_nodes_count": 5363,
    "excess_pressure_over_60m_nodes_count": 315,
    "floors_distribution": {
      "1_эт": 8035,
      "2_эт": 477,
      "3_эт": 204,
      "4_эт": 97,
      "5_эт": 383,
      "6_эт": 11,
      "7_эт": 2,
      "8_эт": 6,
      "9_эт": 139,
      "10_эт": 6
    }
  },
  "pipes_overview": {
    "pipes_count": 18127,
    "total_length_km": 606.058,
    "total_internal_water_volume_m3": 9720.44,
    "network_max_velocity_m_s": 81.722,
    "pipes_over_1_5_m_s_count": 43,
    "pipes_over_3_0_m_s_water_hammer_risk_count": 10,
    "stagnant_pipes_under_0_3_m_s_count": 16945,
    "reverse_flow_pipes_count": 4576,
    "self_loop_topology_pipes_count": 18118
  },
  "pumps_overview": {
    "total_pumps_declared": 0,
    "active_pumps_count": 0,
    "standby_off_pumps_count": 0,
    "total_pumped_volume_m3_day": 0.0,
    "total_hydraulic_energy_kwh_day": 0.0
  },
  "data_quality_flags": [
    "В Труба.csv обнаружено 18118 участков с петлёй экспорта Начало == Конец (потери напора dH по ним заблокированы до исправления топологии в AquaBit)",
    "В График потребления.csv найдено 2 графиков с числом точек != 24"
  ]
}
```

---
## Задача 2 (`Орша_teacher_tu_developer_4b1c0919d6`)

Вопрос инженера: Застройщик просит техусловия на подключение нового жилого дома в городе «Орша». Судя по свободным напорам и этажности существующих узлов, какие ограничения и риски просадки давления есть в сети?

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "nodes_summary": {
    "consumer_nodes_count": 9360,
    "total_daily_consumption_m3_day": 10516.43,
    "sum_peak_node_demand_m3_h": 977.32,
    "free_pressure_network_min_m": -96.07,
    "free_pressure_network_max_m": 112.28,
    "deficit_nodes_count": 5363,
    "excess_pressure_over_60m_nodes_count": 315,
    "floors_distribution": {
      "1_эт": 8035,
      "2_эт": 477,
      "3_эт": 204,
      "4_эт": 97,
      "5_эт": 383,
      "6_эт": 11,
      "7_эт": 2,
      "8_эт": 6,
      "9_эт": 139,
      "10_эт": 6
    },
    "worst_deficit_nodes": [
      {
        "node_id": "c50527",
        "floors": 9,
        "required_pressure_m": 42.0,
        "free_pressure_min_m": -78.85,
        "margin_min_m": -120.85,
        "deficit_minutes_per_day": 273,
        "daily_demand_m3": 4.26,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c50531",
        "floors": 9,
        "required_pressure_m": 42.0,
        "free_pressure_min_m": -78.85,
        "margin_min_m": -120.85,
        "deficit_minutes_per_day": 273,
        "daily_demand_m3": 7.9,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c46565",
        "floors": 2,
        "required_pressure_m": 14.0,
        "free_pressure_min_m": -96.07,
        "margin_min_m": -110.07,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": -43.61,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c46557",
        "floors": 3,
        "required_pressure_m": 18.0,
        "free_pressure_min_m": -92.0,
        "margin_min_m": -110.0,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": -39.15,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c37009",
        "floors": 9,
        "required_pressure_m": 42.0,
        "free_pressure_min_m": -67.15,
        "margin_min_m": -109.15,
        "deficit_minutes_per_day": 1183,
        "daily_demand_m3": 0.16,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c46555",
        "floors": 1,
        "required_pressure_m": 10.0,
        "free_pressure_min_m": -94.25,
        "margin_min_m": -104.25,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": -15.34,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c50563",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": -57.3,
        "margin_min_m": -103.3,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 8.04,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c50559",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": -56.1,
        "margin_min_m": -102.1,
        "deficit_minutes_per_day": 275,
        "daily_demand_m3": 12.04,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "highest_excess_pressure_nodes": [
      {
        "node_id": "c31164",
        "floors": 9,
        "free_pressure_max_m": 112.28,
        "pressure_max_bar": 11.01,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31165",
        "floors": 9,
        "free_pressure_max_m": 112.28,
        "pressure_max_bar": 11.01,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c32683",
        "floors": 9,
        "free_pressure_max_m": 109.95,
        "pressure_max_bar": 10.78,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31419",
        "floors": 1,
        "free_pressure_max_m": 108.4,
        "pressure_max_bar": 10.63,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31398",
        "floors": 9,
        "free_pressure_max_m": 108.32,
        "pressure_max_bar": 10.62,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c32268",
        "floors": 10,
        "free_pressure_max_m": 106.85,
        "pressure_max_bar": 10.48,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c32274",
        "floors": 9,
        "free_pressure_max_m": 106.71,
        "pressure_max_bar": 10.46,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31171",
        "floors": 1,
        "free_pressure_max_m": 105.65,
        "pressure_max_bar": 10.36,
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
## Задача 3 (`Орша_teacher_prv_zoning_883a6243e7`)

Вопрос инженера: Проанализируй зоны минимального и избыточного (>60 м) свободного напора в «Орша». Где целесообразно зонирование сети или установка регуляторов давления PRV?

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "nodes_summary": {
    "consumer_nodes_count": 9360,
    "total_daily_consumption_m3_day": 10516.43,
    "sum_peak_node_demand_m3_h": 977.32,
    "free_pressure_network_min_m": -96.07,
    "free_pressure_network_max_m": 112.28,
    "deficit_nodes_count": 5363,
    "excess_pressure_over_60m_nodes_count": 315,
    "floors_distribution": {
      "1_эт": 8035,
      "2_эт": 477,
      "3_эт": 204,
      "4_эт": 97,
      "5_эт": 383,
      "6_эт": 11,
      "7_эт": 2,
      "8_эт": 6,
      "9_эт": 139,
      "10_эт": 6
    },
    "worst_deficit_nodes": [
      {
        "node_id": "c50527",
        "floors": 9,
        "required_pressure_m": 42.0,
        "free_pressure_min_m": -78.85,
        "margin_min_m": -120.85,
        "deficit_minutes_per_day": 273,
        "daily_demand_m3": 4.26,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c50531",
        "floors": 9,
        "required_pressure_m": 42.0,
        "free_pressure_min_m": -78.85,
        "margin_min_m": -120.85,
        "deficit_minutes_per_day": 273,
        "daily_demand_m3": 7.9,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c46565",
        "floors": 2,
        "required_pressure_m": 14.0,
        "free_pressure_min_m": -96.07,
        "margin_min_m": -110.07,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": -43.61,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c46557",
        "floors": 3,
        "required_pressure_m": 18.0,
        "free_pressure_min_m": -92.0,
        "margin_min_m": -110.0,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": -39.15,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c37009",
        "floors": 9,
        "required_pressure_m": 42.0,
        "free_pressure_min_m": -67.15,
        "margin_min_m": -109.15,
        "deficit_minutes_per_day": 1183,
        "daily_demand_m3": 0.16,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c46555",
        "floors": 1,
        "required_pressure_m": 10.0,
        "free_pressure_min_m": -94.25,
        "margin_min_m": -104.25,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": -15.34,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c50563",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": -57.3,
        "margin_min_m": -103.3,
        "deficit_minutes_per_day": 1440,
        "daily_demand_m3": 8.04,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c50559",
        "floors": 10,
        "required_pressure_m": 46.0,
        "free_pressure_min_m": -56.1,
        "margin_min_m": -102.1,
        "deficit_minutes_per_day": 275,
        "daily_demand_m3": 12.04,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "highest_excess_pressure_nodes": [
      {
        "node_id": "c31164",
        "floors": 9,
        "free_pressure_max_m": 112.28,
        "pressure_max_bar": 11.01,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31165",
        "floors": 9,
        "free_pressure_max_m": 112.28,
        "pressure_max_bar": 11.01,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c32683",
        "floors": 9,
        "free_pressure_max_m": 109.95,
        "pressure_max_bar": 10.78,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31419",
        "floors": 1,
        "free_pressure_max_m": 108.4,
        "pressure_max_bar": 10.63,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31398",
        "floors": 9,
        "free_pressure_max_m": 108.32,
        "pressure_max_bar": 10.62,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c32268",
        "floors": 10,
        "free_pressure_max_m": 106.85,
        "pressure_max_bar": 10.48,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c32274",
        "floors": 9,
        "free_pressure_max_m": 106.71,
        "pressure_max_bar": 10.46,
        "source": {
          "file": "Узел_этажность_и_свободный_напор.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "node_id": "c31171",
        "floors": 1,
        "free_pressure_max_m": 105.65,
        "pressure_max_bar": 10.36,
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
## Задача 4 (`Орша_teacher_water_hammer_55342e02bd`)

Вопрос инженера: Оцени трубопроводы города «Орша» по критериям книги Walski: какие участки работают с повышенной скоростью, риском гидравлического удара (>3.0 м/с) и частыми реверсами потока?

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pipes_summary": {
    "pipes_count": 18127,
    "total_length_km": 606.058,
    "total_internal_water_volume_m3": 9720.44,
    "network_max_velocity_m_s": 81.722,
    "pipes_over_1_5_m_s_count": 43,
    "pipes_over_3_0_m_s_water_hammer_risk_count": 10,
    "stagnant_pipes_under_0_3_m_s_count": 16945,
    "reverse_flow_pipes_count": 4576,
    "self_loop_topology_pipes_count": 18118,
    "top_high_velocity_pipes": [
      {
        "pipe_id": "e56313",
        "diameter_mm": 100.0,
        "length_m": 2.1,
        "q_max_m3_h": 2310.65,
        "q_over_d_index": 23.1065,
        "velocity_max_m_s": 81.722,
        "reynolds_max": 6252678.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e40980",
        "diameter_mm": 100.0,
        "length_m": 5.8,
        "q_max_m3_h": 140.95,
        "q_over_d_index": 1.4095,
        "velocity_max_m_s": 4.985,
        "reynolds_max": 381415.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41023",
        "diameter_mm": 100.0,
        "length_m": 1.3,
        "q_max_m3_h": 140.87,
        "q_over_d_index": 1.4087,
        "velocity_max_m_s": 4.982,
        "reynolds_max": 381201.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e40999",
        "diameter_mm": 100.0,
        "length_m": 30.4,
        "q_max_m3_h": 140.71,
        "q_over_d_index": 1.4071,
        "velocity_max_m_s": 4.977,
        "reynolds_max": 380765.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41006",
        "diameter_mm": 100.0,
        "length_m": 2.9,
        "q_max_m3_h": 140.29,
        "q_over_d_index": 1.4029,
        "velocity_max_m_s": 4.962,
        "reynolds_max": 379625.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41025",
        "diameter_mm": 100.0,
        "length_m": 109.0,
        "q_max_m3_h": 140.2,
        "q_over_d_index": 1.402,
        "velocity_max_m_s": 4.959,
        "reynolds_max": 379388.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e40993",
        "diameter_mm": 100.0,
        "length_m": 31.7,
        "q_max_m3_h": 140.05,
        "q_over_d_index": 1.4005,
        "velocity_max_m_s": 4.953,
        "reynolds_max": 378982.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41024",
        "diameter_mm": 100.0,
        "length_m": 1.1,
        "q_max_m3_h": 139.95,
        "q_over_d_index": 1.3995,
        "velocity_max_m_s": 4.95,
        "reynolds_max": 378707.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "top_stagnant_pipes": [
      {
        "pipe_id": "e173852",
        "diameter_mm": 300.0,
        "length_m": 500.2,
        "velocity_max_m_s": 0.0001,
        "travel_time_min": 83361.7,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e23870",
        "diameter_mm": 125.0,
        "length_m": 401.4,
        "velocity_max_m_s": 0.0002,
        "travel_time_min": 33448.3,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e173873",
        "diameter_mm": 200.0,
        "length_m": 317.9,
        "velocity_max_m_s": 0.0003,
        "travel_time_min": 26495.8,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e28053",
        "diameter_mm": 225.0,
        "length_m": 135.2,
        "velocity_max_m_s": 0.0002,
        "travel_time_min": 22535.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e52506",
        "diameter_mm": 100.0,
        "length_m": 626.3,
        "velocity_max_m_s": 0.0007,
        "travel_time_min": 20876.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e38760",
        "diameter_mm": 150.0,
        "length_m": 111.2,
        "velocity_max_m_s": 0.0002,
        "travel_time_min": 18536.7,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e173856",
        "diameter_mm": 150.0,
        "length_m": 332.8,
        "velocity_max_m_s": 0.0005,
        "travel_time_min": 18491.1,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e18080",
        "diameter_mm": 100.0,
        "length_m": 1025.0,
        "velocity_max_m_s": 0.0014,
        "travel_time_min": 17082.7,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "top_reverse_flow_pipes": [
      {
        "pipe_id": "e18089",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.006
      },
      {
        "pipe_id": "e173887",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.004
      },
      {
        "pipe_id": "e173886",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.008
      },
      {
        "pipe_id": "e173885",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.001
      },
      {
        "pipe_id": "e173883",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.003
      },
      {
        "pipe_id": "e173882",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.012
      },
      {
        "pipe_id": "e173881",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.001
      },
      {
        "pipe_id": "e173874",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.001
      }
    ]
  }
}
```

---
## Задача 5 (`Орша_teacher_stagnation_flushing_e0d086632a`)

Вопрос инженера: Выдели застойные участки сети «Орша» со скоростью ниже 0.3 м/с и большим временем пробега воды. Как это влияет на качество воды и где нужна промывка или переключение задвижек?

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pipes_summary": {
    "pipes_count": 18127,
    "total_length_km": 606.058,
    "total_internal_water_volume_m3": 9720.44,
    "network_max_velocity_m_s": 81.722,
    "pipes_over_1_5_m_s_count": 43,
    "pipes_over_3_0_m_s_water_hammer_risk_count": 10,
    "stagnant_pipes_under_0_3_m_s_count": 16945,
    "reverse_flow_pipes_count": 4576,
    "self_loop_topology_pipes_count": 18118,
    "top_high_velocity_pipes": [
      {
        "pipe_id": "e56313",
        "diameter_mm": 100.0,
        "length_m": 2.1,
        "q_max_m3_h": 2310.65,
        "q_over_d_index": 23.1065,
        "velocity_max_m_s": 81.722,
        "reynolds_max": 6252678.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e40980",
        "diameter_mm": 100.0,
        "length_m": 5.8,
        "q_max_m3_h": 140.95,
        "q_over_d_index": 1.4095,
        "velocity_max_m_s": 4.985,
        "reynolds_max": 381415.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41023",
        "diameter_mm": 100.0,
        "length_m": 1.3,
        "q_max_m3_h": 140.87,
        "q_over_d_index": 1.4087,
        "velocity_max_m_s": 4.982,
        "reynolds_max": 381201.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e40999",
        "diameter_mm": 100.0,
        "length_m": 30.4,
        "q_max_m3_h": 140.71,
        "q_over_d_index": 1.4071,
        "velocity_max_m_s": 4.977,
        "reynolds_max": 380765.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41006",
        "diameter_mm": 100.0,
        "length_m": 2.9,
        "q_max_m3_h": 140.29,
        "q_over_d_index": 1.4029,
        "velocity_max_m_s": 4.962,
        "reynolds_max": 379625.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41025",
        "diameter_mm": 100.0,
        "length_m": 109.0,
        "q_max_m3_h": 140.2,
        "q_over_d_index": 1.402,
        "velocity_max_m_s": 4.959,
        "reynolds_max": 379388.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e40993",
        "diameter_mm": 100.0,
        "length_m": 31.7,
        "q_max_m3_h": 140.05,
        "q_over_d_index": 1.4005,
        "velocity_max_m_s": 4.953,
        "reynolds_max": 378982.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e41024",
        "diameter_mm": 100.0,
        "length_m": 1.1,
        "q_max_m3_h": 139.95,
        "q_over_d_index": 1.3995,
        "velocity_max_m_s": 4.95,
        "reynolds_max": 378707.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "top_stagnant_pipes": [
      {
        "pipe_id": "e173852",
        "diameter_mm": 300.0,
        "length_m": 500.2,
        "velocity_max_m_s": 0.0001,
        "travel_time_min": 83361.7,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e23870",
        "diameter_mm": 125.0,
        "length_m": 401.4,
        "velocity_max_m_s": 0.0002,
        "travel_time_min": 33448.3,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e173873",
        "diameter_mm": 200.0,
        "length_m": 317.9,
        "velocity_max_m_s": 0.0003,
        "travel_time_min": 26495.8,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e28053",
        "diameter_mm": 225.0,
        "length_m": 135.2,
        "velocity_max_m_s": 0.0002,
        "travel_time_min": 22535.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e52506",
        "diameter_mm": 100.0,
        "length_m": 626.3,
        "velocity_max_m_s": 0.0007,
        "travel_time_min": 20876.0,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e38760",
        "diameter_mm": 150.0,
        "length_m": 111.2,
        "velocity_max_m_s": 0.0002,
        "travel_time_min": 18536.7,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e173856",
        "diameter_mm": 150.0,
        "length_m": 332.8,
        "velocity_max_m_s": 0.0005,
        "travel_time_min": 18491.1,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      },
      {
        "pipe_id": "e18080",
        "diameter_mm": 100.0,
        "length_m": 1025.0,
        "velocity_max_m_s": 0.0014,
        "travel_time_min": 17082.7,
        "source": {
          "file": "Труба_скорости_и_режимы_Walski.csv",
          "aggregation": "row_exact"
        }
      }
    ],
    "top_reverse_flow_pipes": [
      {
        "pipe_id": "e18089",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.006
      },
      {
        "pipe_id": "e173887",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.004
      },
      {
        "pipe_id": "e173886",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.008
      },
      {
        "pipe_id": "e173885",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.001
      },
      {
        "pipe_id": "e173883",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.003
      },
      {
        "pipe_id": "e173882",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.012
      },
      {
        "pipe_id": "e173881",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.001
      },
      {
        "pipe_id": "e173874",
        "reverse_steps_of_1440": 660,
        "direction_sign_flips_per_day": 0,
        "velocity_max_m_s": 0.001
      }
    ]
  }
}
```

---
## Задача 6 (`Орша_teacher_pump_vfd_audit_3e964d6efa`)

Вопрос инженера: Проведи энергоаудит насосов модели «Орша»: сколько агрегатов в резерве, какова наработка, число пусков и полезная гидравлическая мощность? Оцени целесообразность ЧРП.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pumps_summary": {
    "total_pumps_declared": 0,
    "active_pumps_count": 0,
    "standby_off_pumps_count": 0,
    "total_pumped_volume_m3_day": 0.0,
    "total_hydraulic_energy_kwh_day": 0.0,
    "active_pumps_details": []
  },
  "excess_nodes_over_60m": 315
}
```

---
## Задача 7 (`Орша_teacher_dispatcher_shift_dbe11e4410`)

Вопрос инженера: Объясни сменному диспетчеру особенности суточного режима сети «Орша»: где меняет направление поток в трубах, как включаются насосы и какие узлы требуют контроля?

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "top_reverse_flow_pipes": [
    {
      "pipe_id": "e18089",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.006
    },
    {
      "pipe_id": "e173887",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.004
    },
    {
      "pipe_id": "e173886",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.008
    },
    {
      "pipe_id": "e173885",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.001
    },
    {
      "pipe_id": "e173883",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.003
    },
    {
      "pipe_id": "e173882",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.012
    },
    {
      "pipe_id": "e173881",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.001
    },
    {
      "pipe_id": "e173874",
      "reverse_steps_of_1440": 660,
      "direction_sign_flips_per_day": 0,
      "velocity_max_m_s": 0.001
    }
  ],
  "pumps_summary": {
    "total_pumps_declared": 0,
    "active_pumps_count": 0,
    "standby_off_pumps_count": 0,
    "total_pumped_volume_m3_day": 0.0,
    "total_hydraulic_energy_kwh_day": 0.0,
    "active_pumps_details": []
  },
  "worst_deficit_nodes": [
    {
      "node_id": "c50527",
      "floors": 9,
      "required_pressure_m": 42.0,
      "free_pressure_min_m": -78.85,
      "margin_min_m": -120.85,
      "deficit_minutes_per_day": 273,
      "daily_demand_m3": 4.26,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c50531",
      "floors": 9,
      "required_pressure_m": 42.0,
      "free_pressure_min_m": -78.85,
      "margin_min_m": -120.85,
      "deficit_minutes_per_day": 273,
      "daily_demand_m3": 7.9,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c46565",
      "floors": 2,
      "required_pressure_m": 14.0,
      "free_pressure_min_m": -96.07,
      "margin_min_m": -110.07,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": -43.61,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c46557",
      "floors": 3,
      "required_pressure_m": 18.0,
      "free_pressure_min_m": -92.0,
      "margin_min_m": -110.0,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": -39.15,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c37009",
      "floors": 9,
      "required_pressure_m": 42.0,
      "free_pressure_min_m": -67.15,
      "margin_min_m": -109.15,
      "deficit_minutes_per_day": 1183,
      "daily_demand_m3": 0.16,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c46555",
      "floors": 1,
      "required_pressure_m": 10.0,
      "free_pressure_min_m": -94.25,
      "margin_min_m": -104.25,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": -15.34,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c50563",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": -57.3,
      "margin_min_m": -103.3,
      "deficit_minutes_per_day": 1440,
      "daily_demand_m3": 8.04,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    },
    {
      "node_id": "c50559",
      "floors": 10,
      "required_pressure_m": 46.0,
      "free_pressure_min_m": -56.1,
      "margin_min_m": -102.1,
      "deficit_minutes_per_day": 275,
      "daily_demand_m3": 12.04,
      "source": {
        "file": "Узел_этажность_и_свободный_напор.csv",
        "aggregation": "row_exact"
      }
    }
  ]
}
```

---
## Задача 8 (`Орша_teacher_schema_quality_58e23ec116`)

Вопрос инженера: Проверь качество расчётной схемы «Орша» после удаления нулевых строк: сколько транзитных узлов и резервных насосов отфильтровано и есть ли ошибки топологии Начало==Конец?

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 0,
    "pruned_standby_pumps_count": 0,
    "pruned_zero_consumers_count": 0
  },
  "schedules_summary": {
    "schedules_count": 6,
    "all_24_hours_valid": false,
    "max_peaking_factor_k_max": 1.358,
    "min_night_factor_k_min": 0.3783
  },
  "self_loop_topology_pipes_count": 18118,
  "data_quality_flags": [
    "В Труба.csv обнаружено 18118 участков с петлёй экспорта Начало == Конец (потери напора dH по ним заблокированы до исправления топологии в AquaBit)",
    "В График потребления.csv найдено 2 графиков с числом точек != 24"
  ]
}
```

---
## Задача 9 (`Орша_teacher_refusal_trap_88b39657f5`)

Вопрос инженера: Рассчитай для водоканала «Орша» годовую экономию в рублях при замене насосов, их фактический электрический КПД и остаточный хлор на крайних узлах.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pumps_summary": {
    "active_pumps_count": 0,
    "total_hydraulic_energy_kwh_day": 0.0
  }
}
```

---
## Задача 10 (`Орша_teacher_node_deep_dive_ca0a93c393`)

Вопрос инженера: Разбери детально причины нехватки свободного напора на узле c50527 в городе «Орша» и предложи инженерные решения.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "node_diagnostic": {
    "node_id": "c50527",
    "floors": 9,
    "required_pressure_m": 42.0,
    "free_pressure_min_m": -78.85,
    "margin_min_m": -120.85,
    "deficit_minutes_per_day": 273,
    "daily_demand_m3": 4.26,
    "source": {
      "file": "Узел_этажность_и_свободный_напор.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 11 (`Орша_teacher_node_deep_dive_09efad42a3`)

Вопрос инженера: Разбери детально причины нехватки свободного напора на узле c50531 в городе «Орша» и предложи инженерные решения.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "node_diagnostic": {
    "node_id": "c50531",
    "floors": 9,
    "required_pressure_m": 42.0,
    "free_pressure_min_m": -78.85,
    "margin_min_m": -120.85,
    "deficit_minutes_per_day": 273,
    "daily_demand_m3": 7.9,
    "source": {
      "file": "Узел_этажность_и_свободный_напор.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 12 (`Орша_teacher_node_deep_dive_03ef671b18`)

Вопрос инженера: Разбери детально причины нехватки свободного напора на узле c46565 в городе «Орша» и предложи инженерные решения.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "node_diagnostic": {
    "node_id": "c46565",
    "floors": 2,
    "required_pressure_m": 14.0,
    "free_pressure_min_m": -96.07,
    "margin_min_m": -110.07,
    "deficit_minutes_per_day": 1440,
    "daily_demand_m3": -43.61,
    "source": {
      "file": "Узел_этажность_и_свободный_напор.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 13 (`Орша_teacher_pipe_deep_dive_59e823eb17`)

Вопрос инженера: Проанализируй гидравлический режим участка трубы e173852 в модели «Орша» (скорость, диаметр, время пробега воды) и дай рекомендации.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pipe_diagnostic": {
    "pipe_id": "e173852",
    "diameter_mm": 300.0,
    "length_m": 500.2,
    "velocity_max_m_s": 0.0001,
    "travel_time_min": 83361.7,
    "source": {
      "file": "Труба_скорости_и_режимы_Walski.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 14 (`Орша_teacher_pipe_deep_dive_5ecd9a694b`)

Вопрос инженера: Проанализируй гидравлический режим участка трубы e23870 в модели «Орша» (скорость, диаметр, время пробега воды) и дай рекомендации.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pipe_diagnostic": {
    "pipe_id": "e23870",
    "diameter_mm": 125.0,
    "length_m": 401.4,
    "velocity_max_m_s": 0.0002,
    "travel_time_min": 33448.3,
    "source": {
      "file": "Труба_скорости_и_режимы_Walski.csv",
      "aggregation": "row_exact"
    }
  }
}
```

---
## Задача 15 (`Орша_teacher_pipe_deep_dive_01ce4e18b2`)

Вопрос инженера: Проанализируй гидравлический режим участка трубы e173873 в модели «Орша» (скорость, диаметр, время пробега воды) и дай рекомендации.

Факты расчёта (facts_inline):
```json
{
  "city_name": "Орша",
  "pipe_diagnostic": {
    "pipe_id": "e173873",
    "diameter_mm": 200.0,
    "length_m": 317.9,
    "velocity_max_m_s": 0.0003,
    "travel_time_min": 26495.8,
    "source": {
      "file": "Труба_скорости_и_режимы_Walski.csv",
      "aggregation": "row_exact"
    }
  }
}
```
