# Пакет задач для разметки Моделью-Учителем (город: хорезмская)

**Системная инструкция Учителю:**
> Ты — главный инженер-гидравлик систем водоснабжения (уровня авторов руководства Walski et al. 'Advanced Water Distribution Modeling and Management' и СП 31.13330.2021). Напиши глубокий, живой, профессиональный инженерный ответ для обучения младшей локальной модели EPANET-AI.

ЖЕЛЕЗНЫЕ ПРАВИЛА ДИСТИЛЛЯЦИИ (нарушение бракует пример!):
1. Опирайся ИСКЛЮЧИТЕЛЬНО на переданный JSON `facts_inline`.
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО считать в уме (не вычисляй проценты, разности или суммы, которых нет в JSON) и запрещено писать любые числа, отсутствующие во входном `facts_inline` (разрешены только константы нормативов: 10 м и +4 м на этаж по СП 31.13330.2021, 60 м макс. напор, 0.3 / 1.5 / 3.0 м/с скорости по Walski, 24 ч, 1440 шагов).
3. Обязательно указывай конкретные строковые ID узлов (c*), труб (e*), насосов (p*), кривых (u*, t*) и объясняй физику процессов.
4. Если спрашивают данные, которых нет в `facts_inline` (КПД двигателя, тариф в рублях, остаточный хлор), чётко перечисли недостающие таблицы и НЕ выдумывай оценочных цифр.

---
## Задача 1 (`хорезмская_teacher_exec_memo_97bb41beb4`)

Вопрос инженера: Подготовь аналитическую записку главному инженеру водоканала по расчёту сети «хорезмская»: оцени баланс, главные гидравлические риски и очерёдность мероприятий.

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
  "zero_cleaning_summary": {
    "pruned_transit_nodes_count": 0,
    "pruned_standby_pumps_count": 0,
    "pruned_zero_consumers_count": 0
  },
  "nodes_overview": {
    "consumer_nodes_count": 8007,
    "total_daily_consumption_m3_day": 176116.21,
    "sum_peak_node_demand_m3_h": 14263.69,
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
    "total_pumps_declared": 0,
    "active_pumps_count": 0,
    "standby_off_pumps_count": 0,
    "total_pumped_volume_m3_day": 0.0,
    "total_hydraulic_energy_kwh_day": 0.0
  },
  "data_quality_flags": [
    "В исходной таблице Узел.csv города «хорезмская» на всех узлах стояло Требуемое давление = 0 (нормативная этажность не задавалась автором модели); показатели водоразбора и напоров собраны по фактическим узлам-абонентам"
  ]
}
```

---
## Задача 2 (`хорезмская_teacher_tu_developer_e6f2f1c163`)

Вопрос инженера: Застройщик просит техусловия на подключение нового жилого дома в городе «хорезмская». Судя по свободным напорам и этажности существующих узлов, какие ограничения и риски просадки давления есть в сети?

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
  "nodes_summary": {
    "consumer_nodes_count": 8007,
    "total_daily_consumption_m3_day": 176116.21,
    "sum_peak_node_demand_m3_h": 14263.69,
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
## Задача 3 (`хорезмская_teacher_prv_zoning_ab7e02cfa7`)

Вопрос инженера: Проанализируй зоны минимального и избыточного (>60 м) свободного напора в «хорезмская». Где целесообразно зонирование сети или установка регуляторов давления PRV?

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
  "nodes_summary": {
    "consumer_nodes_count": 8007,
    "total_daily_consumption_m3_day": 176116.21,
    "sum_peak_node_demand_m3_h": 14263.69,
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
## Задача 4 (`хорезмская_teacher_water_hammer_f6c3e2909c`)

Вопрос инженера: Оцени трубопроводы города «хорезмская» по критериям книги Walski: какие участки работают с повышенной скоростью, риском гидравлического удара (>3.0 м/с) и частыми реверсами потока?

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
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
## Задача 5 (`хорезмская_teacher_stagnation_flushing_4fa1069392`)

Вопрос инженера: Выдели застойные участки сети «хорезмская» со скоростью ниже 0.3 м/с и большим временем пробега воды. Как это влияет на качество воды и где нужна промывка или переключение задвижек?

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
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
## Задача 6 (`хорезмская_teacher_pump_vfd_audit_6c905c62a3`)

Вопрос инженера: Проведи энергоаудит насосов модели «хорезмская»: сколько агрегатов в резерве, какова наработка, число пусков и полезная гидравлическая мощность? Оцени целесообразность ЧРП.

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
  "pumps_summary": {
    "total_pumps_declared": 0,
    "active_pumps_count": 0,
    "standby_off_pumps_count": 0,
    "total_pumped_volume_m3_day": 0.0,
    "total_hydraulic_energy_kwh_day": 0.0,
    "active_pumps_details": []
  },
  "excess_nodes_over_60m": 0
}
```

---
## Задача 7 (`хорезмская_teacher_dispatcher_shift_46158be1f7`)

Вопрос инженера: Объясни сменному диспетчеру особенности суточного режима сети «хорезмская»: где меняет направление поток в трубах, как включаются насосы и какие узлы требуют контроля?

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
  "top_reverse_flow_pipes": [],
  "pumps_summary": {
    "total_pumps_declared": 0,
    "active_pumps_count": 0,
    "standby_off_pumps_count": 0,
    "total_pumped_volume_m3_day": 0.0,
    "total_hydraulic_energy_kwh_day": 0.0,
    "active_pumps_details": []
  },
  "worst_deficit_nodes": []
}
```

---
## Задача 8 (`хорезмская_teacher_schema_quality_716abb1cd3`)

Вопрос инженера: Проверь качество расчётной схемы «хорезмская» после удаления нулевых строк: сколько транзитных узлов и резервных насосов отфильтровано и есть ли ошибки топологии Начало==Конец?

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
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
  "data_quality_flags": [
    "В исходной таблице Узел.csv города «хорезмская» на всех узлах стояло Требуемое давление = 0 (нормативная этажность не задавалась автором модели); показатели водоразбора и напоров собраны по фактическим узлам-абонентам"
  ]
}
```

---
## Задача 9 (`хорезмская_teacher_refusal_trap_318dc17a5e`)

Вопрос инженера: Рассчитай для водоканала «хорезмская» годовую экономию в рублях при замене насосов, их фактический электрический КПД и остаточный хлор на крайних узлах.

Факты расчёта (facts_inline):
```json
{
  "city_name": "хорезмская",
  "pumps_summary": {
    "active_pumps_count": 0,
    "total_hydraulic_energy_kwh_day": 0.0
  }
}
```
