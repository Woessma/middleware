from terminology.oid import OID_TO_FHIR_SYSTEM

def oid_to_fhir_system(oid):
    """
    Einfache OID -> FHIR system URI Zuordnung.
    Wenn der Wert bereits eine URI ist, wird er direkt verwendet.
    """
    if not oid:
        return None

    oid_value = oid.strip()
    if oid_value.startswith(("http://", "https://", "urn:", "urn:oid:")):
        return oid_value

    return OID_TO_FHIR_SYSTEM.get(oid_value, f"urn:oid:{oid_value}")
 
 

 
 
def make_fhir_coding(cda_code):
    if not cda_code:
        return None
 
    code = cda_code.get("code")
    if not code:
        return None
 
    coding = {
        "system": oid_to_fhir_system(cda_code.get("codeSystem")),
        "code": code
    }
 
    if cda_code.get("displayName"):
        coding["display"] = cda_code.get("displayName")
 
    return coding