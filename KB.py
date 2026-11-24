import random
from collections import namedtuple

Participant = None

SensorData = namedtuple('SensorData', [
    'time',      # sensor_time - время суток (0-23)
    'solar',     # sensor_solar - выработка солнечных панелей (0-200)
    'wind',      # sensor_wind - выработка ветрогенераторов (0-200)
    'battery',   # sensor_battery - уровень заряда накопителя (0-100)
    'houses',    # sensor_houses - потребление домов (0-100)
    'hospital',  # sensor_hospital - потребление больницы (0-100)
    'school',    # sensor_school - потребление школы (0-100)
    'factory'    # sensor_factory - потребление завода (0-100)
])

SwitchState = namedtuple('SwitchState', [
    'K_SOLAR',   # bool - подключение солнечных панелей
    'K_WIND',    # bool - подключение ветрогенераторов
    'K_GES',     # bool - подключение ГЭС
    'K_BAT',     # str - режим накопителя: 'charge', 'discharge', 'idle', 'stop'
    'K_HSE',     # bool - питание домов
    'K_HSP',     # bool - питание больницы
    'K_SCH',     # bool - питание школы
    'K_FAC'      # bool - питание завода
])

GlobalParams = namedtuple('GlobalParams', [
    'time',           # время суток (0-23)
    'solar_available',# наличие солнца (погода)
    'wind_strength',  # сила ветра (0-100)
    'battery_level'   # уровень заряда накопителя (0-100)
])

Compromised = set()

# ============================================================
# КОНСТАНТЫ ДЛЯ ЛОГИКИ КООРДИНАТОРА
# ============================================================
BATTERY_CRITICAL = 10   # ниже этого уровня — запрет разряда (глубокий разряд)
BATTERY_SAFE     = 30   # выше этого уровня — разрешён разряд в safe_control
BATTERY_FULL     = 95   # выше — не заряжаем
SCHOOL_START     = 8    # начало рабочего времени школы
SCHOOL_END       = 15   # конец рабочего времени школы
SUNRISE          = 6    # рассвет
SUNSET           = 18   # закат

# Физические ограничения для валидации показаний датчиков
PHYS_LIMITS = {
    'solar':    (0, 200),
    'wind':     (0, 200),
    'battery':  (0, 100),
    'houses':   (0, 100),
    'hospital': (5, 100),   # больница не может потреблять 0
    'school':   (0, 100),
    'factory':  (0, 100),
}

# Консервативные (пессимистичные) замены для скомпрометированных датчиков
FALLBACK_VALUES = {
    'solar':    0,
    'wind':     0,
    'battery':  0,
    'houses':   40,
    'hospital': 20,
    'school':   20,
    'factory':  30,
}


def get_sensors(params):
    """
    Эмуляция получения данных от всех датчиков
    params: GlobalParams с текущими параметрами
    Возвращает SensorData с учетом глобальных переменных и компрометации
    """
    def get_sensor_value(field_name, real_value_func):
        if field_name not in Compromised:
            return real_value_func()
        else:
            # Скомпрометированный датчик - может давать ложные показания
            return random.uniform(0, 100)

    def real_time():
        return params.time

    def real_solar():
        if SUNRISE <= params.time <= SUNSET and params.solar_available:
            return random.uniform(40, 200)
        else:
            return random.uniform(0, 20)

    def real_wind():
        return random.uniform(max(0, params.wind_strength - 20),
                              min(200, params.wind_strength * 2))

    def real_battery():
        return params.battery_level

    def real_houses():
        return random.uniform(20, 60)

    def real_hospital():
        return random.uniform(10, 20)

    def real_school():
        if SCHOOL_START <= params.time <= SCHOOL_END:
            return random.uniform(15, 30)
        else:
            return random.uniform(0, 5)

    def real_factory():
        return random.uniform(20, 50)

    return SensorData(
        time=get_sensor_value('time', real_time),
        solar=get_sensor_value('solar', real_solar),
        wind=get_sensor_value('wind', real_wind),
        battery=get_sensor_value('battery', real_battery),
        houses=get_sensor_value('houses', real_houses),
        hospital=get_sensor_value('hospital', real_hospital),
        school=get_sensor_value('school', real_school),
        factory=get_sensor_value('factory', real_factory)
    )


