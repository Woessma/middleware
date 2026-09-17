const body = res.getBody();
const inputBundle = typeof body === "string" ? JSON.parse(body) : body;
const entries = inputBundle.entry || [];
console.log(
  "Bundle Entries:",
  entries.length
);
 
entries.forEach(function(e) {
 
  if (e.resource) {
    console.log(
      e.resource.resourceType,
      e.resource.id
    );
  }
 
});

// ======================================================
// Konfiguration
// ======================================================
const DOC_LANG = "de-CH";

const PROFILE_CH_IPS_DOCUMENT = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-document";
const PROFILE_CH_IPS_COMPOSITION = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition";
const PROFILE_CH_IPS_PATIENT = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-patient";
const PROFILE_CH_IPS_ORGANIZATION = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-organization";
const PROFILE_CH_IPS_CONDITION = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-condition";
const PROFILE_CH_IPS_MEDICATIONSTATEMENT = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-medicationstatement";
const PROFILE_CH_IPS_ALLERGYINTOLERANCE = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-allergyintolerance";
const PROFILE_CH_IPS_IMMUNIZATION = "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-immunization";

const EXT_CH_EPR_CONFIDENTIALITY =
  "http://fhir.ch/ig/ch-core/StructureDefinition/ch-ext-epr-confidentialitycode";

const AHVN13_SYSTEM = "urn:oid:2.16.756.5.30.1.127.3.10.3";
const GLN_SYSTEM = "urn:oid:2.51.1.3";
const DEFAULT_ORG_GLN = "7601777777718";

// ======================================================
// Generic Helpers
// ======================================================
function clone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function toDate(value) {
  const d = value ? new Date(value) : null;
  return d && !isNaN(d.getTime()) ? d : null;
}

function pad(num) {
  return num < 10 ? "0" + num : String(num);
}

function formatDate(value) {
  const d = toDate(value);
  if (!d) return value || "";

  return (
    d.getUTCFullYear() + "-" +
    pad(d.getUTCMonth() + 1) + "-" +
    pad(d.getUTCDate()) + "T" +
    pad(d.getUTCHours()) + ":" +
    pad(d.getUTCMinutes()) + ":" +
    pad(d.getUTCSeconds()) + "Z"
  );
}

function esc(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function safeJoin(arr, sep) {
  if (!arr || !arr.length) return "";
  return arr.filter(Boolean).join(sep || " ");
}

function randomUuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === "x" ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

function detectBaseUrl(bundle, entries) {
  if (bundle && Array.isArray(bundle.link)) {
    const selfLink = bundle.link.find(function(l) {
      return l && l.relation === "self" && l.url;
    });

    if (selfLink && selfLink.url) {
      const idx = selfLink.url.indexOf("/Patient/");
      if (idx > 0) return selfLink.url.substring(0, idx);
    }
  }

  for (let i = 0; i < entries.length; i++) {
    const fu = entries[i] && entries[i].fullUrl;
    const r = entries[i] && entries[i].resource;

    if (fu && r && r.resourceType && r.id) {
      const suffix = "/" + r.resourceType + "/" + r.id;
      if (fu.endsWith(suffix)) {
        return fu.substring(0, fu.length - suffix.length);
      }
    }
  }

  return "https://example.invalid/fhir";
}

function buildFullUrl(base, resourceType, id) {
  return base + "/" + resourceType + "/" + id;
}

function getCodingDisplay(cc, fallback) {
  if (!cc) return fallback || "";
  if (cc.text) return cc.text;

  if (cc.coding && cc.coding.length) {
    return cc.coding[0].display || cc.coding[0].code || fallback || "";
  }

  return fallback || "";
}

// ======================================================
// Cleanup Helpers
// ======================================================
function cleanupEmptyMeta(resource) {
  if (!resource || !resource.meta) return;

  if (resource.meta.profile && resource.meta.profile.length === 0) {
    delete resource.meta.profile;
  }

  if (Object.keys(resource.meta).length === 0) {
    delete resource.meta;
  }
}

function setOnlyProfiles(resource, profiles) {
  if (!resource.meta) resource.meta = {};
  resource.meta.profile = profiles || [];
  cleanupEmptyMeta(resource);
}

function removeIdentifierTypes(resource) {
  if (!resource || !resource.identifier) return;

  for (let i = 0; i < resource.identifier.length; i++) {
    delete resource.identifier[i].type;
  }
}

function keepOnlyPatientAhvnIdentifier(patient) {
  if (!patient || !patient.identifier) return;

  const ahv = patient.identifier.find(function(id) {
    return id.system === AHVN13_SYSTEM;
  });

  patient.identifier = ahv ? [ahv] : [];
  removeIdentifierTypes(patient);
}

function removeUnknownExtensions(resource) {
  if (!resource) return;

  if (resource.extension) {
    delete resource.extension;
  }

  if (resource.subject && resource.subject.extension) {
    delete resource.subject.extension;
  }

  if (resource.patient && resource.patient.extension) {
    delete resource.patient.extension;
  }

  if (resource.contained && resource.contained.length) {
    for (let i = 0; i < resource.contained.length; i++) {
      if (resource.contained[i].extension) {
        delete resource.contained[i].extension;
      }
    }
  }
}

function removeExternalProfiles(resource) {
  if (!resource || !resource.meta) return;

  if (resource.meta.profile && resource.meta.profile.length) {
    resource.meta.profile = resource.meta.profile.filter(function(p) {
      return (
        p.indexOf("http://fhir.ch/ig/ch-ips/") === 0 ||
        p.indexOf("http://hl7.org/fhir/uv/ips/") === 0
      );
    });

    if (resource.meta.profile.length === 0) {
      delete resource.meta.profile;
    }
  }

  cleanupEmptyMeta(resource);
}

function cleanupContainedMeta(resource) {
  if (!resource || !resource.contained) return;

  for (let i = 0; i < resource.contained.length; i++) {
    removeExternalProfiles(resource.contained[i]);
    cleanupEmptyMeta(resource.contained[i]);
  }
}

// ======================================================
// Patient / Organization
// ======================================================
function buildOrganizationFromPatient(patient) {
  return {
    resourceType: "Organization",
    id: "Hausarzt-Organization",
    meta: {
      profile: [PROFILE_CH_IPS_ORGANIZATION]
    },
    identifier: [
      {
        system: GLN_SYSTEM,
        value: DEFAULT_ORG_GLN
      }
    ],
    name: "Organisation"
  };
}

function formatPatientName(patient) {
  if (!patient || !patient.name || !patient.name.length) {
    return (patient && patient.id) || "Unbekannter Patient";
  }

  const name = patient.name[0];
  const given = name.given ? safeJoin(name.given, " ") : "";
  const family = name.family || "";
  const full = safeJoin([given, family], " ").trim();

  return full || patient.id || "Unbekannter Patient";
}

function setPatientNarrative(patient) {
  const patientName = formatPatientName(patient);
  const gender = patient && patient.gender ? patient.gender : "unknown";
  const birthDate = patient && patient.birthDate ? patient.birthDate : "unknown";

  const addr = patient && patient.address && patient.address[0] ? patient.address[0] : null;
  const line = addr && addr.line ? safeJoin(addr.line, " ") : "";
  const city = addr && addr.city ? addr.city : "";
  const postalCode = addr && addr.postalCode ? addr.postalCode : "";
  const country = addr && addr.country ? addr.country : "";
  const addressText = safeJoin([line, postalCode, city, country], " ").trim();

  patient.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>Patient</b></p>' +
      '<p>' + esc(patientName) + '</p>' +
      '<p>Geschlecht: ' + esc(gender) + '</p>' +
      '<p>Geburtsdatum: ' + esc(birthDate) + '</p>' +
      (addressText ? '<p>Adresse: ' + esc(addressText) + '</p>' : '') +
      '</div>'
  };
}

function setOrganizationNarrative(org) {
  const idf = org && org.identifier && org.identifier[0] ? org.identifier[0] : null;
  const idText = idf ? ((idf.system || "") + " | " + (idf.value || "")) : (org.id || "unknown");

  org.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>Organisation</b></p>' +
      (org.name ? '<p>' + esc(org.name) + '</p>' : '') +
      '<p>' + esc(idText) + '</p>' +
      '</div>'
  };
}

