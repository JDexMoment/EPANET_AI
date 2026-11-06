# Пакет задач для разметки Моделью-Учителем (город: модель семей)

**Системная инструкция Учителю:**
> Ты — главный инженер-гидравлик систем водоснабжения (уровня авторов руководства Walski et al. 'Advanced Water Distribution Modeling and Management' и СП 31.13330.2021). Напиши глубокий, живой, профессиональный инженерный ответ для обучения младшей локальной модели EPANET-AI.

ЖЕЛЕЗНЫЕ ПРАВИЛА ДИСТИЛЛЯЦИИ (нарушение бракует пример!):
1. Опирайся ИСКЛЮЧИТЕЛЬНО на переданный JSON `facts_inline`.
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО считать в уме (не вычисляй проценты, разности или суммы, которых нет в JSON) и запрещено писать любые числа, отсутствующие во входном `facts_inline` (разрешены только константы нормативов: 10 м и +4 м на этаж по СП 31.13330.2021, 60 м макс. напор, 0.3 / 1.5 / 3.0 м/с скорости по Walski, 24 ч, 1440 шагов).
3. Обязательно указывай конкретные строковые ID узлов (c*), труб (e*), насосов (p*), кривых (u*, t*) и объясняй физику процессов.
4. Если спрашивают данные, которых нет в `facts_inline` (КПД двигателя, тариф в рублях, остаточный хлор), чётко перечисли недостающие таблицы и НЕ выдумывай оценочных цифр.

---
## Задача 1 (`модель семей_teacher_exec_memo_145dd5f594`)

Вопрос инженера: Подготовь аналитическую записку главному инженеру водоканала по расчёту сети «модель семей»: оцени баланс, главные гидравлические риски и очерёдность мероприятий.

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 21004,
    "pruned_standby_pumps_count": 35,
    "pruned_zero_consumers_count": 20927
  },
  "nodes_overview": {
    "consumer_nodes_count": 20712,
    "total_daily_consumption_m3_day": 71602.65,
    "sum_peak_node_demand_m3_h": 3608.18,
    "free_pressure_network_min_m": null,
    "free_pressure_network_max_m": null,
    "deficit_nodes_count": 0,
    "excess_pressure_over_60m_nodes_count": 0,
    "floors_distribution": {}
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
    "total_pumps_declared": 127,
    "active_pumps_count": 92,
    "standby_off_pumps_count": 35,
    "total_pumped_volume_m3_day": 156377.7,
    "total_hydraulic_energy_kwh_day": 21868.55
  },
  "data_quality_flags": [
    "В исходной таблице Узел.csv города «модель семей» на всех узлах стояло Требуемое давление = 0 (нормативная этажность не задавалась автором модели); показатели водоразбора и напоров собраны по фактическим узлам-абонентам",
    "В График потребления.csv найдено 2 графиков с числом точек != 24"
  ]
}
```

---
## Задача 2 (`модель семей_teacher_tu_developer_e8c44f50f2`)

Вопрос инженера: Застройщик просит техусловия на подключение нового жилого дома в городе «модель семей». Судя по свободным напорам и этажности существующих узлов, какие ограничения и риски просадки давления есть в сети?

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "nodes_summary": {
    "consumer_nodes_count": 20712,
    "total_daily_consumption_m3_day": 71602.65,
    "sum_peak_node_demand_m3_h": 3608.18,
    "free_pressure_network_min_m": null,
    "free_pressure_network_max_m": null,
    "deficit_nodes_count": 0,
    "excess_pressure_over_60m_nodes_count": 0,
    "floors_distribution": {},
    "worst_deficit_nodes": [],
    "highest_excess_pressure_nodes": []
  }
}
```

---
## Задача 3 (`модель семей_teacher_prv_zoning_03fd7cf64f`)