# ============================================================
# ЗАДАЧА 1. Штатный режим работы координатора
# ============================================================
def control(sensors):
    """
    Базовая логика координатора.
    Приоритеты (по убыванию):
      1. Больница — всегда 100% питания
      2. Школа — в рабочее время (8–15)
      3. Защита АКБ от глубокого разряда и разряда без нагрузки
      4. Дома
      5. Завод
    ГЭС не используется — цель энергоэффективности.
    """
    t = sensors.time
    is_day = SUNRISE <= t <= SUNSET
    is_school_hours = SCHOOL_START <= t <= SCHOOL_END

    # ---------- Генерация ----------
    # Солнце и ветер — «бесплатная» энергия, подключаем всегда, если есть выработка
    K_SOLAR = is_day and sensors.solar > 15
    K_WIND  = sensors.wind > 15
    K_GES   = False  # не используем по условию энергоэффективности

    # Оценочная генерация (условные кВт)
    gen = 0.0
    if K_SOLAR:
        gen += sensors.solar * 0.5
    if K_WIND:
        gen += sensors.wind * 0.4

    # ---------- Потребление (приоритетное) ----------
    P_HOSP = sensors.hospital                          # всегда
    P_SCH  = sensors.school if is_school_hours else 0  # только днём
    P_HSE  = sensors.houses
    P_FAC  = sensors.factory

    total_need = P_HOSP + P_SCH + P_HSE + P_FAC
    deficit = total_need - gen  # >0 — не хватает, <0 — избыток

    # ---------- Режим накопителя ----------
    bat = sensors.battery
    if deficit > 0:
        # нужен разряд, но защищаем АКБ от глубокого разряда
        if bat > BATTERY_CRITICAL:
            K_BAT = 'discharge'
        else:
            K_BAT = 'stop'  # принудительная остановка — защита от деградации
    elif deficit < -20 and bat < BATTERY_FULL:
        K_BAT = 'charge'
    else:
        K_BAT = 'idle'

    # ---------- Подключение потребителей ----------
    K_HSP = True   # больница — всегда (приоритет №1)
    K_SCH = is_school_hours and (K_BAT != 'stop')
    K_HSE = (K_BAT != 'stop')
    K_FAC = (K_BAT != 'stop') and (deficit <= 0)  # завод — только при избытке

    # В режиме stop отключаем всё, кроме больницы
    if K_BAT == 'stop':
        K_HSE = False
        K_SCH = False
        K_FAC = False

    return SwitchState(
        K_SOLAR=K_SOLAR, K_WIND=K_WIND, K_GES=K_GES, K_BAT=K_BAT,
        K_HSE=K_HSE, K_HSP=K_HSP, K_SCH=K_SCH, K_FAC=K_FAC
    )