// ======================================================
// Quantity / Observation
// ======================================================
function normalizeQuantity(qty) {
  if (!qty) return;

  if (qty.unit === "mmHg" || qty.unit === "mm[Hg]") {
    qty.unit = "mmHg";
    qty.system = "http://unitsofmeasure.org";
    qty.code = "mm[Hg]";
    return;
  }

  if (qty.unit === "°C" || qty.unit === "Cel") {
    qty.unit = "°C";
    qty.system = "http://unitsofmeasure.org";
    qty.code = "Cel";
    return;
  }

  if (qty.unit === "mg" || qty.code === "mg") {
    qty.unit = qty.unit || "mg";
    qty.system = "http://unitsofmeasure.org";
    qty.code = "mg";
    return;
  }
}

function normalizeObservationQuantities(obs) {
  if (!obs) return;

  if (obs.valueQuantity) {
    normalizeQuantity(obs.valueQuantity);
  }

  if (obs.component && obs.component.length) {
    for (let i = 0; i < obs.component.length; i++) {
      const comp = obs.component[i];
      if (comp && comp.valueQuantity) {
        normalizeQuantity(comp.valueQuantity);
      }
    }
  }
}

function ensureObservationPerformer(obs) {
  if (!obs) return;
  if (obs.performer && obs.performer.length) return;

  obs.performer = [
    {
      reference: "Organization/Hausarzt-Organization"
    }
  ];
}

function getObservationCode(obs) {
  if (obs && obs.code && obs.code.coding) {
    for (let i = 0; i < obs.code.coding.length; i++) {
      const c = obs.code.coding[i];
      if (c.system === "http://loinc.org" && c.code) return c.code;
    }

    if (obs.code.coding[0] && obs.code.coding[0].code) {
      return obs.code.coding[0].code;
    }
  }

  return (obs && obs.code && obs.code.text) || (obs && obs.id) || "unknown";
}

function getObservationDisplay(obs) {
  return getCodingDisplay(obs && obs.code, getObservationCode(obs) || "Observation");
}

function getCategoryCodes(obs) {
  const result = [];
  if (!obs || !obs.category) return result;

  for (let i = 0; i < obs.category.length; i++) {
    const cat = obs.category[i];
    if (!cat || !cat.coding) continue;

    for (let j = 0; j < cat.coding.length; j++) {
      const c = cat.coding[j];
      if (c && c.code) result.push(c.code);
    }
  }

  return result;
}

function hasCategory(obs, code) {
  const codes = getCategoryCodes(obs);

  for (let i = 0; i < codes.length; i++) {
    if (codes[i] === code) return true;
  }

  return false;
}

function getObservationType(obs) {
  if (hasCategory(obs, "vital-signs")) return "vital-signs";
  if (hasCategory(obs, "laboratory")) return "laboratory";
  return null;
}

function hasUsableObservationValue(obs) {
  return !!(
    obs.valueQuantity ||
    obs.valueCodeableConcept ||
    obs.valueString ||
    obs.valueBoolean !== undefined ||
    obs.valueInteger !== undefined ||
    obs.valueRange ||
    obs.valueRatio ||
    obs.valueSampledData ||
    obs.valueTime ||
    obs.valueDateTime ||
    (obs.component && obs.component.length > 0) ||
    obs.dataAbsentReason ||
    (obs.interpretation && obs.interpretation.length > 0)
  );
}

function getInterpretationText(obs) {
  if (!obs || !obs.interpretation || !obs.interpretation.length) return "";
  return getCodingDisplay(obs.interpretation[0], "");
}

function getDataAbsentReasonText(obs) {
  if (!obs || !obs.dataAbsentReason) return "";
  return getCodingDisplay(obs.dataAbsentReason, "");
}

function formatObservationValue(obs) {
  if (!obs) return "Kein Wert";

  if (obs.valueQuantity) {
    normalizeQuantity(obs.valueQuantity);
    return ((obs.valueQuantity.value != null ? obs.valueQuantity.value : "") + " " + (obs.valueQuantity.unit || "")).trim();
  }

  if (obs.valueCodeableConcept) {
    return getCodingDisplay(obs.valueCodeableConcept, "CodeableConcept");
  }

  if (obs.valueString) return obs.valueString;
  if (obs.valueBoolean !== undefined) return String(obs.valueBoolean);
  if (obs.valueInteger !== undefined) return String(obs.valueInteger);
  if (obs.valueDateTime) return obs.valueDateTime;
  if (obs.valueTime) return obs.valueTime;

  if (obs.component && obs.component.length) {
    const parts = [];

    for (let i = 0; i < obs.component.length; i++) {
      const c = obs.component[i];
      if (!c) continue;

      const compDisplay = getCodingDisplay(c.code, "Komponente");

      if (c.valueQuantity) {
        normalizeQuantity(c.valueQuantity);
        parts.push(
          (
            compDisplay +
            ": " +
            (c.valueQuantity.value != null ? c.valueQuantity.value : "") +
            " " +
            (c.valueQuantity.unit || "")
          ).trim()
        );
      } else if (c.valueCodeableConcept) {
        parts.push(compDisplay + ": " + getCodingDisplay(c.valueCodeableConcept, ""));
      } else if (c.valueString) {
        parts.push(compDisplay + ": " + c.valueString);
      } else {
        parts.push(compDisplay);
      }
    }

    if (parts.length) return parts.join(", ");
  }

  const interpretationText = getInterpretationText(obs);
  if (interpretationText) return interpretationText;

  const dataAbsentReasonText = getDataAbsentReasonText(obs);
  if (dataAbsentReasonText) return "Kein Wert (" + dataAbsentReasonText + ")";

  return "Kein Wert";
}

function setObservationNarrative(obs) {
  obs.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(getObservationDisplay(obs)) + '</b></p>' +
      '<p>Wert: ' + esc(formatObservationValue(obs)) + '</p>' +
      (obs.effectiveDateTime || obs.issued ? '<p>Datum: ' + esc(obs.effectiveDateTime || obs.issued) + '</p>' : '') +
      (obs.status ? '<p>Status: ' + esc(obs.status) + '</p>' : '') +
      '</div>'
  };
}

function buildObservationSectionNarrative(title, obsArray) {
  const rows = [];

  for (let i = 0; i < obsArray.length; i++) {
    const obs = obsArray[i];

    rows.push(
      "<tr>" +
      "<td>" + esc(getObservationDisplay(obs)) + "</td>" +
      "<td>" + esc(formatObservationValue(obs)) + "</td>" +
      "<td>" + esc(formatDate(obs.effectiveDateTime || obs.issued || "")) + "</td>" +
      "<td>" + esc(obs.status || "") + "</td>" +
      "</tr>"
    );
  }

  return {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(title) + '</b></p>' +
      '<table border="1">' +
      '<tr><th>Eintrag</th><th>Wert</th><th>Datum</th><th>Status</th></tr>' +
      rows.join("") +
      '</table>' +
      '</div>'
  };
}

// ======================================================
// Condition
// ======================================================
function getConditionDisplay(c) {
  return getCodingDisplay(c && c.code, (c && c.id) || "Problem");
}

function getConditionClinicalStatus(c) {
  return getCodingDisplay(c && c.clinicalStatus, "");
}

function getConditionVerificationStatus(c) {
  return getCodingDisplay(c && c.verificationStatus, "");
}

function getConditionDate(c) {
  return (c && (c.onsetDateTime || c.recordedDate)) || "";
}

function setConditionNarrative(c) {
  c.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(getConditionDisplay(c)) + '</b></p>' +
      (getConditionClinicalStatus(c) ? '<p>Klinischer Status: ' + esc(getConditionClinicalStatus(c)) + '</p>' : '') +
      (getConditionVerificationStatus(c) ? '<p>Verifikation: ' + esc(getConditionVerificationStatus(c)) + '</p>' : '') +
      (getConditionDate(c) ? '<p>Datum: ' + esc(getConditionDate(c)) + '</p>' : '') +
      '</div>'
  };
}

