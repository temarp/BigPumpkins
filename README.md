# Сбор данных о гигантских тыквах

Парсеры собирают открытые данные из [GPC results на BigPumpkins](https://www.bigpumpkins.com/WeighoffResultsGPC.aspx?c=P&y=2025) и [PumpkinFanatic](https://www.pumpkinfanatic.com/tools/Top500Pumpkins.php). В проверенных разделах сайтов отдельная кнопка полной выгрузки CSV/XLSX не обнаружена. Поэтому данные читаются из HTML и сохраняются в CSV, который открывается в Excel.

## Установка

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Запуск

```bash
# Все опубликованные результаты GPC для тыкв за 2020–2025 годы
.venv/bin/python -m scrapers bigpumpkins --years 2020:2025 --output data/bigpumpkins.csv

# Одна известная тыква, её родители и потомки (один шаг графа)
.venv/bin/python -m scrapers pumpkinfanatic \
  --name '2819.3 Paton 2025' --depth 1 --progeny \
  --max-pages 100 --output data/pumpkinfanatic.csv

# Начать с публичного списка Top 500; полный обход может занять много времени
.venv/bin/python -m scrapers pumpkinfanatic \
  --top500 --depth 1 --progeny --max-pages 1000 \
  --output data/pumpkinfanatic_top.csv

# Или взять названия из своего CSV с колонкой name
.venv/bin/python -m scrapers pumpkinfanatic \
  --names-csv data/names.csv --depth 0 --max-pages 1000 \
  --output data/pumpkinfanatic_from_list.csv
```

`--depth 0` загружает только указанные карточки. `--delay` задаёт паузу между запросами в секундах (по умолчанию 1). `--max-pages` ограничивает число карточек PumpkinFanatic. Ошибки отдельных карточек и лет записываются в `<output>.errors.txt`; процесс завершается с ненулевым кодом при неполной выгрузке.

Данные в CSV имеют общие столбцы: источник и URL, название, год, вес в фунтах и кг, выращиватель, место, мать (`mother`/Seed), отец (`father`/Pollinator), OTT, расчётный вес и отклонение от таблицы. Пустое значение означает отсутствие сведений на странице. В BigPumpkins нет отдельного поля с именем тыквы: `name` составляется из веса, фамилии и года, а `name_inferred=1` отмечает такое предположение. Для точного сопоставления записей двух сайтов одного этого поля недостаточно.

BigPumpkins охватывает опубликованные результаты **GPC** за выбранные годы, а не все независимые взвешивания. PumpkinFanatic `--top500` начинает обход только с 500 самых тяжёлых тыкв; это не полная база сайта. Оба источника могут обновляться после сезона. Перед массовым запуском стоит проверить текущие правила использования сайтов и сохранять паузу между запросами.

В `data/` сохранена полная выгрузка GPC за 2013–2025 годы, отдельные выгрузки 2024 и 2025 годов и небольшой проверочный набор PumpkinFanatic из трёх карточек. Последний не является полной выгрузкой PumpkinFanatic.

## Нормализация, EDA и базовая модель

`scrapers.names.parse_pumpkin_name(text, reference_year=...)` выделяет вес, выращивателя и год из названий вроде `2641.1 Paton 2024`. Он также распознаёт `Self`, `Open`, `Unknown` и пометки `DMG/EXH`. Если года нет, функция оставляет его пустым. Двузначный год выводится относительно года потомка и помечается `year_inferred=True`.

```bash
# Сбор исторической базы GPC в data/
.venv/bin/python -m scrapers bigpumpkins --years 2013:2025 \
  --output data/bigpumpkins_2013_2025.csv

.venv/bin/python -m analysis.eda \
  --input data/bigpumpkins_2013_2025.csv --output-dir reports

.venv/bin/python -m analysis.model \
  --input data/bigpumpkins_2013_2025.csv --output-dir reports

.venv/bin/python -m analysis.calibration \
  --input data/bigpumpkins_2013_2025.csv --output-dir reports \
  --threshold-kg 1000

.venv/bin/python -m analysis.predict \
  --mother '2819.3 Paton 2025' --father '2731.5 Stelts 2024' \
  --year 2026 --threshold-kg 1000
```

[Отчёт EDA](reports/EDA.md) содержит распределение веса, пропуски, найденные связи родитель–потомок и потенциальные выбросы. [Отчёт модели](reports/MODEL.md) приводит метрики по сезонам 2024–2025; датасет для обучения — `reports/training_dataset.csv`, коэффициенты базовой модели — `reports/baseline_model.json`.

[Калибровка](reports/CALIBRATION.md) для порога 1000 кг проверена последовательно на сезонах 2024 и 2025. Для прогноза следующего сезона используется `reports/calibrated_model.json`, обученная на данных до 2025 года. `analysis.predict` показывает исходную и скорректированную вероятность и признак `calibration_applied`. Для других порогов калибровка не применена. На последней проверке поправка улучшила log loss, но Brier score практически не изменился; редкие тяжёлые плоды всё ещё недооцениваются в сумме. Поэтому вероятность остаётся исследовательской оценкой.