# ============================================================
# ЗАДАЧА 2. Кибериммунная версия (защита от компрометации)
# ============================================================
def safe_control(sensors):
    """
    Кибериммунная логика координатора.
    Проверяет показания датчиков на физическую и логическую
    согласованность. Ложные/аномальные данные заменяются
    консервативными оценками, после чего применяется та же
    приоритетная логика, но с более осторожными порогами.
    """
    t = sensors.time
    is_day = SUNRISE <= t <= SUNSET
    is_school_hours = SCHOOL_START <= t <= SCHOOL_END

    # ---------- 1. Валидация физических диапазонов ----------
    def safe_val(name, raw):
        lo, hi = PHYS_LIMITS[name]
        if not (lo <= raw <= hi):
            return None  # аномалия
        return raw

    s_solar    = safe_val('solar',    sensors.solar)
    s_wind     = safe_val('wind',     sensors.wind)
    s_battery  = safe_val('battery',  sensors.battery)
    s_hospital = safe_val('hospital', sensors.hospital)
    s_school   = safe_val('school',   sensors.school)
    s_houses   = safe_val('houses',   sensors.houses)
    s_factory  = safe_val('factory',  sensors.factory)

    # ---------- 2. Логические инварианты ----------
    # Солнце ночью не светит — большое значение = компрометация
    if not is_day and s_solar is not None and s_solar > 25:
        s_solar = None
    # Больница не может потреблять 0 — это критичная аномалия
    if s_hospital is not None and s_hospital < 5:
        s_hospital = None
    # Время не может быть вне диапазона 0–23
    if not (0 <= sensors.time <= 23):
        # используем безопасное «дневное» значение для расчётов
        is_day = True
        is_school_hours = True

    # ---------- 3. Консервативные замены ----------
    solar_eff    = s_solar    if s_solar    is not None else FALLBACK_VALUES['solar']
    wind_eff     = s_wind     if s_wind     is not None else FALLBACK_VALUES['wind']
    battery_eff  = s_battery  if s_battery  is not None else FALLBACK_VALUES['battery']
    hospital_eff = s_hospital if s_hospital is not None else FALLBACK_VALUES['hospital']
    school_eff   = s_school   if s_school   is not None else FALLBACK_VALUES['school']
    houses_eff   = s_houses   if s_houses   is not None else FALLBACK_VALUES['houses']
    factory_eff  = s_factory  if s_factory  is not None else FALLBACK_VALUES['factory']

    # ---------- 4. Управление по тем же приоритетам ----------
    K_SOLAR = is_day and solar_eff > 15
    K_WIND  = wind_eff > 15
    K_GES   = False

    gen = 0.0
    if K_SOLAR:
        gen += solar_eff * 0.5
    if K_WIND:
        gen += wind_eff * 0.4

    P_HOSP = hospital_eff
    P_SCH  = school_eff if is_school_hours else 0
    P_HSE  = houses_eff
    P_FAC  = factory_eff

    total_need = P_HOSP + P_SCH + P_HSE + P_FAC
    deficit = total_need - gen

    # Более осторожная политика АКБ при компрометации
    if deficit > 0:
        if battery_eff > BATTERY_SAFE:
            K_BAT = 'discharge'
        elif battery_eff > BATTERY_CRITICAL:
            K_BAT = 'idle'    # не разряжаем, но и не заряжаем — ждём данных
        else:
            K_BAT = 'stop'
    elif deficit < -20 and battery_eff < 90:
        K_BAT = 'charge'
    else:
        K_BAT = 'idle'

    K_HSP = True
    K_SCH = is_school_hours and (K_BAT != 'stop')
    K_HSE = (K_BAT != 'stop')
    K_FAC = (K_BAT != 'stop') and (deficit <= 0)

    if K_BAT == 'stop':
        K_HSE = False
        K_SCH = False
        K_FAC = False

    return SwitchState(
        K_SOLAR=K_SOLAR, K_WIND=K_WIND, K_GES=K_GES, K_BAT=K_BAT,
        K_HSE=K_HSE, K_HSP=K_HSP, K_SCH=K_SCH, K_FAC=K_FAC
    )


# ============================================================
# ПРОВЕРКА ЦЕЛЕЙ БЕЗОПАСНОСТИ (без изменений)
# ============================================================
def check_safety_goals(switches, params):
    """
    Проверка выполнения целей безопасности
    Возвращает список [goal1_ok, goal2_ok, goal3_ok]
    где каждый элемент - True если цель выполнена, False если нарушена
    """
    # Цель 1: Больница всегда должна быть включена
    goal1_ok = switches.K_HSP

    # Цель 2: Школа в рабочее время (8-15) должна быть включена
    is_school_hours = SCHOOL_START <= params.time <= SCHOOL_END
    if is_school_hours:
        goal2_ok = switches.K_SCH
    else:
        goal2_ok = True  # Ночью школа может быть отключена

    # Цель 3: Защита накопителя
    bat_mode = switches.K_BAT
    goal3_ok = True

    # Не допускаем разряд при низком уровне
    if params.battery_level < BATTERY_CRITICAL and bat_mode == 'discharge':
        goal3_ok = False

    # Не допускаем разряд в никуда (discharge при отключенных потребителях)
    total_consumption = 0
    if switches.K_HSP:
        total_consumption += 10
    if switches.K_SCH:
        total_consumption += 8
    if switches.K_HSE:
        total_consumption += 30
    if switches.K_FAC:
        total_consumption += 25
    if bat_mode == 'discharge' and total_consumption == 0:
        goal3_ok = False

    return [goal1_ok, goal2_ok, goal3_ok]


def evaluate_safety(switches_list, params_list):
    """
    Оценивает безопасность решений для списка сценариев
    Возвращает количество нарушений и детальную статистику
    """
    total_violations = 0
    violations_count = [0, 0, 0]  # [goal1, goal2, goal3]
    for switches, params in zip(switches_list, params_list):
        goal_status = check_safety_goals(switches, params)
        for i, status in enumerate(goal_status):
            if not status:
                violations_count[i] += 1
                total_violations += 1
    return total_violations, violations_count