Вопрос инженера: Проанализируй зоны минимального и избыточного (>60 м) свободного напора в «модель семей». Где целесообразно зонирование сети или установка регуляторов давления PRV?

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "nodes_summary": {
    "consumer_nodes_count": 20712,
    "total_daily_consumption_m3_day": 71602.65,
    "sum_peak_node_demand_m3_h": 3608.18,
    "free_pressure_network_min_m": null,
    "free_pressure_network_max_m": null,
    "deficit_nodes_count": 0,
    "excess_pressure_over_60m_nodes_count": 0,
    "floors_distribution": {},
    "worst_deficit_nodes": [],
    "highest_excess_pressure_nodes": []
  }
}
```

---
## Задача 4 (`модель семей_teacher_water_hammer_cdfd8799f4`)

Вопрос инженера: Оцени трубопроводы города «модель семей» по критериям книги Walski: какие участки работают с повышенной скоростью, риском гидравлического удара (>3.0 м/с) и частыми реверсами потока?

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
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
## Задача 5 (`модель семей_teacher_stagnation_flushing_5be6ddfd79`)

Вопрос инженера: Выдели застойные участки сети «модель семей» со скоростью ниже 0.3 м/с и большим временем пробега воды. Как это влияет на качество воды и где нужна промывка или переключение задвижек?

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
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
## Задача 6 (`модель семей_teacher_pump_vfd_audit_59f77489e8`)

Вопрос инженера: Проведи энергоаудит насосов модели «модель семей»: сколько агрегатов в резерве, какова наработка, число пусков и полезная гидравлическая мощность? Оцени целесообразность ЧРП.

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "pumps_summary": {
    "total_pumps_declared": 127,
    "active_pumps_count": 92,
    "standby_off_pumps_count": 35,
    "total_pumped_volume_m3_day": 156377.7,
    "total_hydraulic_energy_kwh_day": 21868.55,
    "active_pumps_details": [
      {
        "pump_id": "p3381720",
        "curve_id": "u3381741",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 467.16,
        "flow_max_m3_h": 619.75,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 76.35,
        "hydraulic_energy_kwh_day": 1832.4
      },
      {
        "pump_id": "p3381996",
        "curve_id": "u3382079",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 751.1,
        "flow_max_m3_h": 863.35,
        "tdh_head_m": 62.28,
        "hydraulic_power_kw": 127.43,
        "hydraulic_energy_kwh_day": 3058.32
      },
      {
        "pump_id": "p3382208",
        "curve_id": "u3381747",
        "run_hours_per_day": 18.0,
        "starts_per_day": 2,
        "flow_mean_m3_h": 315.8,
        "flow_max_m3_h": 934.08,
        "tdh_head_m": 63.0,
        "hydraulic_power_kw": 54.2,
        "hydraulic_energy_kwh_day": 975.6
      },
      {
        "pump_id": "p3382211",
        "curve_id": "u3381747",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1286.47,
        "flow_max_m3_h": 1531.3,
        "tdh_head_m": 63.0,
        "hydraulic_power_kw": 220.78,
        "hydraulic_energy_kwh_day": 5298.72
      },
      {
        "pump_id": "p3466443",
        "curve_id": "u3466508",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 235.5,
        "flow_max_m3_h": 277.36,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 38.49,
        "hydraulic_energy_kwh_day": 923.76
      },
      {
        "pump_id": "p3466789",
        "curve_id": "u3466738",
        "run_hours_per_day": 4.1,
        "starts_per_day": 1,
        "flow_mean_m3_h": 212.17,
        "flow_max_m3_h": 212.25,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 17.92,
        "hydraulic_energy_kwh_day": 73.47
      },
      {
        "pump_id": "p3466811",
        "curve_id": "u3466738",
        "run_hours_per_day": 6.77,
        "starts_per_day": 1,
        "flow_mean_m3_h": 111.09,
        "flow_max_m3_h": 122.98,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 9.38,
        "hydraulic_energy_kwh_day": 63.5
      },
      {
        "pump_id": "p3466850",
        "curve_id": "u3466738",
        "run_hours_per_day": 13.65,
        "starts_per_day": 1,
        "flow_mean_m3_h": 253.11,
        "flow_max_m3_h": 264.01,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 21.37,
        "hydraulic_energy_kwh_day": 291.7
      },
      {
        "pump_id": "p3466871",
        "curve_id": "u3466738",
        "run_hours_per_day": 15.47,
        "starts_per_day": 1,
        "flow_mean_m3_h": 192.21,
        "flow_max_m3_h": 205.13,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 16.23,
        "hydraulic_energy_kwh_day": 251.08
      },
      {
        "pump_id": "p3466907",
        "curve_id": "u3466738",
        "run_hours_per_day": 16.6,
        "starts_per_day": 2,
        "flow_mean_m3_h": 128.54,
        "flow_max_m3_h": 157.16,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 10.85,
        "hydraulic_energy_kwh_day": 180.11
      },
      {
        "pump_id": "p3466925",
        "curve_id": "u3466738",
        "run_hours_per_day": 23.98,
        "starts_per_day": 1,
        "flow_mean_m3_h": 155.99,
        "flow_max_m3_h": 364.62,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 13.17,
        "hydraulic_energy_kwh_day": 315.82
      },
      {
        "pump_id": "p3466944",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 152.79,
        "flow_max_m3_h": 207.84,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 12.9,
        "hydraulic_energy_kwh_day": 309.6
      },
      {
        "pump_id": "p3467028",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 142.7,
        "flow_max_m3_h": 194.82,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 12.05,
        "hydraulic_energy_kwh_day": 289.2
      },
      {
        "pump_id": "p3467057",
        "curve_id": "u3466738",
        "run_hours_per_day": 17.55,
        "starts_per_day": 2,
        "flow_mean_m3_h": 55.77,
        "flow_max_m3_h": 141.51,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 4.71,
        "hydraulic_energy_kwh_day": 82.66
      },
      {
        "pump_id": "p3467077",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 63.32,
        "flow_max_m3_h": 151.66,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 5.35,
        "hydraulic_energy_kwh_day": 128.4
      },
      {
        "pump_id": "p3467096",
        "curve_id": "u3466738",
        "run_hours_per_day": 23.98,
        "starts_per_day": 1,
        "flow_mean_m3_h": 190.21,
        "flow_max_m3_h": 201.94,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 16.06,
        "hydraulic_energy_kwh_day": 385.12
      },
      {
        "pump_id": "p3467126",
        "curve_id": "u3466738",
        "run_hours_per_day": 23.98,
        "starts_per_day": 1,
        "flow_mean_m3_h": 193.83,
        "flow_max_m3_h": 205.25,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 16.37,
        "hydraulic_energy_kwh_day": 392.55
      },
      {
        "pump_id": "p3467173",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 72.9,
        "flow_max_m3_h": 157.09,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 6.16,
        "hydraulic_energy_kwh_day": 147.84
      },
      {
        "pump_id": "p3467230",
        "curve_id": "u3467232",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 177.3,
        "flow_max_m3_h": 189.99,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 16.9,
        "hydraulic_energy_kwh_day": 405.6
      },
      {
        "pump_id": "p3467255",
        "curve_id": "u3467232",
        "run_hours_per_day": 17.0,
        "starts_per_day": 2,
        "flow_mean_m3_h": 162.65,
        "flow_max_m3_h": 166.34,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 15.51,
        "hydraulic_energy_kwh_day": 263.67
      },
      {
        "pump_id": "p3467281",
        "curve_id": "u3467232",
        "run_hours_per_day": 16.67,
        "starts_per_day": 2,
        "flow_mean_m3_h": 163.42,
        "flow_max_m3_h": 167.11,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 15.58,
        "hydraulic_energy_kwh_day": 259.72
      },
      {
        "pump_id": "p3467321",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 164.82,
        "flow_max_m3_h": 164.82,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 15.71,
        "hydraulic_energy_kwh_day": 0.31
      },
      {
        "pump_id": "p3467335",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 177.16,
        "flow_max_m3_h": 177.16,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 16.89,
        "hydraulic_energy_kwh_day": 0.34
      },
      {
        "pump_id": "p3467373",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 94.1,
        "flow_max_m3_h": 94.1,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 8.97,
        "hydraulic_energy_kwh_day": 0.18
      },
      {
        "pump_id": "p3467390",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 204.92,
        "flow_max_m3_h": 204.92,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 19.54,
        "hydraulic_energy_kwh_day": 0.39
      },
      {
        "pump_id": "p3467407",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 126.64,
        "flow_max_m3_h": 126.64,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 12.07,
        "hydraulic_energy_kwh_day": 0.24
      },
      {
        "pump_id": "p3467573",
        "curve_id": "u3467560",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 204.29,
        "flow_max_m3_h": 208.34,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 33.39,
        "hydraulic_energy_kwh_day": 801.36
      },
      {
        "pump_id": "p3467585",
        "curve_id": "u3467560",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 170.33,
        "flow_max_m3_h": 174.95,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 27.84,
        "hydraulic_energy_kwh_day": 668.16
      },
      {
        "pump_id": "p3467651",
        "curve_id": "u3467560",
        "run_hours_per_day": 9.87,
        "starts_per_day": 2,
        "flow_mean_m3_h": 178.34,
        "flow_max_m3_h": 178.65,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 29.15,
        "hydraulic_energy_kwh_day": 287.71
      },
      {
        "pump_id": "p3467665",
        "curve_id": "u3467560",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 171.56,
        "flow_max_m3_h": 180.29,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 28.04,
        "hydraulic_energy_kwh_day": 672.96
      },
      {
        "pump_id": "p3467677",
        "curve_id": "u3467560",
        "run_hours_per_day": 19.95,
        "starts_per_day": 2,
        "flow_mean_m3_h": 164.5,
        "flow_max_m3_h": 170.16,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 26.89,
        "hydraulic_energy_kwh_day": 536.46
      },
      {
        "pump_id": "p3467694",
        "curve_id": "u3467560",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 182.63,
        "flow_max_m3_h": 182.63,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 29.85,
        "hydraulic_energy_kwh_day": 0.6
      },
      {
        "pump_id": "p3467707",
        "curve_id": "u3467560",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 141.51,
        "flow_max_m3_h": 141.51,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 23.13,
        "hydraulic_energy_kwh_day": 0.46
      },
      {
        "pump_id": "p3467720",
        "curve_id": "u3467560",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 151.97,
        "flow_max_m3_h": 151.97,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 24.84,
        "hydraulic_energy_kwh_day": 0.5
      },
      {
        "pump_id": "p3468154",
        "curve_id": "u3468209",
        "run_hours_per_day": 17.0,
        "starts_per_day": 1,
        "flow_mean_m3_h": 119.53,
        "flow_max_m3_h": 135.66,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 16.28,
        "hydraulic_energy_kwh_day": 276.76
      },
      {
        "pump_id": "p3468322",
        "curve_id": "u3468476",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 120.61,
        "flow_max_m3_h": 148.97,
        "tdh_head_m": 43.0,
        "hydraulic_power_kw": 14.13,
        "hydraulic_energy_kwh_day": 339.12
      },
      {
        "pump_id": "p3468325",
        "curve_id": "u3468476",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 117.57,
        "flow_max_m3_h": 144.81,
        "tdh_head_m": 43.0,
        "hydraulic_power_kw": 13.77,
        "hydraulic_energy_kwh_day": 330.48
      },
      {
        "pump_id": "p3468577",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 6.73,
        "flow_max_m3_h": 8.73,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.92,
        "hydraulic_energy_kwh_day": 22.08
      },
      {
        "pump_id": "p3468612",
        "curve_id": "u3468614",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.17,
        "flow_max_m3_h": 2.78,
        "tdh_head_m": 55.0,
        "hydraulic_power_kw": 0.33,
        "hydraulic_energy_kwh_day": 7.92
      },
      {
        "pump_id": "p3468710",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 22.7,
        "flow_max_m3_h": 26.83,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 3.09,
        "hydraulic_energy_kwh_day": 74.16
      },
      {
        "pump_id": "p3468745",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.21,
        "flow_max_m3_h": 1.55,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.07,
        "hydraulic_energy_kwh_day": 1.68
      },
      {
        "pump_id": "p3468824",
        "curve_id": "u3468818",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.84,
        "flow_max_m3_h": 2.36,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3468859",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.27,
        "flow_max_m3_h": 2.94,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.31,
        "hydraulic_energy_kwh_day": 7.44
      },
      {
        "pump_id": "p3468925",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.22,
        "flow_max_m3_h": 9.42,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.98,
        "hydraulic_energy_kwh_day": 23.52
      },
      {
        "pump_id": "p3468958",
        "curve_id": "u3468946",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.68,
        "flow_max_m3_h": 7.38,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 0.7,
        "hydraulic_energy_kwh_day": 16.8
      },
      {
        "pump_id": "p3469010",
        "curve_id": "u3468818",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.1,
        "flow_max_m3_h": 4.08,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.27,
        "hydraulic_energy_kwh_day": 6.48
      },
      {
        "pump_id": "p3469064",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.96,
        "flow_max_m3_h": 1.25,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.08,
        "hydraulic_energy_kwh_day": 1.92
      },
      {
        "pump_id": "p3469167",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.74,
        "flow_max_m3_h": 2.24,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.14,
        "hydraulic_energy_kwh_day": 3.36
      },
      {
        "pump_id": "p3469223",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.93,
        "flow_max_m3_h": 2.49,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.26,
        "hydraulic_energy_kwh_day": 6.24
      },
      {
        "pump_id": "p3469259",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.05,
        "flow_max_m3_h": 2.72,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.28,
        "hydraulic_energy_kwh_day": 6.72
      },
      {
        "pump_id": "p3469287",
        "curve_id": "u3468818",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.12,
        "flow_max_m3_h": 0.14,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.01,
        "hydraulic_energy_kwh_day": 0.24
      },
      {
        "pump_id": "p3469327",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.12,
        "flow_max_m3_h": 5.33,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.56,
        "hydraulic_energy_kwh_day": 13.44
      },
      {
        "pump_id": "p3469364",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.29,
        "flow_max_m3_h": 2.97,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.2,
        "hydraulic_energy_kwh_day": 4.8
      },
      {
        "pump_id": "p3469394",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.35,
        "flow_max_m3_h": 7.02,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.73,
        "hydraulic_energy_kwh_day": 17.52
      },
      {
        "pump_id": "p3469429",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.64,
        "flow_max_m3_h": 6.04,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.63,
        "hydraulic_energy_kwh_day": 15.12
      },
      {
        "pump_id": "p3469457",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.31,
        "flow_max_m3_h": 1.7,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.11,
        "hydraulic_energy_kwh_day": 2.64
      },
      {
        "pump_id": "p3469473",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.15,
        "flow_max_m3_h": 9.3,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.97,
        "hydraulic_energy_kwh_day": 23.28
      },
      {
        "pump_id": "p3469511",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.02,
        "flow_max_m3_h": 6.48,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.27,
        "hydraulic_energy_kwh_day": 6.48
      },
      {
        "pump_id": "p3469543",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.31,
        "flow_max_m3_h": 9.49,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.0,
        "hydraulic_energy_kwh_day": 24.0
      },
      {
        "pump_id": "p3469592",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.61,
        "flow_max_m3_h": 4.77,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.49,
        "hydraulic_energy_kwh_day": 11.76
      },
      {
        "pump_id": "p3469627",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 6.99,
        "flow_max_m3_h": 9.06,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.95,
        "hydraulic_energy_kwh_day": 22.8
      },
      {
        "pump_id": "p3469674",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.67,
        "flow_max_m3_h": 5.99,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.64,
        "hydraulic_energy_kwh_day": 15.36
      },
      {
        "pump_id": "p3469709",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.99,
        "flow_max_m3_h": 1.28,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.08,
        "hydraulic_energy_kwh_day": 1.92
      },
      {
        "pump_id": "p3469741",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.15,
        "flow_max_m3_h": 0.18,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.01,
        "hydraulic_energy_kwh_day": 0.24
      },
      {
        "pump_id": "p3469769",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.8,
        "flow_max_m3_h": 10.13,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.06,
        "hydraulic_energy_kwh_day": 25.44
      },
      {
        "pump_id": "p3469818",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.88,
        "flow_max_m3_h": 2.43,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3469842",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.2,
        "flow_max_m3_h": 6.73,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.71,
        "hydraulic_energy_kwh_day": 17.04
      },
      {
        "pump_id": "p3469868",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.83,
        "flow_max_m3_h": 4.99,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.52,
        "hydraulic_energy_kwh_day": 12.48
      },
      {
        "pump_id": "p3469892",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.4,
        "flow_max_m3_h": 1.81,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.12,
        "hydraulic_energy_kwh_day": 2.88
      },
      {
        "pump_id": "p3469923",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 8.23,
        "flow_max_m3_h": 10.67,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.12,
        "hydraulic_energy_kwh_day": 26.88
      },
      {
        "pump_id": "p3469959",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.39,
        "flow_max_m3_h": 5.6,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.6,
        "hydraulic_energy_kwh_day": 14.4
      },
      {
        "pump_id": "p3469988",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.12,
        "flow_max_m3_h": 5.38,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.56,
        "hydraulic_energy_kwh_day": 13.44
      },
      {
        "pump_id": "p3470039",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.29,
        "flow_max_m3_h": 5.18,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.58,
        "hydraulic_energy_kwh_day": 13.92
      },
      {
        "pump_id": "p3470064",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.18,
        "flow_max_m3_h": 2.84,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.3,
        "hydraulic_energy_kwh_day": 7.2
      },
      {
        "pump_id": "p3470084",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.16,
        "flow_max_m3_h": 1.5,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3470110",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.87,
        "flow_max_m3_h": 1.1,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.05,
        "hydraulic_energy_kwh_day": 1.2
      },
      {
        "pump_id": "p3470146",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.09,
        "flow_max_m3_h": 4.0,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.42,
        "hydraulic_energy_kwh_day": 10.08
      },
      {
        "pump_id": "p3470166",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.44,
        "flow_max_m3_h": 4.47,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.19,
        "hydraulic_energy_kwh_day": 4.56
      },
      {
        "pump_id": "p3470188",
        "curve_id": "u3468946",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.39,
        "flow_max_m3_h": 3.09,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 0.29,
        "hydraulic_energy_kwh_day": 6.96
      },
      {
        "pump_id": "p3470217",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.22,
        "flow_max_m3_h": 1.61,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.07,
        "hydraulic_energy_kwh_day": 1.68
      },
      {
        "pump_id": "p3470239",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 18.85,
        "flow_max_m3_h": 24.09,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 2.57,
        "hydraulic_energy_kwh_day": 61.68
      },
      {
        "pump_id": "p3470276",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.34,
        "flow_max_m3_h": 9.48,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.0,
        "hydraulic_energy_kwh_day": 24.0
      },
      {
        "pump_id": "p3470318",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.72,
        "flow_max_m3_h": 0.94,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.06,
        "hydraulic_energy_kwh_day": 1.44
      },
      {
        "pump_id": "p3470340",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.6,
        "flow_max_m3_h": 0.77,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.05,
        "hydraulic_energy_kwh_day": 1.2
      },
      {
        "pump_id": "p3470792",
        "curve_id": "u3470797",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 385.69,
        "flow_max_m3_h": 417.81,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 52.53,
        "hydraulic_energy_kwh_day": 1260.72
      },
      {
        "pump_id": "p3474053",
        "curve_id": "u3474055",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.68,
        "flow_max_m3_h": 2.18,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.23,
        "hydraulic_energy_kwh_day": 5.52
      },
      {
        "pump_id": "p3474070",
        "curve_id": "u3474055",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.02,
        "flow_max_m3_h": 1.33,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.14,
        "hydraulic_energy_kwh_day": 3.36
      },
      {
        "pump_id": "p3474146",
        "curve_id": "u3474178",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 26.43,
        "flow_max_m3_h": 34.03,
        "tdh_head_m": 80.0,
        "hydraulic_power_kw": 5.76,
        "hydraulic_energy_kwh_day": 138.24
      },
      {
        "pump_id": "p3474328",
        "curve_id": "u3474330",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.93,
        "flow_max_m3_h": 1.17,
        "tdh_head_m": 65.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3474384",
        "curve_id": "u3474330",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.33,
        "flow_max_m3_h": 1.71,
        "tdh_head_m": 65.0,
        "hydraulic_power_kw": 0.23,
        "hydraulic_energy_kwh_day": 5.52
      },
      {
        "pump_id": "p3474474",
        "curve_id": "u3474330",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.42,
        "flow_max_m3_h": 1.84,
        "tdh_head_m": 65.0,
        "hydraulic_power_kw": 0.25,
        "hydraulic_energy_kwh_day": 6.0
      },
      {
        "pump_id": "p3474632",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.43,
        "flow_max_m3_h": 1.85,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.19,
        "hydraulic_energy_kwh_day": 4.56
      }
    ]
  },
  "excess_nodes_over_60m": 0
}
```

