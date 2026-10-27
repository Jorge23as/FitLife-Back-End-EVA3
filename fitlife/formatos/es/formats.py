"""
Formatos de Chile para fechas y números (los usa el admin y las plantillas).

El español de Django muestra "27 de octubre de 2026 a las 19:00" y separa
los miles con un espacio. Acá se cambian a lo que se usa en Chile:
27-10-2026 19:00 y $34.990.
"""
DATE_FORMAT = 'd-m-Y'
SHORT_DATE_FORMAT = 'd-m-Y'
DATETIME_FORMAT = 'd-m-Y H:i'
SHORT_DATETIME_FORMAT = 'd-m-Y H:i'
TIME_FORMAT = 'H:i'
MONTH_DAY_FORMAT = 'j \\d\\e F'
YEAR_MONTH_FORMAT = 'F \\d\\e Y'
FIRST_DAY_OF_WEEK = 1  # lunes
DATE_INPUT_FORMATS = ['%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d']
DATETIME_INPUT_FORMATS = ['%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']
DECIMAL_SEPARATOR = ','
THOUSAND_SEPARATOR = '.'
NUMBER_GROUPING = 3