function buildConditionSectionNarrative(title, conditions) {
  const rows = [];

  for (let i = 0; i < conditions.length; i++) {
    const c = conditions[i];

    rows.push(
      "<tr>" +
      "<td>" + esc(getConditionDisplay(c)) + "</td>" +
      "<td>" + esc(getConditionClinicalStatus(c)) + "</td>" +
      "<td>" + esc(getConditionVerificationStatus(c)) + "</td>" +
      "<td>" + esc(formatDate(getConditionDate(c))) + "</td>" +
      "</tr>"
    );
  }

  return {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(title) + '</b></p>' +
      '<table border="1">' +
      '<tr><th>Problem</th><th>Klinischer Status</th><th>Verifikation</th><th>Datum</th></tr>' +
      rows.join("") +
      '</table>' +
      '</div>'
  };
}

// ======================================================
// MedicationStatement
// ======================================================
function getMedicationStatementDisplay(ms) {
  if (ms.medicationCodeableConcept) {
    return getCodingDisplay(ms.medicationCodeableConcept, "Medikation");
  }

  if (ms.medicationReference) {
    if (ms.medicationReference.display) return ms.medicationReference.display;

    if (ms.medicationReference.reference && ms.medicationReference.reference.startsWith("#")) {
      const containedId = ms.medicationReference.reference.substring(1);

      if (ms.contained && ms.contained.length) {
        const med = ms.contained.find(function(r) {
          return r.resourceType === "Medication" && r.id === containedId;
        });

        if (med) return getCodingDisplay(med.code, containedId);
      }
    }
  }

  return ms.id || "Medikation";
}

function getMedicationStatementReason(ms) {
  if (ms.reasonCode && ms.reasonCode.length) {
    return getCodingDisplay(ms.reasonCode[0], "");
  }

  return "";
}

function getMedicationStatementDosage(ms) {

  if (!ms.dosage || !ms.dosage.length) {
    return "";
  }

  const d = ms.dosage[0];

  // CDA-Originaltext bevorzugen
  if (d.text) {
    return d.text;
  }

  const parts = [];

  if (
    d.doseAndRate &&
    d.doseAndRate.length &&
    d.doseAndRate[0].doseQuantity
  ) {
    const dq = d.doseAndRate[0].doseQuantity;

    normalizeQuantity(dq);

    parts.push(
      (
        (dq.value != null ? dq.value : "") +
        " " +
        (dq.unit || "")
      ).trim()
    );
  }

  if (d.route) {
    const route = getCodingDisplay(d.route, "");
    if (route) parts.push(route);
  }

  if (
    d.timing &&
    d.timing.repeat &&
    d.timing.repeat.when &&
    d.timing.repeat.when.length
  ) {
    parts.push(
      "[" + d.timing.repeat.when.join(",") + "]"
    );
  }

  return parts.filter(Boolean).join(" | ");
}

function getMedicationStatementDate(ms) {
  if (ms.effectivePeriod && ms.effectivePeriod.start) return ms.effectivePeriod.start;
  if (ms.effectiveDateTime) return ms.effectiveDateTime;
  if (ms.dateAsserted) return ms.dateAsserted;
  return "";
}

function ensureMedicationStatementEffective(ms) {
  if (!ms) return;

  if (ms.effectiveDateTime || ms.effectivePeriod) return;

  if (ms.dosage && ms.dosage.length) {
    for (let i = 0; i < ms.dosage.length; i++) {
      const d = ms.dosage[i];

      if (
        d.timing &&
        d.timing.repeat &&
        d.timing.repeat.boundsPeriod &&
        d.timing.repeat.boundsPeriod.start
      ) {
        ms.effectivePeriod = {
          start: d.timing.repeat.boundsPeriod.start
        };
        return;
      }
    }
  }

  if (ms.dateAsserted) {
    ms.effectiveDateTime = ms.dateAsserted;
    return;
  }

  ms.effectiveDateTime = new Date().toISOString();
}

function cleanMedicationStatementForIps(ms) {
  if (!ms) return;

  setOnlyProfiles(ms, [PROFILE_CH_IPS_MEDICATIONSTATEMENT]);

  if (ms.extension) {
    delete ms.extension;
  }

  if (ms.subject && ms.subject.extension) {
    delete ms.subject.extension;
  }

  ensureMedicationStatementEffective(ms);
  cleanupContainedMeta(ms);
  cleanupEmptyMeta(ms);
}

function setMedicationStatementNarrative(ms) {
  ms.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(getMedicationStatementDisplay(ms)) + '</b></p>' +
      (getMedicationStatementDate(ms) ? '<p>Datum: ' + esc(getMedicationStatementDate(ms)) + '</p>' : '') +
      (ms.status ? '<p>Status: ' + esc(ms.status) + '</p>' : '') +
      (getMedicationStatementDosage(ms) ? '<p>Dosierung: ' + esc(getMedicationStatementDosage(ms)) + '</p>' : '') +
      (getMedicationStatementReason(ms) ? '<p>Grund: ' + esc(getMedicationStatementReason(ms)) + '</p>' : '') +
      '</div>'
  };
}

function buildMedicationSectionNarrative(title, meds) {
  const rows = [];

  for (let i = 0; i < meds.length; i++) {
    const ms = meds[i];

    rows.push(
      "<tr>" +
      "<td>" + esc(getMedicationStatementDisplay(ms)) + "</td>" +
      "<td>" + esc(getMedicationStatementDosage(ms)) + "</td>" +
      "<td>" + esc(getMedicationStatementReason(ms)) + "</td>" +
      "<td>" + esc(formatDate(getMedicationStatementDate(ms))) + "</td>" +
      "<td>" + esc(ms.status || "") + "</td>" +
      "</tr>"
    );
  }

  return {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(title) + '</b></p>' +
      '<table border="1">' +
      '<tr><th>Medikament</th><th>Dosierung</th><th>Grund</th><th>Datum</th><th>Status</th></tr>' +
      rows.join("") +
      '</table>' +
      '</div>'
  };
}

// ======================================================
// AllergyIntolerance
// ======================================================
function getAllergyDisplay(ai) {
  return getCodingDisplay(ai && ai.code, (ai && ai.id) || "Allergie");
}

function getAllergySubstance(ai) {
 
  if (ai.code) {
    return getCodingDisplay(ai.code, "");
  }
 
  if (!ai.reaction ||
      !ai.reaction.length ||
      !ai.reaction[0].substance) {
    return "";
  }
 
  return getCodingDisplay(
    ai.reaction[0].substance,
    ""
  );
}

function getAllergyReaction(ai) {
  if (!ai.reaction || !ai.reaction.length) return "";
 
  const reactions = [];
 
  for (let i = 0; i < ai.reaction.length; i++) {
    const r = ai.reaction[i];
 
    if (!r || !r.manifestation || !r.manifestation.length) {
      continue;
    }
 
    for (let j = 0; j < r.manifestation.length; j++) {
      const manifestationText = getCodingDisplay(
        r.manifestation[j],
        ""
      );
 
      if (manifestationText) {
        reactions.push(manifestationText);
      }
    }
  }
 
  return reactions.join(", ");
}


function getAllergyDate(ai) {
  return ai.recordedDate || "";
}

function getAllergySeverity(ai) {
 
  if (
      ai.reaction &&
      ai.reaction.length &&
      ai.reaction[0].severity
  ) {
      return ai.reaction[0].severity;
  }
 
  return ai.criticality || "";
}

function setAllergyNarrative(ai) {
  ai.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(getAllergyDisplay(ai)) + '</b></p>' +
      (getAllergySubstance(ai) ? '<p>Substanz: ' + esc(getAllergySubstance(ai)) + '</p>' : '') +
      (getAllergyReaction(ai) ? '<p>Reaktion: ' + esc(getAllergyReaction(ai)) + '</p>' : '') +
      (getAllergySeverity(ai) ? '<p>Schweregrad: ' + esc(getAllergySeverity(ai)) + '</p>' : '') +
      (getCodingDisplay(ai.clinicalStatus, "") ? '<p>Klinischer Status: ' + esc(getCodingDisplay(ai.clinicalStatus, "")) + '</p>' : '') +
      (getCodingDisplay(ai.verificationStatus, "") ? '<p>Verifikation: ' + esc(getCodingDisplay(ai.verificationStatus, "")) + '</p>' : '') +
      (getAllergyDate(ai) ? '<p>Datum: ' + esc(getAllergyDate(ai)) + '</p>' : '') +
      '</div>'
  };
}