---
## Задача 7 (`модель семей_teacher_dispatcher_shift_36a4c59dc2`)

Вопрос инженера: Объясни сменному диспетчеру особенности суточного режима сети «модель семей»: где меняет направление поток в трубах, как включаются насосы и какие узлы требуют контроля?

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "top_reverse_flow_pipes": [],
  "pumps_summary": {
    "total_pumps_declared": 127,
    "active_pumps_count": 92,
    "standby_off_pumps_count": 35,
    "total_pumped_volume_m3_day": 156377.7,
    "total_hydraulic_energy_kwh_day": 21868.55,
    "active_pumps_details": [
      {
        "pump_id": "p3381720",
        "curve_id": "u3381741",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 467.16,
        "flow_max_m3_h": 619.75,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 76.35,
        "hydraulic_energy_kwh_day": 1832.4
      },
      {
        "pump_id": "p3381996",
        "curve_id": "u3382079",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 751.1,
        "flow_max_m3_h": 863.35,
        "tdh_head_m": 62.28,
        "hydraulic_power_kw": 127.43,
        "hydraulic_energy_kwh_day": 3058.32
      },
      {
        "pump_id": "p3382208",
        "curve_id": "u3381747",
        "run_hours_per_day": 18.0,
        "starts_per_day": 2,
        "flow_mean_m3_h": 315.8,
        "flow_max_m3_h": 934.08,
        "tdh_head_m": 63.0,
        "hydraulic_power_kw": 54.2,
        "hydraulic_energy_kwh_day": 975.6
      },
      {
        "pump_id": "p3382211",
        "curve_id": "u3381747",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1286.47,
        "flow_max_m3_h": 1531.3,
        "tdh_head_m": 63.0,
        "hydraulic_power_kw": 220.78,
        "hydraulic_energy_kwh_day": 5298.72
      },
      {
        "pump_id": "p3466443",
        "curve_id": "u3466508",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 235.5,
        "flow_max_m3_h": 277.36,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 38.49,
        "hydraulic_energy_kwh_day": 923.76
      },
      {
        "pump_id": "p3466789",
        "curve_id": "u3466738",
        "run_hours_per_day": 4.1,
        "starts_per_day": 1,
        "flow_mean_m3_h": 212.17,
        "flow_max_m3_h": 212.25,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 17.92,
        "hydraulic_energy_kwh_day": 73.47
      },
      {
        "pump_id": "p3466811",
        "curve_id": "u3466738",
        "run_hours_per_day": 6.77,
        "starts_per_day": 1,
        "flow_mean_m3_h": 111.09,
        "flow_max_m3_h": 122.98,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 9.38,
        "hydraulic_energy_kwh_day": 63.5
      },
      {
        "pump_id": "p3466850",
        "curve_id": "u3466738",
        "run_hours_per_day": 13.65,
        "starts_per_day": 1,
        "flow_mean_m3_h": 253.11,
        "flow_max_m3_h": 264.01,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 21.37,
        "hydraulic_energy_kwh_day": 291.7
      },
      {
        "pump_id": "p3466871",
        "curve_id": "u3466738",
        "run_hours_per_day": 15.47,
        "starts_per_day": 1,
        "flow_mean_m3_h": 192.21,
        "flow_max_m3_h": 205.13,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 16.23,
        "hydraulic_energy_kwh_day": 251.08
      },
      {
        "pump_id": "p3466907",
        "curve_id": "u3466738",
        "run_hours_per_day": 16.6,
        "starts_per_day": 2,
        "flow_mean_m3_h": 128.54,
        "flow_max_m3_h": 157.16,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 10.85,
        "hydraulic_energy_kwh_day": 180.11
      },
      {
        "pump_id": "p3466925",
        "curve_id": "u3466738",
        "run_hours_per_day": 23.98,
        "starts_per_day": 1,
        "flow_mean_m3_h": 155.99,
        "flow_max_m3_h": 364.62,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 13.17,
        "hydraulic_energy_kwh_day": 315.82
      },
      {
        "pump_id": "p3466944",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 152.79,
        "flow_max_m3_h": 207.84,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 12.9,
        "hydraulic_energy_kwh_day": 309.6
      },
      {
        "pump_id": "p3467028",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 142.7,
        "flow_max_m3_h": 194.82,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 12.05,
        "hydraulic_energy_kwh_day": 289.2
      },
      {
        "pump_id": "p3467057",
        "curve_id": "u3466738",
        "run_hours_per_day": 17.55,
        "starts_per_day": 2,
        "flow_mean_m3_h": 55.77,
        "flow_max_m3_h": 141.51,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 4.71,
        "hydraulic_energy_kwh_day": 82.66
      },
      {
        "pump_id": "p3467077",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 63.32,
        "flow_max_m3_h": 151.66,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 5.35,
        "hydraulic_energy_kwh_day": 128.4
      },
      {
        "pump_id": "p3467096",
        "curve_id": "u3466738",
        "run_hours_per_day": 23.98,
        "starts_per_day": 1,
        "flow_mean_m3_h": 190.21,
        "flow_max_m3_h": 201.94,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 16.06,
        "hydraulic_energy_kwh_day": 385.12
      },
      {
        "pump_id": "p3467126",
        "curve_id": "u3466738",
        "run_hours_per_day": 23.98,
        "starts_per_day": 1,
        "flow_mean_m3_h": 193.83,
        "flow_max_m3_h": 205.25,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 16.37,
        "hydraulic_energy_kwh_day": 392.55
      },
      {
        "pump_id": "p3467173",
        "curve_id": "u3466738",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 72.9,
        "flow_max_m3_h": 157.09,
        "tdh_head_m": 31.0,
        "hydraulic_power_kw": 6.16,
        "hydraulic_energy_kwh_day": 147.84
      },
      {
        "pump_id": "p3467230",
        "curve_id": "u3467232",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 177.3,
        "flow_max_m3_h": 189.99,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 16.9,
        "hydraulic_energy_kwh_day": 405.6
      },
      {
        "pump_id": "p3467255",
        "curve_id": "u3467232",
        "run_hours_per_day": 17.0,
        "starts_per_day": 2,
        "flow_mean_m3_h": 162.65,
        "flow_max_m3_h": 166.34,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 15.51,
        "hydraulic_energy_kwh_day": 263.67
      },
      {
        "pump_id": "p3467281",
        "curve_id": "u3467232",
        "run_hours_per_day": 16.67,
        "starts_per_day": 2,
        "flow_mean_m3_h": 163.42,
        "flow_max_m3_h": 167.11,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 15.58,
        "hydraulic_energy_kwh_day": 259.72
      },
      {
        "pump_id": "p3467321",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 164.82,
        "flow_max_m3_h": 164.82,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 15.71,
        "hydraulic_energy_kwh_day": 0.31
      },
      {
        "pump_id": "p3467335",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 177.16,
        "flow_max_m3_h": 177.16,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 16.89,
        "hydraulic_energy_kwh_day": 0.34
      },
      {
        "pump_id": "p3467373",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 94.1,
        "flow_max_m3_h": 94.1,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 8.97,
        "hydraulic_energy_kwh_day": 0.18
      },
      {
        "pump_id": "p3467390",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 204.92,
        "flow_max_m3_h": 204.92,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 19.54,
        "hydraulic_energy_kwh_day": 0.39
      },
      {
        "pump_id": "p3467407",
        "curve_id": "u3467232",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 126.64,
        "flow_max_m3_h": 126.64,
        "tdh_head_m": 35.0,
        "hydraulic_power_kw": 12.07,
        "hydraulic_energy_kwh_day": 0.24
      },
      {
        "pump_id": "p3467573",
        "curve_id": "u3467560",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 204.29,
        "flow_max_m3_h": 208.34,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 33.39,
        "hydraulic_energy_kwh_day": 801.36
      },
      {
        "pump_id": "p3467585",
        "curve_id": "u3467560",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 170.33,
        "flow_max_m3_h": 174.95,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 27.84,
        "hydraulic_energy_kwh_day": 668.16
      },
      {
        "pump_id": "p3467651",
        "curve_id": "u3467560",
        "run_hours_per_day": 9.87,
        "starts_per_day": 2,
        "flow_mean_m3_h": 178.34,
        "flow_max_m3_h": 178.65,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 29.15,
        "hydraulic_energy_kwh_day": 287.71
      },
      {
        "pump_id": "p3467665",
        "curve_id": "u3467560",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 171.56,
        "flow_max_m3_h": 180.29,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 28.04,
        "hydraulic_energy_kwh_day": 672.96
      },
      {
        "pump_id": "p3467677",
        "curve_id": "u3467560",
        "run_hours_per_day": 19.95,
        "starts_per_day": 2,
        "flow_mean_m3_h": 164.5,
        "flow_max_m3_h": 170.16,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 26.89,
        "hydraulic_energy_kwh_day": 536.46
      },
      {
        "pump_id": "p3467694",
        "curve_id": "u3467560",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 182.63,
        "flow_max_m3_h": 182.63,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 29.85,
        "hydraulic_energy_kwh_day": 0.6
      },
      {
        "pump_id": "p3467707",
        "curve_id": "u3467560",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 141.51,
        "flow_max_m3_h": 141.51,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 23.13,
        "hydraulic_energy_kwh_day": 0.46
      },
      {
        "pump_id": "p3467720",
        "curve_id": "u3467560",
        "run_hours_per_day": 0.02,
        "starts_per_day": 1,
        "flow_mean_m3_h": 151.97,
        "flow_max_m3_h": 151.97,
        "tdh_head_m": 60.0,
        "hydraulic_power_kw": 24.84,
        "hydraulic_energy_kwh_day": 0.5
      },
      {
        "pump_id": "p3468154",
        "curve_id": "u3468209",
        "run_hours_per_day": 17.0,
        "starts_per_day": 1,
        "flow_mean_m3_h": 119.53,
        "flow_max_m3_h": 135.66,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 16.28,
        "hydraulic_energy_kwh_day": 276.76
      },
      {
        "pump_id": "p3468322",
        "curve_id": "u3468476",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 120.61,
        "flow_max_m3_h": 148.97,
        "tdh_head_m": 43.0,
        "hydraulic_power_kw": 14.13,
        "hydraulic_energy_kwh_day": 339.12
      },
      {
        "pump_id": "p3468325",
        "curve_id": "u3468476",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 117.57,
        "flow_max_m3_h": 144.81,
        "tdh_head_m": 43.0,
        "hydraulic_power_kw": 13.77,
        "hydraulic_energy_kwh_day": 330.48
      },
      {
        "pump_id": "p3468577",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 6.73,
        "flow_max_m3_h": 8.73,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.92,
        "hydraulic_energy_kwh_day": 22.08
      },
      {
        "pump_id": "p3468612",
        "curve_id": "u3468614",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.17,
        "flow_max_m3_h": 2.78,
        "tdh_head_m": 55.0,
        "hydraulic_power_kw": 0.33,
        "hydraulic_energy_kwh_day": 7.92
      },
      {
        "pump_id": "p3468710",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 22.7,
        "flow_max_m3_h": 26.83,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 3.09,
        "hydraulic_energy_kwh_day": 74.16
      },
      {
        "pump_id": "p3468745",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.21,
        "flow_max_m3_h": 1.55,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.07,
        "hydraulic_energy_kwh_day": 1.68
      },
      {
        "pump_id": "p3468824",
        "curve_id": "u3468818",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.84,
        "flow_max_m3_h": 2.36,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3468859",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.27,
        "flow_max_m3_h": 2.94,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.31,
        "hydraulic_energy_kwh_day": 7.44
      },
      {
        "pump_id": "p3468925",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.22,
        "flow_max_m3_h": 9.42,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.98,
        "hydraulic_energy_kwh_day": 23.52
      },
      {
        "pump_id": "p3468958",
        "curve_id": "u3468946",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.68,
        "flow_max_m3_h": 7.38,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 0.7,
        "hydraulic_energy_kwh_day": 16.8
      },
      {
        "pump_id": "p3469010",
        "curve_id": "u3468818",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.1,
        "flow_max_m3_h": 4.08,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.27,
        "hydraulic_energy_kwh_day": 6.48
      },
      {
        "pump_id": "p3469064",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.96,
        "flow_max_m3_h": 1.25,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.08,
        "hydraulic_energy_kwh_day": 1.92
      },
      {
        "pump_id": "p3469167",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.74,
        "flow_max_m3_h": 2.24,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.14,
        "hydraulic_energy_kwh_day": 3.36
      },
      {
        "pump_id": "p3469223",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.93,
        "flow_max_m3_h": 2.49,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.26,
        "hydraulic_energy_kwh_day": 6.24
      },
      {
        "pump_id": "p3469259",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.05,
        "flow_max_m3_h": 2.72,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.28,
        "hydraulic_energy_kwh_day": 6.72
      },
      {
        "pump_id": "p3469287",
        "curve_id": "u3468818",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.12,
        "flow_max_m3_h": 0.14,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.01,
        "hydraulic_energy_kwh_day": 0.24
      },
      {
        "pump_id": "p3469327",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.12,
        "flow_max_m3_h": 5.33,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.56,
        "hydraulic_energy_kwh_day": 13.44
      },
      {
        "pump_id": "p3469364",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.29,
        "flow_max_m3_h": 2.97,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.2,
        "hydraulic_energy_kwh_day": 4.8
      },
      {
        "pump_id": "p3469394",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.35,
        "flow_max_m3_h": 7.02,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.73,
        "hydraulic_energy_kwh_day": 17.52
      },
      {
        "pump_id": "p3469429",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.64,
        "flow_max_m3_h": 6.04,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.63,
        "hydraulic_energy_kwh_day": 15.12
      },
      {
        "pump_id": "p3469457",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.31,
        "flow_max_m3_h": 1.7,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.11,
        "hydraulic_energy_kwh_day": 2.64
      },
      {
        "pump_id": "p3469473",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.15,
        "flow_max_m3_h": 9.3,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.97,
        "hydraulic_energy_kwh_day": 23.28
      },
      {
        "pump_id": "p3469511",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.02,
        "flow_max_m3_h": 6.48,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.27,
        "hydraulic_energy_kwh_day": 6.48
      },
      {
        "pump_id": "p3469543",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.31,
        "flow_max_m3_h": 9.49,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.0,
        "hydraulic_energy_kwh_day": 24.0
      },
      {
        "pump_id": "p3469592",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.61,
        "flow_max_m3_h": 4.77,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.49,
        "hydraulic_energy_kwh_day": 11.76
      },
      {
        "pump_id": "p3469627",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 6.99,
        "flow_max_m3_h": 9.06,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.95,
        "hydraulic_energy_kwh_day": 22.8
      },
      {
        "pump_id": "p3469674",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.67,
        "flow_max_m3_h": 5.99,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.64,
        "hydraulic_energy_kwh_day": 15.36
      },
      {
        "pump_id": "p3469709",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.99,
        "flow_max_m3_h": 1.28,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.08,
        "hydraulic_energy_kwh_day": 1.92
      },
      {
        "pump_id": "p3469741",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.15,
        "flow_max_m3_h": 0.18,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.01,
        "hydraulic_energy_kwh_day": 0.24
      },
      {
        "pump_id": "p3469769",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.8,
        "flow_max_m3_h": 10.13,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.06,
        "hydraulic_energy_kwh_day": 25.44
      },
      {
        "pump_id": "p3469818",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.88,
        "flow_max_m3_h": 2.43,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3469842",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 5.2,
        "flow_max_m3_h": 6.73,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.71,
        "hydraulic_energy_kwh_day": 17.04
      },
      {
        "pump_id": "p3469868",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.83,
        "flow_max_m3_h": 4.99,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.52,
        "hydraulic_energy_kwh_day": 12.48
      },
      {
        "pump_id": "p3469892",
        "curve_id": "u3469084",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.4,
        "flow_max_m3_h": 1.81,
        "tdh_head_m": 32.0,
        "hydraulic_power_kw": 0.12,
        "hydraulic_energy_kwh_day": 2.88
      },
      {
        "pump_id": "p3469923",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 8.23,
        "flow_max_m3_h": 10.67,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.12,
        "hydraulic_energy_kwh_day": 26.88
      },
      {
        "pump_id": "p3469959",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.39,
        "flow_max_m3_h": 5.6,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.6,
        "hydraulic_energy_kwh_day": 14.4
      },
      {
        "pump_id": "p3469988",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.12,
        "flow_max_m3_h": 5.38,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.56,
        "hydraulic_energy_kwh_day": 13.44
      },
      {
        "pump_id": "p3470039",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 4.29,
        "flow_max_m3_h": 5.18,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.58,
        "hydraulic_energy_kwh_day": 13.92
      },
      {
        "pump_id": "p3470064",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.18,
        "flow_max_m3_h": 2.84,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.3,
        "hydraulic_energy_kwh_day": 7.2
      },
      {
        "pump_id": "p3470084",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.16,
        "flow_max_m3_h": 1.5,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3470110",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.87,
        "flow_max_m3_h": 1.1,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.05,
        "hydraulic_energy_kwh_day": 1.2
      },
      {
        "pump_id": "p3470146",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.09,
        "flow_max_m3_h": 4.0,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.42,
        "hydraulic_energy_kwh_day": 10.08
      },
      {
        "pump_id": "p3470166",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 3.44,
        "flow_max_m3_h": 4.47,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.19,
        "hydraulic_energy_kwh_day": 4.56
      },
      {
        "pump_id": "p3470188",
        "curve_id": "u3468946",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 2.39,
        "flow_max_m3_h": 3.09,
        "tdh_head_m": 45.0,
        "hydraulic_power_kw": 0.29,
        "hydraulic_energy_kwh_day": 6.96
      },
      {
        "pump_id": "p3470217",
        "curve_id": "u3468759",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.22,
        "flow_max_m3_h": 1.61,
        "tdh_head_m": 20.0,
        "hydraulic_power_kw": 0.07,
        "hydraulic_energy_kwh_day": 1.68
      },
      {
        "pump_id": "p3470239",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 18.85,
        "flow_max_m3_h": 24.09,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 2.57,
        "hydraulic_energy_kwh_day": 61.68
      },
      {
        "pump_id": "p3470276",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 7.34,
        "flow_max_m3_h": 9.48,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 1.0,
        "hydraulic_energy_kwh_day": 24.0
      },
      {
        "pump_id": "p3470318",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.72,
        "flow_max_m3_h": 0.94,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.06,
        "hydraulic_energy_kwh_day": 1.44
      },
      {
        "pump_id": "p3470340",
        "curve_id": "u3469184",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.6,
        "flow_max_m3_h": 0.77,
        "tdh_head_m": 30.0,
        "hydraulic_power_kw": 0.05,
        "hydraulic_energy_kwh_day": 1.2
      },
      {
        "pump_id": "p3470792",
        "curve_id": "u3470797",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 385.69,
        "flow_max_m3_h": 417.81,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 52.53,
        "hydraulic_energy_kwh_day": 1260.72
      },
      {
        "pump_id": "p3474053",
        "curve_id": "u3474055",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.68,
        "flow_max_m3_h": 2.18,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.23,
        "hydraulic_energy_kwh_day": 5.52
      },
      {
        "pump_id": "p3474070",
        "curve_id": "u3474055",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.02,
        "flow_max_m3_h": 1.33,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.14,
        "hydraulic_energy_kwh_day": 3.36
      },
      {
        "pump_id": "p3474146",
        "curve_id": "u3474178",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 26.43,
        "flow_max_m3_h": 34.03,
        "tdh_head_m": 80.0,
        "hydraulic_power_kw": 5.76,
        "hydraulic_energy_kwh_day": 138.24
      },
      {
        "pump_id": "p3474328",
        "curve_id": "u3474330",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 0.93,
        "flow_max_m3_h": 1.17,
        "tdh_head_m": 65.0,
        "hydraulic_power_kw": 0.16,
        "hydraulic_energy_kwh_day": 3.84
      },
      {
        "pump_id": "p3474384",
        "curve_id": "u3474330",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.33,
        "flow_max_m3_h": 1.71,
        "tdh_head_m": 65.0,
        "hydraulic_power_kw": 0.23,
        "hydraulic_energy_kwh_day": 5.52
      },
      {
        "pump_id": "p3474474",
        "curve_id": "u3474330",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.42,
        "flow_max_m3_h": 1.84,
        "tdh_head_m": 65.0,
        "hydraulic_power_kw": 0.25,
        "hydraulic_energy_kwh_day": 6.0
      },
      {
        "pump_id": "p3474632",
        "curve_id": "u3468555",
        "run_hours_per_day": 24.0,
        "starts_per_day": 0,
        "flow_mean_m3_h": 1.43,
        "flow_max_m3_h": 1.85,
        "tdh_head_m": 50.0,
        "hydraulic_power_kw": 0.19,
        "hydraulic_energy_kwh_day": 4.56
      }
    ]
  },
  "worst_deficit_nodes": []
}
```

---
## Задача 8 (`модель семей_teacher_schema_quality_cf3b05d778`)

Вопрос инженера: Проверь качество расчётной схемы «модель семей» после удаления нулевых строк: сколько транзитных узлов и резервных насосов отфильтровано и есть ли ошибки топологии Начало==Конец?

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 21004,
    "pruned_standby_pumps_count": 35,
    "pruned_zero_consumers_count": 20927
  },
  "schedules_summary": {
    "schedules_count": 5,
    "all_24_hours_valid": false,
    "max_peaking_factor_k_max": 1.5,
    "min_night_factor_k_min": 0.2
  },
  "self_loop_topology_pipes_count": 0,
  "data_quality_flags": [
    "В исходной таблице Узел.csv города «модель семей» на всех узлах стояло Требуемое давление = 0 (нормативная этажность не задавалась автором модели); показатели водоразбора и напоров собраны по фактическим узлам-абонентам",
    "В График потребления.csv найдено 2 графиков с числом точек != 24"
  ]
}
```

---
## Задача 9 (`модель семей_teacher_refusal_trap_b0d748fcf7`)

Вопрос инженера: Рассчитай для водоканала «модель семей» годовую экономию в рублях при замене насосов, их фактический электрический КПД и остаточный хлор на крайних узлах.

Факты расчёта (facts_inline):
```json
{
  "city_name": "модель семей",
  "pumps_summary": {
    "active_pumps_count": 92,
    "total_hydraulic_energy_kwh_day": 21868.55
  }
}
```
