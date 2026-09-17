def cda_ts_to_fhir_date(value):

    if not value:
        return None

    value = value.strip()

    # Bereits FHIR/ISO-Format
    if "-" in value:
        return value

    if len(value) >= 8:
        return (
            f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
        )

    return None
 
 
def cda_ts_to_fhir_datetime(value):

    if not value:
        return None

    value = value.strip()

    # Bereits FHIR/ISO-Format
    if "-" in value:
        return value

    if len(value) >= 19 and value[-5] in ["+", "-"]:

        base = value[0:14]
        tz = value[-5:]

        return (
            f"{base[0:4]}-{base[4:6]}-{base[6:8]}"
            f"T{base[8:10]}:{base[10:12]}:{base[12:14]}"
            f"{tz[0:3]}:{tz[3:5]}"
        )

    if len(value) >= 14:

        return (
            f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
            f"T{value[8:10]}:{value[10:12]}:{value[12:14]}"
        )

    if len(value) >= 8:
        return (
            f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
        )

    return None
 