function buildAllergySectionNarrative(title, allergies) {
  const rows = [];

  for (let i = 0; i < allergies.length; i++) {
    const ai = allergies[i];

    rows.push(
      "<tr>" +
      "<td>" + esc(getAllergyDisplay(ai)) + "</td>" +
      "<td>" + esc(getAllergySubstance(ai)) + "</td>" +
      "<td>" + esc(getAllergyReaction(ai)) + "</td>" +
      "<td>" + esc(getAllergySeverity(ai)) + "</td>" +
      "<td>" + esc(getCodingDisplay(ai.clinicalStatus, "")) + "</td>" +
      "<td>" + esc(getCodingDisplay(ai.verificationStatus, "")) + "</td>" +
      "<td>" + esc(formatDate(getAllergyDate(ai))) + "</td>" +
      "</tr>"
    );
  }

  return {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(title) + '</b></p>' +
      '<table border="1">' +
      '<tr><th>Allergie</th><th>Substanz</th><th>Reaktion</th><th>Schweregrad</th><th>Klinischer Status</th><th>Verifikation</th><th>Datum</th></tr>' +
      rows.join("") +
      '</table>' +
      '</div>'
  };
}

// ======================================================
// Immunization
// ======================================================
function getImmunizationDisplay(imm) {
  return getCodingDisplay(imm && imm.vaccineCode, (imm && imm.id) || "Impfung");
}

function getImmunizationDate(imm) {
  return imm.occurrenceDateTime || imm.recorded || "";
}

function cleanImmunizationForIps(imm) {
  if (!imm) return;

  setOnlyProfiles(imm, [PROFILE_CH_IPS_IMMUNIZATION]);

  if (imm.extension) {
    delete imm.extension;
  }

  if (imm.patient && imm.patient.extension) {
    delete imm.patient.extension;
  }

  cleanupEmptyMeta(imm);
}

function setImmunizationNarrative(imm) {
  imm.text = {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(getImmunizationDisplay(imm)) + '</b></p>' +
      (getImmunizationDate(imm) ? '<p>Datum: ' + esc(getImmunizationDate(imm)) + '</p>' : '') +
      (imm.status ? '<p>Status: ' + esc(imm.status) + '</p>' : '') +
      (imm.lotNumber ? '<p>Chargennummer: ' + esc(imm.lotNumber) + '</p>' : '') +
      '</div>'
  };
}

function buildImmunizationSectionNarrative(title, immunizations) {
  const rows = [];

  for (let i = 0; i < immunizations.length; i++) {
    const imm = immunizations[i];

    rows.push(
      "<tr>" +
      "<td>" + esc(getImmunizationDisplay(imm)) + "</td>" +
      "<td>" + esc(formatDate(getImmunizationDate(imm))) + "</td>" +
      "<td>" + esc(imm.status || "") + "</td>" +
      "<td>" + esc(imm.lotNumber || "") + "</td>" +
      "</tr>"
    );
  }

  return {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>' + esc(title) + '</b></p>' +
      '<table border="1">' +
      '<tr><th>Impfstoff</th><th>Datum</th><th>Status</th><th>Chargennummer</th></tr>' +
      rows.join("") +
      '</table>' +
      '</div>'
  };
}

// ======================================================
// Composition Narrative
// ======================================================
function buildCompositionNarrative(patient, vitalObservations, resultObservations, conditions, immunizations, medicationStatements, allergies) {
  const patientName = formatPatientName(patient);

  function listItems(arr, fn) {
    const items = [];
    for (let i = 0; i < arr.length; i++) {
      items.push("<li>" + esc(fn(arr[i])) + "</li>");
    }
    return items.join("");
  }

  return {
    status: "generated",
    div:
      '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
      '<p><b>Patient Summary fuer IPS Schweiz</b></p>' +
      '<p>Patient: ' + esc(patientName) + '</p>' +
      '<p>Probleme: ' + conditions.length + '</p>' +
      '<p>Vitalparameter: ' + vitalObservations.length + '</p>' +
      '<p>Resultate: ' + resultObservations.length + '</p>' +
      '<p>Medikation: ' + medicationStatements.length + '</p>' +
      '<p>Allergien: ' + allergies.length + '</p>' +
      '<p>Impfungen: ' + immunizations.length + '</p>' +
      (conditions.length ? '<p><b>Problemliste</b></p><ul>' + listItems(conditions, getConditionDisplay) + '</ul>' : '') +
      (vitalObservations.length ? '<p><b>Vitalparameter</b></p><ul>' + listItems(vitalObservations, function(o) { return getObservationDisplay(o) + ": " + formatObservationValue(o); }) + '</ul>' : '') +
      (resultObservations.length ? '<p><b>Resultate</b></p><ul>' + listItems(resultObservations, function(o) { return getObservationDisplay(o) + ": " + formatObservationValue(o); }) + '</ul>' : '') +
      (medicationStatements.length ? '<p><b>Medikation</b></p><ul>' + listItems(medicationStatements, function(m) { return getMedicationStatementDisplay(m) + (getMedicationStatementDosage(m) ? ": " + getMedicationStatementDosage(m) : ""); }) + '</ul>' : '') +
      (allergies.length ? '<p><b>Allergien und Intoleranzen</b></p><ul>' + listItems(allergies, function(a) { return getAllergyDisplay(a) + (getAllergyReaction(a) ? ": " + getAllergyReaction(a) : ""); }) + '</ul>' : '') +
      (immunizations.length ? '<p><b>Impfungen</b></p><ul>' + listItems(immunizations, function(i) { return getImmunizationDisplay(i) + " (" + formatDate(getImmunizationDate(i)) + ")"; }) + '</ul>' : '') +
      '</div>'
  };
}

// ======================================================
// Dedupe
// ======================================================
function dedupeLatestByCode(observations) {
  const latestByCode = {};

  for (let i = 0; i < observations.length; i++) {
    const obs = observations[i];
    const code = getObservationCode(obs);
    const existing = latestByCode[code];

    if (!existing) {
      latestByCode[code] = obs;
      continue;
    }

    const d1 = toDate(existing.effectiveDateTime) || toDate(existing.issued) || new Date(0);
    const d2 = toDate(obs.effectiveDateTime) || toDate(obs.issued) || new Date(0);

    if (d2 > d1) {
      latestByCode[code] = obs;
    }
  }

  const result = [];

  for (const k in latestByCode) {
    if (Object.prototype.hasOwnProperty.call(latestByCode, k)) {
      result.push(latestByCode[k]);
    }
  }

  result.sort(function(a, b) {
    const da = toDate(a.effectiveDateTime) || toDate(a.issued) || new Date(0);
    const db = toDate(b.effectiveDateTime) || toDate(b.issued) || new Date(0);
    return db - da;
  });

  return result;
}

// ======================================================
// Ressourcen einsammeln
// ======================================================
let patient = null;
const observations = [];
observations.forEach(function(obs) {
 
  console.log(
    JSON.stringify(
      {
        id: obs.id,
        code: obs.code,
        category: obs.category
      },
      null,
      2
    )
  );
 
});
 
const immunizations = [];
const medicationStatements = [];
const allergyIntolerances = [];
const conditions = [];
const goals = [];
const consents = [];
const careTeams = [];
const ignoredResourceTypes = [];

for (let i = 0; i < entries.length; i++) {
  const e = entries[i];
  const r = e && e.resource;

  if (!r || !r.resourceType) continue;

  const resource = clone(r);

  switch (resource.resourceType) {
    case "Patient":
      if (!patient) patient = resource;
      break;

    case "Observation":
      observations.push(resource);
      break;

    case "Immunization":
      immunizations.push(resource);
      break;

    case "MedicationStatement":
      medicationStatements.push(resource);
      break;

    case "AllergyIntolerance":
      allergyIntolerances.push(resource);
      break;

    case "Condition":
      conditions.push(resource);
      break;
	  
	case "Goal":
		goals.push(resource);
		break;

	case "Consent":
		consents.push(resource);
		break;

	case "CareTeam":
		careTeams.push(resource);
		break;
		
    default:
      ignoredResourceTypes.push(resource.resourceType);
      break;
  }
}