# ============================================================
# ФОРМИРОВАНИЕ ТАБЛИЦ РЕЗУЛЬТАТОВ (без изменений)
# ============================================================
def print_table(sensors_list, switches_list, params_list, scenario_name,
                goals_status_list=None, compromised_list=None):
    """
    Формирует таблицу решений для нескольких сценариев без использования tabulate
    """
    print(f"\n=== {scenario_name} ===")
    headers = ["Параметры"] + [f"Сит {i+1}" for i in range(len(sensors_list))]

    col_width = 12
    separator = "+" + "-" * col_width + "+" + "+".join(["-" * col_width] * len(sensors_list)) + "+"
    print(separator)
    header_line = f"|{headers[0]:^{col_width}}"
    for h in headers[1:]:
        header_line += f"|{h:^{col_width}}"
    print(header_line + "|")
    print(separator)

    param_rows = [
        ("TIME", []),
        ("SOLAR_AVAIL", []),
        ("WIND_STR", []),
        ("BATTERY", [])
    ]
    for params in params_list:
        param_rows[0][1].append(f"{params.time}")
        param_rows[1][1].append("да" if params.solar_available else "нет")
        param_rows[2][1].append(f"{params.wind_strength}")
        param_rows[3][1].append(f"{params.battery_level}")

    for row_name, values in param_rows:
        line = f"|{row_name:^{col_width}}"
        for v in values:
            line += f"|{v:^{col_width}}"
        print(line + "|")
    print(separator)

    condition_rows = [
        ("Время", []),
        ("Солнце", []),
        ("Ветер", []),
        ("Запас", []),
        ("Дома", []),
        ("Больница", []),
        ("Школа", []),
        ("Завод", [])
    ]

    for idx, sensors in enumerate(sensors_list):
        hour = sensors.time
        condition_rows[0][1].append("день" if SUNRISE <= hour <= SUNSET else "ночь")

        solar = sensors.solar
        compromised = compromised_list and compromised_list[idx] if compromised_list else set()
        solar_str = ""
        if solar > 60:
            solar_str = "светит"
        elif solar > 20:
            solar_str = "пасмурно"
        else:
            solar_str = "нет"
        if 'solar' in compromised:
            solar_str += "!"
        condition_rows[1][1].append(solar_str)

        wind = sensors.wind
        wind_str = ""
        if wind > 120:
            wind_str = "сильный"
        elif wind > 40:
            wind_str = "средний"
        else:
            wind_str = "слабый"
        if 'wind' in compromised:
            wind_str += "!"
        condition_rows[2][1].append(wind_str)

        battery = sensors.battery
        battery_str = ""
        if battery > 70:
            battery_str = "высокий"
        elif battery > 30:
            battery_str = "средний"
        elif battery > BATTERY_CRITICAL:
            battery_str = "низкий"
        else:
            battery_str = "критич"
        if 'battery' in compromised:
            battery_str += "!"
        condition_rows[3][1].append(battery_str)

        houses_str = f"{sensors.houses:.0f}"
        if 'houses' in compromised:
            houses_str += "!"
        condition_rows[4][1].append(houses_str)

        hospital_str = f"{sensors.hospital:.0f}"
        if 'hospital' in compromised:
            hospital_str += "!"
        condition_rows[5][1].append(hospital_str)

        school_str = f"{sensors.school:.0f}"
        if 'school' in compromised:
            school_str += "!"
        condition_rows[6][1].append(school_str)

        factory_str = f"{sensors.factory:.0f}"
        if 'factory' in compromised:
            factory_str += "!"
        condition_rows[7][1].append(factory_str)

    for row_name, values in condition_rows:
        line = f"|{row_name:^{col_width}}"
        for v in values:
            line += f"|{v:^{col_width}}"
        print(line + "|")
    print(separator)

    result_rows = [
        ("K_SOLAR", []),
        ("K_WIND", []),
        ("K_GES", []),
        ("K_BAT", []),
        ("K_HSE", []),
        ("K_HSP", []),
        ("K_SCH", []),
        ("K_FAC", [])
    ]
    for switches in switches_list:
        result_rows[0][1].append("+" if switches.K_SOLAR else "-")
        result_rows[1][1].append("+" if switches.K_WIND else "-")
        result_rows[2][1].append("+" if switches.K_GES else "-")
        bat = switches.K_BAT
        if bat == 'charge':
            result_rows[3][1].append("З")
        elif bat == 'discharge':
            result_rows[3][1].append("Р")
        elif bat == 'stop':
            result_rows[3][1].append("С")
        else:
            result_rows[3][1].append("-")
        result_rows[4][1].append("+" if switches.K_HSE else "-")
        result_rows[5][1].append("+" if switches.K_HSP else "-")
        result_rows[6][1].append("+" if switches.K_SCH else "-")
        result_rows[7][1].append("+" if switches.K_FAC else "-")

    for row_name, values in result_rows:
        line = f"|{row_name:^{col_width}}"
        for v in values:
            line += f"|{v:^{col_width}}"
        print(line + "|")
    print(separator)

    if goals_status_list:
        violations_row = ["Нарушения"]
        for goals in goals_status_list:
            violated = []
            if not goals[0]:
                violated.append("1")
            if not goals[1]:
                violated.append("2")
            if not goals[2]:
                violated.append("3")
            if violated:
                violations_row.append(f"{','.join(violated)}")
            else:
                violations_row.append("-")
        line = f"|{violations_row[0]:^{col_width}}"
        for v in violations_row[1:]:
            line += f"|{v:^{col_width}}"
        print(line + "|")
        print(separator)


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ — ЗАПУСК ВСЕХ СЦЕНАРИЕВ
# ============================================================
def main():
    global Compromised

    # Фиксируем random для воспроизводимости
    # random.seed(42)

    print("\nГЕНЕРАЦИЯ ТЕСТОВЫХ СЦЕНАРИЕВ...")

    # ===== СЦЕНАРИЙ 1: Штатная работа =====
    situation_tuples_1 = [
        (12, True, 80, 85),   # Сит 1: День, солнце, сильный ветер, высокий запас
        (14, True, 20, 80),   # Сит 2: День, солнце, слабый ветер, высокий запас
        (10, False, 75, 25),  # Сит 3: День, пасмурно, сильный ветер, низкий запас
        (16, False, 15, 20),  # Сит 4: День, пасмурно, слабый ветер, низкий запас
        (2, False, 85, 90),   # Сит 5: Ночь, сильный ветер, высокий запас
        (23, False, 10, 75),  # Сит 6: Ночь, слабый ветер, высокий запас
        (3, False, 70, 15),   # Сит 7: Ночь, сильный ветер, низкий запас
        (1, False, 5, 10)     # Сит 8: Ночь, слабый ветер, низкий запас
    ]
    params_list_1 = [GlobalParams(time=t, solar_available=sa, wind_strength=ws, battery_level=bl)
                     for t, sa, ws, bl in situation_tuples_1]

    scenarios_1 = []
    compromised_list_1 = []
    for params in params_list_1:
        Compromised = set()
        compromised_list_1.append(Compromised.copy())
        scenarios_1.append(get_sensors(params))

    switches_1 = [control(s) for s in scenarios_1]
    goals_1 = [check_safety_goals(sw, params) for sw, params in zip(switches_1, params_list_1)]
    print_table(scenarios_1, switches_1, params_list_1,
                "СЦЕНАРИЙ 1: Штатная работа", goals_1, compromised_list_1)

    total_violations_1, violations_count_1 = evaluate_safety(switches_1, params_list_1)
    print(f"Оценка безопасности: {total_violations_1} нарушений")
    print(f"  Цель 1 (больница): {violations_count_1[0]} нарушений")
    print(f"  Цель 2 (школа): {violations_count_1[1]} нарушений")
    print(f"  Цель 3 (накопитель): {violations_count_1[2]} нарушений")

    # ===== СЦЕНАРИЙ 2: Дефицит энергии =====
    situation_tuples_2 = [
        (13, True, 75, 25),   # D1: День, солнце, сильный ветер, низкий запас
        (11, True, 15, 20),   # D2: День, солнце, слабый ветер, низкий запас
        (9, False, 70, 8),    # D3: День, пасмурно, сильный ветер, критический запас
        (15, False, 10, 5),   # D4: День, пасмурно, слабый ветер, критический запас
        (22, False, 80, 25),  # D5: Ночь, сильный ветер, низкий запас
        (4, False, 12, 20),   # D6: Ночь, слабый ветер, низкий запас
        (1, False, 65, 7),    # D7: Ночь, сильный ветер, критический запас
        (3, False, 8, 4)      # D8: Ночь, слабый ветер, критический запас
    ]
    params_list_2 = [GlobalParams(time=t, solar_available=sa, wind_strength=ws, battery_level=bl)
                     for t, sa, ws, bl in situation_tuples_2]

    scenarios_2 = []
    compromised_list_2 = []
    for params in params_list_2:
        Compromised = set()
        compromised_list_2.append(Compromised.copy())
        scenarios_2.append(get_sensors(params))

    switches_2 = [control(s) for s in scenarios_2]
    goals_2 = [check_safety_goals(sw, params) for sw, params in zip(switches_2, params_list_2)]
    print_table(scenarios_2, switches_2, params_list_2,
                "СЦЕНАРИЙ 2: Режим дефицита", goals_2, compromised_list_2)

    total_violations_2, violations_count_2 = evaluate_safety(switches_2, params_list_2)
    print(f"Оценка безопасности: {total_violations_2} нарушений")
    print(f"  Цель 1 (больница): {violations_count_2[0]} нарушений")
    print(f"  Цель 2 (школа): {violations_count_2[1]} нарушений")
    print(f"  Цель 3 (накопитель): {violations_count_2[2]} нарушений")

    # ===== СЦЕНАРИЙ 3: Компрометация =====
    print("\n" + "=" * 70)
    print("АКТИВАЦИЯ РЕЖИМА КОМПРОМЕТАЦИИ ДАТЧИКОВ")
    print("=" * 70)

    params_list_3 = params_list_1[:6]
    compromised_configs = [
        {'solar', 'hospital'},                    # A1: солнце и больница
        {'wind', 'school'},                       # A2: ветер и школа
        {'wind', 'hospital'},                     # A3: ветер и больница
        {'solar', 'battery', 'school'},           # A4: солнце, накопитель, школа
        {'solar', 'battery', 'hospital'},         # A5: солнце, накопитель, больница
        {'wind', 'battery', 'hospital', 'school'} # A6: все
    ]

    scenarios_3 = []
    compromised_list_3 = []
    switches_3_normal = []
    switches_3_safe = []

    for i, params in enumerate(params_list_3):
        Compromised = compromised_configs[i].copy()
        compromised_list_3.append(Compromised.copy())
        sensors = get_sensors(params)
        scenarios_3.append(sensors)
        switches_3_normal.append(control(sensors))
        switches_3_safe.append(safe_control(sensors))

    goals_normal = [check_safety_goals(sw, params) for sw, params in zip(switches_3_normal, params_list_3)]
    print_table(scenarios_3, switches_3_normal, params_list_3,
                "СЦЕНАРИЙ 3: Компрометация (обычный control)", goals_normal, compromised_list_3)

    total_violations_normal, violations_count_normal = evaluate_safety(switches_3_normal, params_list_3)
    print(f"Обычный control - всего нарушений: {total_violations_normal}")
    print(f"  Цель 1 (больница): {violations_count_normal[0]} нарушений")
    print(f"  Цель 2 (школа): {violations_count_normal[1]} нарушений")
    print(f"  Цель 3 (накопитель): {violations_count_normal[2]} нарушений")

    goals_safe = [check_safety_goals(sw, params) for sw, params in zip(switches_3_safe, params_list_3)]
    print_table(scenarios_3, switches_3_safe, params_list_3,
                "СЦЕНАРИЙ 3: Компрометация (safe_control с защитой)", goals_safe, compromised_list_3)

    total_violations_safe, violations_count_safe = evaluate_safety(switches_3_safe, params_list_3)
    print(f"Safe control - всего нарушений: {total_violations_safe}")
    print(f"  Цель 1 (больница): {violations_count_safe[0]} нарушений")
    print(f"  Цель 2 (школа): {violations_count_safe[1]} нарушений")
    print(f"  Цель 3 (накопитель): {violations_count_safe[2]} нарушений")

    # Сравнение
    print("\n" + "=" * 70)
    print("СРАВНЕНИЕ РЕЗУЛЬТАТОВ")
    print("=" * 70)
    print(f"Обычный control: {total_violations_normal} нарушений")
    print(f"Safe control:    {total_violations_safe} нарушений")
    if total_violations_normal > 0:
        improvement = total_violations_normal - total_violations_safe
        if improvement > 0:
            print(f"Улучшение: {improvement} нарушений предотвращено "
                  f"({improvement / total_violations_normal * 100:.1f}%)")
        elif improvement < 0:
            print(f"Ухудшение: {abs(improvement)} дополнительных нарушений")
        else:
            print("Результаты одинаковы")


if __name__ == "__main__":
    main()