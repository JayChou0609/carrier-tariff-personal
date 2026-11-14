"""Display official area names without changing tariff identity or archived fields."""
import json
from pathlib import Path
import re

AREA_CODES = json.loads((Path(__file__).resolve().parents[1] / 'custom/area-codes.json').read_text(encoding='utf-8'))
AREA_KEYS = {'适用地区', 'applicableArea', 'applyArea'}


def display_area(value, carrier=''):
    text = str(value if value is not None else '').strip()
    if not text:
        return '未公示'
    codes = AREA_CODES.get(carrier, {})
    result = []
    for part in filter(None, re.split(r'[,，、;；\s]+', text)):
        if part in codes:
            name = codes[part]
        elif re.search(r'[\u3400-\u9fff]', part) and not re.fullmatch(r'\d+[市省区县]?', part):
            name = part
        else:
            name = '适用地区待核验'
        if name not in result:
            result.append(name)
    return '、'.join(result)


def display_fields(fields, carrier=''):
    return {key: display_area(value, carrier) if key in AREA_KEYS else value for key, value in fields.items()}