if (!patient) {
  throw new Error("Kein Patient im $everything-Bundle gefunden.");
}

const FULLURL_BASE = detectBaseUrl(inputBundle, entries);

// ======================================================
// Filtern / Sortieren
// ======================================================
const relevantObservations = observations.filter(function(obs) {
  return getObservationType(obs) && hasUsableObservationValue(obs);
});

const vitalObservations = dedupeLatestByCode(
  relevantObservations.filter(function(obs) {
    return getObservationType(obs) === "vital-signs";
  })
);

const resultObservations = dedupeLatestByCode(
  relevantObservations.filter(function(obs) {
    return getObservationType(obs) === "laboratory";
  })
);

const sortedConditions = conditions.slice().sort(function(a, b) {
  const da = toDate(getConditionDate(a)) || new Date(0);
  const db = toDate(getConditionDate(b)) || new Date(0);
  return db - da;
});

const sortedImmunizations = immunizations.slice().sort(function(a, b) {
  const da = toDate(getImmunizationDate(a)) || new Date(0);
  const db = toDate(getImmunizationDate(b)) || new Date(0);
  return db - da;
});

const sortedMedicationStatements = medicationStatements.slice().sort(function(a, b) {
  const da = toDate(getMedicationStatementDate(a)) || new Date(0);
  const db = toDate(getMedicationStatementDate(b)) || new Date(0);
  return db - da;
});

const sortedAllergyIntolerances = allergyIntolerances.slice().sort(function(a, b) {
  const da = toDate(getAllergyDate(a)) || new Date(0);
  const db = toDate(getAllergyDate(b)) || new Date(0);
  return db - da;
});

// ======================================================
// Output-Ressourcen bereinigen
// ======================================================
setOnlyProfiles(patient, [PROFILE_CH_IPS_PATIENT]);
keepOnlyPatientAhvnIdentifier(patient);
removeUnknownExtensions(patient);
cleanupEmptyMeta(patient);

const organization = buildOrganizationFromPatient(patient);
cleanupEmptyMeta(organization);

for (let i = 0; i < sortedConditions.length; i++) {
  setOnlyProfiles(sortedConditions[i], [PROFILE_CH_IPS_CONDITION]);
  removeUnknownExtensions(sortedConditions[i]);
  cleanupEmptyMeta(sortedConditions[i]);
}

for (let i = 0; i < vitalObservations.length; i++) {
  removeExternalProfiles(vitalObservations[i]);
  removeUnknownExtensions(vitalObservations[i]);
  normalizeObservationQuantities(vitalObservations[i]);
  ensureObservationPerformer(vitalObservations[i]);
  cleanupEmptyMeta(vitalObservations[i]);
}

for (let i = 0; i < resultObservations.length; i++) {
  removeExternalProfiles(resultObservations[i]);
  removeUnknownExtensions(resultObservations[i]);
  normalizeObservationQuantities(resultObservations[i]);
  ensureObservationPerformer(resultObservations[i]);
  cleanupEmptyMeta(resultObservations[i]);
}

for (let i = 0; i < sortedMedicationStatements.length; i++) {
  cleanMedicationStatementForIps(sortedMedicationStatements[i]);
}

for (let i = 0; i < sortedAllergyIntolerances.length; i++) {
  setOnlyProfiles(sortedAllergyIntolerances[i], [PROFILE_CH_IPS_ALLERGYINTOLERANCE]);
  removeUnknownExtensions(sortedAllergyIntolerances[i]);
  cleanupEmptyMeta(sortedAllergyIntolerances[i]);
}

for (let i = 0; i < sortedImmunizations.length; i++) {
  cleanImmunizationForIps(sortedImmunizations[i]);
}

// ======================================================
// Narratives setzen
// ======================================================
setPatientNarrative(patient);
setOrganizationNarrative(organization);

for (let i = 0; i < sortedConditions.length; i++) {
  setConditionNarrative(sortedConditions[i]);
}

for (let i = 0; i < vitalObservations.length; i++) {
  setObservationNarrative(vitalObservations[i]);
}

for (let i = 0; i < resultObservations.length; i++) {
  setObservationNarrative(resultObservations[i]);
}

for (let i = 0; i < sortedMedicationStatements.length; i++) {
  setMedicationStatementNarrative(sortedMedicationStatements[i]);
}

for (let i = 0; i < sortedAllergyIntolerances.length; i++) {
  setAllergyNarrative(sortedAllergyIntolerances[i]);
}

for (let i = 0; i < sortedImmunizations.length; i++) {
  setImmunizationNarrative(sortedImmunizations[i]);
}

// ======================================================
// Composition bauen
// ======================================================
const now = new Date().toISOString();
const docUuid = randomUuid();
const compositionId = "CH-IPS-Composition-1";

const composition = {
  resourceType: "Composition",
  id: compositionId,
  meta: {
    profile: [PROFILE_CH_IPS_COMPOSITION]
  },
  language: DOC_LANG,
  identifier: {
    system: "urn:ietf:rfc:3986",
    value: "urn:uuid:" + docUuid
  },
  status: "final",
  type: {
    coding: [
      {
        system: "http://loinc.org",
        code: "60591-5",
        display: "Patient summary Document"
      }
    ]
  },
  subject: {
    reference: "Patient/" + patient.id
  },
  date: now,
  title: "Patient Summary fuer IPS Schweiz",
  confidentiality: "N",
  _confidentiality: {
    extension: [
      {
        url: EXT_CH_EPR_CONFIDENTIALITY,
        valueCodeableConcept: {
          coding: [
            {
              system: "http://snomed.info/sct",
              code: "17621005",
              display: "Normal (qualifier value)"
            }
          ]
        }
      }
    ]
  },
  event: [
    {
      code: [
        {
          coding: [
            {
              system: "http://terminology.hl7.org/CodeSystem/v3-ActClass",
              code: "PCPR",
              display: "care provision"
            }
          ]
        }
      ],
      period: {
        end: now
      }
    }
  ],
  author: [
    {
      reference: "Organization/" + organization.id
    }
  ],
  custodian: {
    reference: "Organization/" + organization.id
  },
  section: []
};

composition.text = buildCompositionNarrative(
  patient,
  vitalObservations,
  resultObservations,
  sortedConditions,
  sortedImmunizations,
  sortedMedicationStatements,
  sortedAllergyIntolerances
);

// ======================================================
// Sections
// ======================================================
if (sortedConditions.length) {
  composition.section.push({
    title: "Problemliste",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "11450-4",
          display: "Problem list - Reported"
        }
      ]
    },
    text: buildConditionSectionNarrative("Problemliste", sortedConditions),
    entry: sortedConditions.map(function(c) {
      return { reference: "Condition/" + c.id };
    })
  });
} else {
  composition.section.push({
    title: "Problemliste",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "11450-4",
          display: "Problem list - Reported"
        }
      ]
    },
    text: {
      status: "generated",
      div:
        '<div xmlns="http://www.w3.org/1999/xhtml" xml:lang="' + DOC_LANG + '" lang="' + DOC_LANG + '">' +
        '<p><b>Problemliste</b></p>' +
        '<p>Keine Problemressourcen im aktuellen Datensatz vorhanden.</p>' +
        '</div>'
    },
    emptyReason: {
      coding: [
        {
          system: "http://terminology.hl7.org/CodeSystem/list-empty-reason",
          code: "unavailable",
          display: "Unavailable"
        }
      ]
    }
  });
}

if (vitalObservations.length) {
  composition.section.push({
    title: "Vitalparameter",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "8716-3",
          display: "Vital signs"
        }
      ]
    },
    text: buildObservationSectionNarrative("Vitalparameter", vitalObservations),
    entry: vitalObservations.map(function(obs) {
      return { reference: "Observation/" + obs.id };
    })
  });
}

if (resultObservations.length) {
  composition.section.push({
    title: "Resultate",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "30954-2",
          display: "Relevant diagnostic tests/laboratory data Narrative"
        }
      ]
    },
    text: buildObservationSectionNarrative("Resultate", resultObservations),
    entry: resultObservations.map(function(obs) {
      return { reference: "Observation/" + obs.id };
    })
  });
}

if (sortedMedicationStatements.length) {
  composition.section.push({
    title: "Medikation",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "10160-0",
          display: "History of Medication use"
        }
      ]
    },
    text: buildMedicationSectionNarrative("Medikation", sortedMedicationStatements),
    entry: sortedMedicationStatements.map(function(ms) {
      return { reference: "MedicationStatement/" + ms.id };
    })
  });
}

if (sortedAllergyIntolerances.length) {
  composition.section.push({
    title: "Allergien und Intoleranzen",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "48765-2",
          display: "Allergies and adverse reactions Document"
        }
      ]
    },
    text: buildAllergySectionNarrative("Allergien und Intoleranzen", sortedAllergyIntolerances),
    entry: sortedAllergyIntolerances.map(function(ai) {
      return { reference: "AllergyIntolerance/" + ai.id };
    })
  });
}

if (sortedImmunizations.length) {
  composition.section.push({
    title: "Impfungen",
    code: {
      coding: [
        {
          system: "http://loinc.org",
          code: "11369-6",
          display: "History of Immunization"
        }
      ]
    },
    text: buildImmunizationSectionNarrative("Impfungen", sortedImmunizations),
    entry: sortedImmunizations.map(function(imm) {
      return { reference: "Immunization/" + imm.id };
    })
  });
}

if (goals.length) {

  composition.section.push({
    title: "Behandlungsziele",
    code: {
      coding: [{
        system: "http://loinc.org",
        code: "61146-7",
        display: "Goals"
      }]
    },
    entry: goals.map(function(g) {
      return {
        reference: "Goal/" + g.id
      };
    })
  });

}
// ======================================================
// Output Bundle
// ======================================================
const ipsBundle = {
  resourceType: "Bundle",
  id: docUuid,
  meta: {
    profile: [PROFILE_CH_IPS_DOCUMENT]
  },
  language: DOC_LANG,
  identifier: {
    system: "urn:ietf:rfc:3986",
    value: "urn:uuid:" + docUuid
  },
  type: "document",
  timestamp: now,
  entry: []
};

ipsBundle.entry.push({
  fullUrl: buildFullUrl(FULLURL_BASE, "Composition", composition.id),
  resource: composition
});

ipsBundle.entry.push({
  fullUrl: buildFullUrl(FULLURL_BASE, "Organization", organization.id),
  resource: organization
});

ipsBundle.entry.push({
  fullUrl: buildFullUrl(FULLURL_BASE, "Patient", patient.id),
  resource: patient
});

for (let i = 0; i < sortedConditions.length; i++) {
  ipsBundle.entry.push({
    fullUrl: buildFullUrl(FULLURL_BASE, "Condition", sortedConditions[i].id),
    resource: sortedConditions[i]
  });
}

for (let i = 0; i < vitalObservations.length; i++) {
  ipsBundle.entry.push({
    fullUrl: buildFullUrl(FULLURL_BASE, "Observation", vitalObservations[i].id),
    resource: vitalObservations[i]
  });
}

for (let i = 0; i < resultObservations.length; i++) {
  ipsBundle.entry.push({
    fullUrl: buildFullUrl(FULLURL_BASE, "Observation", resultObservations[i].id),
    resource: resultObservations[i]
  });
}

for (let i = 0; i < sortedMedicationStatements.length; i++) {
  ipsBundle.entry.push({
    fullUrl: buildFullUrl(FULLURL_BASE, "MedicationStatement", sortedMedicationStatements[i].id),
    resource: sortedMedicationStatements[i]
  });
}

for (let i = 0; i < sortedAllergyIntolerances.length; i++) {
  ipsBundle.entry.push({
    fullUrl: buildFullUrl(FULLURL_BASE, "AllergyIntolerance", sortedAllergyIntolerances[i].id),
    resource: sortedAllergyIntolerances[i]
  });
}

for (let i = 0; i < sortedImmunizations.length; i++) {
  ipsBundle.entry.push({
    fullUrl: buildFullUrl(FULLURL_BASE, "Immunization", sortedImmunizations[i].id),
    resource: sortedImmunizations[i]
  });
}

for (let i = 0; i < goals.length; i++) {

  ipsBundle.entry.push({
    fullUrl: buildFullUrl(
      FULLURL_BASE,
      "Goal",
      goals[i].id
    ),
    resource: goals[i]
  });

}

for (let i = 0; i < consents.length; i++) {

  ipsBundle.entry.push({
    fullUrl: buildFullUrl(
      FULLURL_BASE,
      "Consent",
      consents[i].id
    ),
    resource: consents[i]
  });

}

for (let i = 0; i < careTeams.length; i++) {

  ipsBundle.entry.push({
    fullUrl: buildFullUrl(
      FULLURL_BASE,
      "CareTeam",
      careTeams[i].id
    ),
    resource: careTeams[i]
  });

}

// ======================================================
// Bruno Variablen speichern
// ======================================================
bru.setVar("ipsBundle", JSON.stringify(ipsBundle, null, 2));

bru.setVar("ipsStats", JSON.stringify({
  patientId: patient.id,
  patientName: formatPatientName(patient),
  fullUrlBase: FULLURL_BASE,

  inputObservations: observations.length,
  relevantObservations: relevantObservations.length,

  conditionsSelected: sortedConditions.length,
  vitalSignsSelected: vitalObservations.length,
  resultsSelected: resultObservations.length,
  medicationsSelected: sortedMedicationStatements.length,
  allergiesSelected: sortedAllergyIntolerances.length,
  immunizationsSelected: sortedImmunizations.length,  
  goalsSelected: goals.length,
  consentsSelected: consents.length,
  careTeamsSelected: careTeams.length,
  
  conditionIds: sortedConditions.map(function(c) { return c.id; }),
  vitalSignsCodes: vitalObservations.map(function(o) { return getObservationCode(o); }),
  resultCodes: resultObservations.map(function(o) { return getObservationCode(o); }),
  medicationIds: sortedMedicationStatements.map(function(m) { return m.id; }),
  allergyIds: sortedAllergyIntolerances.map(function(a) { return a.id; }),
  immunizationIds: sortedImmunizations.map(function(i) { return i.id; }),
  goalIds: goals.map(function(g) {
  return g.id;
}),

consentIds: consents.map(function(c) {
  return c.id;
}),

careTeamIds: careTeams.map(function(ct) {
  return ct.id;
}),

  ignoredResourceTypes: Array.from(new Set(ignoredResourceTypes)),

  appliedProfiles: {
    bundle: PROFILE_CH_IPS_DOCUMENT,
    composition: PROFILE_CH_IPS_COMPOSITION,
    patient: PROFILE_CH_IPS_PATIENT,
    organization: PROFILE_CH_IPS_ORGANIZATION,
    condition: PROFILE_CH_IPS_CONDITION,
    medicationStatement: PROFILE_CH_IPS_MEDICATIONSTATEMENT,
    allergyIntolerance: PROFILE_CH_IPS_ALLERGYINTOLERANCE,
    immunization: PROFILE_CH_IPS_IMMUNIZATION
  }
}, null, 2));

console.log("CH-IPS Bundle clean erzeugt und in {{ipsBundle}} gespeichert.");
console.log("Statistik wurde in {{ipsStats}} gespeichert.");
// ======================================================
// Bruno Visualisierung der Response als FHIR Bundle
// ======================================================
function responseVisEscapeHtml(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function responseVisGetBundle() {
  const raw = bru.getVar("ipsBundle");
  if (raw) {
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  }

  if (inputBundle && inputBundle.resourceType === "Bundle") {
    return inputBundle;
  }

  if (inputBundle && inputBundle.resourceType) {
    return {
      resourceType: "Bundle",
      type: "collection",
      entry: [
        {
          fullUrl: "urn:uuid:" + (inputBundle.id || "resource"),
          resource: inputBundle
        }
      ]
    };
  }

  return {
    resourceType: "Bundle",
    type: "collection",
    entry: []
  };
}

function responseVisFindFirst(bundle, resourceType) {
  if (!bundle || !Array.isArray(bundle.entry)) return null;

  const found = bundle.entry.find(function(e) {
    return e && e.resource && e.resource.resourceType === resourceType;
  });

  return found ? found.resource : null;
}

function responseVisFindByReference(bundle, reference) {
  if (!bundle || !Array.isArray(bundle.entry) || !reference) return null;

  const found = bundle.entry.find(function(e) {
    return (
      e &&
      e.resource &&
      e.resource.resourceType + "/" + e.resource.id === reference
    );
  });

  return found ? found.resource : null;
}

function responseVisResourceTypeCounts(bundle) {
  const counts = {};

  if (!bundle || !Array.isArray(bundle.entry)) return counts;

  bundle.entry.forEach(function(e) {
    if (!e || !e.resource || !e.resource.resourceType) return;
    const rt = e.resource.resourceType;
    counts[rt] = (counts[rt] || 0) + 1;
  });

  return counts;
}

function responseVisPatientName(patient) {
  if (!patient || !patient.name || !patient.name.length) {
    return "Unbekannter Patient";
  }

  const n = patient.name[0];
  const given = Array.isArray(n.given) ? n.given.join(" ") : "";
  return [given, n.family || ""].filter(Boolean).join(" ") || "Unbekannter Patient";
}

function responseVisGetDisplayText(resource) {
  if (!resource) return "";

  if (resource.resourceType === "Patient") {
    return responseVisPatientName(resource);
  }

  if (resource.resourceType === "Encounter") {
    const status = resource.status || "";
    const period = resource.period || {};
    const range = [period.start, period.end].filter(Boolean).join(" → ");
    return [status, range].filter(Boolean).join(" | ");
  }

  if (resource.resourceType === "Observation") {
    const code = resource.code && resource.code.coding && resource.code.coding[0] && resource.code.coding[0].display
      ? resource.code.coding[0].display
      : (resource.code && resource.code.text ? resource.code.text : "");
    const value = resource.valueString || resource.valueQuantity || resource.valueCodeableConcept || "";
    return [code, value].filter(Boolean).join(" | ");
  }

  if (resource.resourceType === "MedicationStatement") {
    return resource.medicationCodeableConcept && resource.medicationCodeableConcept.text
      ? resource.medicationCodeableConcept.text
      : "";
  }

  if (resource.resourceType === "AllergyIntolerance") {
    return resource.code && resource.code.text ? resource.code.text : "";
  }

  if (resource.resourceType === "Organization") {
    return resource.name || "";
  }

  if (resource.resourceType === "Condition") {
    return resource.code && resource.code.text ? resource.code.text : "";
  }

  if (resource.identifier && resource.identifier.length) {
    const first = resource.identifier[0];
    return [first.system, first.value].filter(Boolean).join(": ");
  }

  return "";
}

function responseVisRenderXhtml(div) {
  if (!div) {
    return '<p class="empty">Keine Narrative vorhanden</p>';
  }

  return div;
}

function responseVisRenderStats(bundle, composition) {
  const counts = responseVisResourceTypeCounts(bundle);
  const countCards = Object.keys(counts)
    .sort()
    .map(function(rt) {
      return `
        <div class="stat-card">
          <div class="stat-value">${counts[rt]}</div>
          <div class="stat-label">${responseVisEscapeHtml(rt)}</div>
        </div>
      `;
    })
    .join("");

  return `
    <div class="stats-grid">
      <div class="stat-card primary">
        <div class="stat-value">${bundle && Array.isArray(bundle.entry) ? bundle.entry.length : 0}</div>
        <div class="stat-label">Bundle Entries</div>
      </div>
      <div class="stat-card primary">
        <div class="stat-value">${composition && composition.section ? composition.section.length : 0}</div>
        <div class="stat-label">Composition Sections</div>
      </div>
      <div class="stat-card primary">
        <div class="stat-value">${bundle && bundle.total != null ? bundle.total : "-"}</div>
        <div class="stat-label">Bundle Total</div>
      </div>
      ${countCards}
    </div>
  `;
}

function responseVisRenderCompositionSections(bundle, composition) {
  if (!composition || !Array.isArray(composition.section)) {
    return '<p class="empty">Keine Sections in der Composition gefunden.</p>';
  }

  return composition.section
    .map(function(sec, index) {
      const entries = Array.isArray(sec.entry) ? sec.entry : [];

      const entryLinks = entries
        .map(function(ref) {
          const target = responseVisFindByReference(bundle, ref.reference);
          const label = ref.reference || "Reference";
          const type = target ? target.resourceType : "unresolved";

          return `
            <li>
              <code>${responseVisEscapeHtml(label)}</code>
              <span class="muted">(${responseVisEscapeHtml(type)})</span>
            </li>
          `;
        })
        .join("");

      const sectionCode =
        sec.code &&
        sec.code.coding &&
        sec.code.coding[0] &&
        sec.code.coding[0].code
          ? sec.code.coding[0].code
          : "";

      return `
        <section class="section-card">
          <div class="section-header">
            <div>
              <div class="section-number">Section ${index + 1}</div>
              <h3>${responseVisEscapeHtml(sec.title || "Ohne Titel")}</h3>
            </div>

            <div class="section-code">
              ${responseVisEscapeHtml(sectionCode)}
            </div>
          </div>

          <div class="section-narrative">
            ${responseVisRenderXhtml(sec.text && sec.text.div)}
          </div>

          ${
            entries.length
              ? `
                <details>
                  <summary>Referenzen anzeigen (${entries.length})</summary>
                  <ul>${entryLinks}</ul>
                </details>
              `
              : ""
          }
        </section>
      `;
    })
    .join("");
}

function responseVisRenderEntrySections(bundle) {
  if (!bundle || !Array.isArray(bundle.entry)) {
    return '<p class="empty">Keine Bundle Entries gefunden.</p>';
  }

  return bundle.entry
    .map(function(entry, index) {
      const resource = entry && entry.resource ? entry.resource : {};
      const resourceType = resource.resourceType || "Resource";
      const title = resource.title || resource.name || resourceType + (resource.id ? " / " + resource.id : "");
      const profile = resource.meta && resource.meta.profile && resource.meta.profile[0]
        ? resource.meta.profile[0]
        : "";
      const narrative = resource.text && resource.text.div
        ? resource.text.div
        : (resource.text && resource.text.status ? resource.text.status : "");
      const sectionTitles = Array.isArray(resource.section)
        ? resource.section
            .map(function(sec) {
              return sec && (sec.title || (sec.code && sec.code.text) || "Section");
            })
            .filter(Boolean)
        : [];

      const sectionListHtml = sectionTitles.length
        ? '<ul class="section-ref-list">' +
          sectionTitles.map(function(label) {
            return '<li>' + responseVisEscapeHtml(label) + '</li>';
          }).join("") +
          '</ul>'
        : '<p class="muted">Keine Sections</p>';

      return `
        <section class="section-card">
          <div class="section-header">
            <div>
              <div class="section-number">Entry ${index + 1}</div>
              <h3>${responseVisEscapeHtml(title)}</h3>
            </div>

            <div class="section-code">
              ${responseVisEscapeHtml(resourceType)}
            </div>
          </div>

          <div class="section-narrative">
            <p><strong>ID:</strong> ${responseVisEscapeHtml(resource.id || "")}</p>
            ${profile ? '<p><strong>Profil:</strong> ' + responseVisEscapeHtml(profile) + '</p>' : ""}
            <p><strong>fullUrl:</strong> ${responseVisEscapeHtml(entry.fullUrl || "")}</p>
            ${narrative ? responseVisRenderXhtml(narrative) : '<p class="empty">Keine Narrative vorhanden</p>'}
            ${sectionTitles.length ? '<p><strong>Sections:</strong></p>' + sectionListHtml : ""}
          </div>
        </section>
      `;
    })
    .join("");
}

function responseVisRenderResourceTable(bundle) {
  if (!bundle || !Array.isArray(bundle.entry)) {
    return '<p class="empty">Keine Bundle Entries gefunden.</p>';
  }

  return `
    <table class="resource-table">
      <thead>
        <tr>
          <th>#</th>
          <th>ResourceType</th>
          <th>ID</th>
          <th>Beschreibung</th>
          <th>fullUrl</th>
        </tr>
      </thead>
      <tbody>
        ${bundle.entry.map(function(e, idx) {
          const r = e.resource || {};
          return `
            <tr>
              <td>${idx + 1}</td>
              <td><span class="pill">${responseVisEscapeHtml(r.resourceType || "")}</span></td>
              <td><code>${responseVisEscapeHtml(r.id || "")}</code></td>
              <td>${responseVisEscapeHtml(responseVisGetDisplayText(r))}</td>
              <td><code>${responseVisEscapeHtml(e.fullUrl || "")}</code></td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
}

function responseVisStyles() {
  return `
    <style>
      :root {
        --text: #111827;
        --muted: #6b7280;
        --border: #d1d5db;
        --soft-border: #e5e7eb;
        --soft-bg: #f9fafb;
        --header-bg: #f3f4f6;
        --blue: #2563eb;
        --green: #16a34a;
      }
      body { margin: 0; padding: 18px; font-family: Arial, sans-serif; color: var(--text); background: #ffffff; }
      h1, h2, h3 { margin-top: 0; }
      .top-box { border: 1px solid var(--soft-border); background: var(--soft-bg); border-radius: 10px; padding: 14px; margin-bottom: 18px; }
      .muted { color: var(--muted); }
      code { font-family: Consolas, Monaco, monospace; font-size: 12px; }
      .stats-grid { display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0 22px 0; }
      .stat-card { min-width: 130px; border: 1px solid var(--soft-border); border-radius: 8px; padding: 10px; background: #ffffff; }
      .stat-card.primary { background: #eff6ff; border-color: #bfdbfe; }
      .stat-value { font-size: 22px; font-weight: bold; color: var(--blue); }
      .stat-label { font-size: 12px; color: var(--muted); }
      .resource-table { width: 100%; border-collapse: collapse; }
      .resource-table th, .resource-table td { border: 1px solid var(--border); padding: 7px; text-align: left; vertical-align: top; }
      .resource-table th { background: var(--header-bg); }
      .pill { display: inline-block; padding: 2px 7px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-weight: bold; font-size: 12px; }
      .section-card { border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 16px; background: #ffffff; }
      .section-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--soft-border); padding-bottom: 8px; margin-bottom: 12px; }
      .section-number { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
      .section-code { font-size: 12px; color: var(--green); font-weight: bold; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 999px; padding: 4px 8px; white-space: nowrap; }
      .section-narrative table { border-collapse: collapse; width: 100%; margin-top: 8px; }
      .section-ref-list { margin: 6px 0 0 0; padding-left: 18px; }
      .section-narrative th, .section-narrative td { border: 1px solid var(--border); padding: 7px; text-align: left; vertical-align: top; }
      .section-narrative th { background: var(--header-bg); }
      details { margin-top: 10px; }
      summary { cursor: pointer; color: var(--blue); font-weight: bold; }
      .empty { color: var(--muted); font-style: italic; }
      .raw-json { background: #111827; color: #f9fafb; padding: 12px; border-radius: 8px; max-height: 500px; overflow: auto; font-size: 12px; }
    </style>
  `;
}

function responseVisSectionTitle(section) {
  if (!section) return "Unbenannte Section";
  if (section.title) return section.title;
  if (section.code && section.code.text) return section.code.text;
  return "Unbenannte Section";
}

function responseVisSectionCode(section) {
  if (!section || !section.code) return "";

  if (section.code.coding && section.code.coding.length) {
    const coding = section.code.coding[0];
    return [coding.code, coding.display].filter(Boolean).join(" · ");
  }

  return section.code.text || "";
}

function responseVisSectionNarrative(section) {
  if (!section || !section.text) return "";

  if (typeof section.text === "string") {
    return section.text;
  }

  if (section.text.div) {
    return section.text.div;
  }

  if (section.text.status) {
    return section.text.status;
  }

  return "";
}

function responseVisResolveReferences(bundle, section) {
  if (!bundle || !section || !Array.isArray(section.entry)) {
    return [];
  }

  const refs = [];

  section.entry.forEach(function(entry) {
    if (!entry || !entry.reference) return;

    const targetRef = entry.reference;
    const match = bundle.entry && bundle.entry.find(function(item) {
      if (!item || !item.resource) return false;
      return item.resource.resourceType + "/" + item.resource.id === targetRef;
    });

    if (match && match.resource) {
      refs.push({
        reference: targetRef,
        resourceType: match.resource.resourceType,
        id: match.resource.id
      });
    } else {
      refs.push({
        reference: targetRef,
        resourceType: "unresolved",
        id: ""
      });
    }
  });

  return refs;
}

function responseVisRenderSectionNarratives(bundle) {
  const composition = responseVisFindFirst(bundle, "Composition");

  if (!composition || !Array.isArray(composition.section) || composition.section.length === 0) {
    return '<p class="empty">Keine Section-Narratives gefunden.</p>';
  }

  const cards = composition.section.map(function(section, index) {
    const title = responseVisSectionTitle(section);
    const code = responseVisSectionCode(section);
    const narrative = responseVisSectionNarrative(section);
    const refs = responseVisResolveReferences(bundle, section);

    const refsHtml = refs.length
      ? '<ul class="section-ref-list">' +
        refs.map(function(ref) {
          return '<li><code>' + responseVisEscapeHtml(ref.reference) + '</code> <span class="muted">(' + responseVisEscapeHtml(ref.resourceType) + ')</span></li>';
        }).join("") +
        '</ul>'
      : '<p class="muted">Keine Referenzen</p>';

    return `
      <div class="section-card">
        <div class="section-head">
          <div>
            <div class="section-title">${responseVisEscapeHtml(title || "Section " + (index + 1))}</div>
            <div class="section-meta">Section ${index + 1}</div>
          </div>
          ${code ? '<div class="section-code">' + responseVisEscapeHtml(code) + '</div>' : ""}
        </div>

        <div class="section-narrative">
          ${narrative ? narrative : '<span class="empty">Kein Narrative-Text vorhanden</span>'}
        </div>

        <div class="section-meta">
          <strong>Referenzen:</strong>
          ${refsHtml}
        </div>
      </div>
    `;
  });

  return '<div class="section-grid">' + cards.join("") + '</div>';
}

function responseVisBuildHtml() {
  const bundle = responseVisGetBundle();
  const composition = responseVisFindFirst(bundle, "Composition");
  const patient = responseVisFindFirst(bundle, "Patient");

  return `
    <html lang="de">
      <head>
        <meta charset="UTF-8" />
        <title>FHIR Response Visualisierung</title>
        ${responseVisStyles()}
      </head>
      <body>
        <h1>FHIR Response Visualisierung</h1>
        <div class="top-box">
          <p><b>Bundle Typ:</b> ${responseVisEscapeHtml(bundle.type || "")}</p>
          <p><b>Bundle ID:</b> ${responseVisEscapeHtml(bundle.id || "")}</p>
          <p><b>Patient:</b> ${responseVisEscapeHtml(responseVisPatientName(patient))}</p>
          <p class="muted">Quelle: Bruno Variable <code>ipsBundle</code> oder Response Body</p>
        </div>

        <h2>Übersicht</h2>
        ${responseVisRenderStats(bundle, composition)}

        <h2>IPS Sections</h2>
        ${responseVisRenderCompositionSections(bundle, composition)}

        <h2>Alle Entries als Sections</h2>
        ${responseVisRenderEntrySections(bundle)}

        <h2>Ressourcenübersicht</h2>
        ${responseVisRenderResourceTable(bundle)}

        <h2>Raw JSON</h2>
        <pre class="raw-json">${responseVisEscapeHtml(JSON.stringify(bundle, null, 2))}</pre>
      </body>
    </html>
  `;
}

bru.setVar("responseBundle", JSON.stringify(responseVisGetBundle(), null, 2));

bru.visualize("html", {
  name: "FHIR Response",
  content: responseVisBuildHtml()
});