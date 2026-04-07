// CloudEMS Groepenkast Card v3.0
// Geïntegreerde elektrische normendatabase — 50+ landen (IEC 60364 basis)
// CloudEMS Electrical Standards Database
// Wereldwijde laagspanningsnormen gebaseerd op IEC 60364 en nationale implementaties
// Gebruikt door cloudems-groepenkast-card.js voor NEN/AREI/VDE/BS etc. validatie

const ELECTRICAL_STANDARDS = {
  // ── EUROPA ───────────────────────────────────────────────────────────────────

  NL: {
    name: 'NEN 1010', fullName: 'NEN 1010:2015 (Nederlandse installatiepraktijk)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: 4, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: true },
    notes: 'Maximaal 4 eindgroepen per 30mA aardlekschakelaar (art. 531.3).',
  },
  BE: {
    name: 'AREI', fullName: 'Algemeen Reglement op de Elektrische Installaties (AREI)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: 8, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: true },
    notes: 'Max 8 groepen per 30mA aardlekschakelaar. Type A verplicht.',
  },
  FR: {
    name: 'NF C 15-100', fullName: 'NF C 15-100 (Installations électriques à basse tension)',
    voltage: 230, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: 8, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: true },
    notes: 'TT-stelsel verplicht. Max 8 circuits per 30mA DDR. Aparte groep voor elk groot apparaat.',
  },
  DE: {
    name: 'VDE 0100', fullName: 'DIN VDE 0100 (Errichten von Niederspannungsanlagen)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'FI-Schutzschalter verplicht voor badkamer/buitenstopcontacten. Geen vaste max per RCD.',
  },
  GB: {
    name: 'BS 7671', fullName: 'BS 7671:2018+A2:2022 (IET Wiring Regulations, 18th Edition)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: true },
    notes: 'RCD protection verplicht voor alle stopcontacten ≤32A (2022 amendement).',
  },
  IT: {
    name: 'CEI 64-8', fullName: 'CEI 64-8 (Impianti elettrici utilizzatori)',
    voltage: 230, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: 6, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Differenziale verplicht. TT-stelsel gebruikelijk. Max 6 groepen per 30mA.',
  },
  ES: {
    name: 'REBT', fullName: 'Reglamento Electrotécnico para Baja Tensión (ITC-BT)',
    voltage: 230, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, maxGroupsPerRCD100mA: null, rcdRequired: true,
    rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'IDA verplicht. TT-stelsel. Verdeelkast per woning verplicht.',
  },
  PT: {
    name: 'RTIEBT', fullName: 'Regras Técnicas das Instalações Elétricas de Baixa Tensão',
    voltage: 230, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op HD 60364. Disjuntor diferencial verplicht.',
  },
  AT: {
    name: 'OVE E 8001', fullName: 'OVE E 8001 (Österreichische Elektrotechnische Norm)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. FI-Schutzschalter standaard.',
  },
  CH: {
    name: 'NIN / NIV', fullName: 'NIN 2020 (Niederspannungs-Installationsnorm)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Fehlerstromschutzschalter verplicht in natte ruimten.',
  },
  NO: {
    name: 'NEK 400', fullName: 'NEK 400:2018 (Elektriske lavspenningsanlegg)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Jordfeilbryter verplicht in natte ruimten.',
  },
  SE: {
    name: 'SS 437 01 40', fullName: 'SS 437 01 40 (Svenska elinstallationsregler)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Jordfelsbrytare verplicht.',
  },
  DK: {
    name: 'DS/EN 60364', fullName: 'DS 6007 Stærkstrømsbekendtgørelsen',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'HPFI (type F) aanbevolen. Gebaseerd op IEC 60364.',
  },
  FI: {
    name: 'SFS 6000', fullName: 'SFS 6000 (Pienjännitesähköasennukset)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Vikavirtasuoja verplicht in natte ruimten.',
  },
  PL: {
    name: 'PN-IEC 60364', fullName: 'PN-HD 60364 (Instalacje elektryczne niskiego napięcia)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Wyłącznik różnicowoprądowy verplicht.',
  },
  CZ: {
    name: 'ČSN 33 2000', fullName: 'ČSN 33 2000-1 (Elektrické instalace nízkého napětí)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  RO: {
    name: 'PE 107 / SR HD 60364',
    fullName: 'SR HD 60364 (Instalații electrice de joasă tensiune)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  GR: {
    name: 'HD 384 / ELOT',
    fullName: 'ELOT HD 384 (Ηλεκτρικές εγκαταστάσεις κτιρίων)',
    voltage: 230, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. TT-stelsel gebruikelijk.',
  },
  LU: {
    name: 'PAN / IEC 60364', fullName: "Prescriptions d'Alimentation Normales (PAN)",
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Vergelijkbaar met Belgische AREI.',
  },
  HR: {
    name: 'HRN HD 60364', fullName: 'HRN HD 60364 (Elektroinstalacije niskog napona)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  HU: {
    name: 'MSZ EN 60364', fullName: 'MSZ EN 60364 (Épületek villamos berendezései)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  SK: {
    name: 'STN 33 2000', fullName: 'STN HD 60364 (Elektrické inštalácie nízkeho napätia)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  SI: {
    name: 'SIST HD 60364', fullName: 'SIST HD 60364 (Nizkonapetostne električne inštalacije)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  RS: {
    name: 'SRPS HD 60364', fullName: 'SRPS HD 60364',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  UA: {
    name: 'ДСТУ HD 60364', fullName: 'ДСТУ EN 60364 (Електроустановки будівель)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  RU: {
    name: 'ПУЭ (PUE)', fullName: 'Правила устройства электроустановок (ПУЭ 7)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: false, outdoor: false, kitchen: false },
    notes: 'УЗО (RCD) niet wettelijk verplicht maar sterk aanbevolen. Gebaseerd op pre-IEC normen.',
  },

  // ── NOORD-AMERIKA ─────────────────────────────────────────────────────────────

  US: {
    name: 'NEC (NFPA 70)', fullName: 'National Electrical Code NFPA 70 (2023)',
    voltage: 120, freq: 60, earthing: 'TN-S',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: null, rcdSensitivity: 5,
    requires: { bathroom: true, outdoor: true, kitchen: true },
    notes: 'GFCI (5mA) ipv RCD. Breaker panel (200A typical). 120/240V split phase. Arc-fault (AFCI) verplicht voor slaapkamers.',
  },
  CA: {
    name: 'CEC', fullName: 'Canadian Electrical Code CSA C22.1 (2021)',
    voltage: 120, freq: 60, earthing: 'TN-S',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: null, rcdSensitivity: 5,
    requires: { bathroom: true, outdoor: true, kitchen: true },
    notes: 'GFCI verplicht in vochtige ruimten. Vergelijkbaar met NEC.',
  },
  MX: {
    name: 'NOM-001-SEDE', fullName: 'Norma Oficial Mexicana NOM-001-SEDE',
    voltage: 127, freq: 60, earthing: 'TN-S',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: null, rcdSensitivity: 5,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op NEC. GFCI voor vochtige ruimten.',
  },

  // ── LATIJNS-AMERIKA ───────────────────────────────────────────────────────────

  BR: {
    name: 'ABNT NBR 5410', fullName: 'ABNT NBR 5410 (Instalações elétricas de baixa tensão)',
    voltage: 127, freq: 60, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. DR (aardlek) verplicht in vochtige ruimten. 127V of 220V (regio afhankelijk).',
  },
  AR: {
    name: 'IRAM 2281', fullName: 'IRAM 2281 (Instalaciones eléctricas en inmuebles)',
    voltage: 220, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. DDI (diferencial) aanbevolen.',
  },
  CL: {
    name: 'SEC / NCh Elec 4/2003', fullName: 'Norma Chilena Oficial NCh Elec 4/2003',
    voltage: 220, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },

  // ── AZIË-PACIFIC ─────────────────────────────────────────────────────────────

  AU: {
    name: 'AS/NZS 3000', fullName: 'AS/NZS 3000:2018 (Wiring Rules)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'RCD verplicht voor alle stopcontacten en verlichtingsgroepen (2019 update). Gebaseerd op IEC 60364.',
  },
  NZ: {
    name: 'AS/NZS 3000', fullName: 'AS/NZS 3000:2018 (Wiring Rules — New Zealand)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Identiek aan Australisch AS/NZS 3000.',
  },
  JP: {
    name: 'JIS C 0364 / 内線規程', fullName: 'JIS C 0364 (内線規程 JEAC 8001)',
    voltage: 100, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: null, rcdSensitivity: 15,
    requires: { bathroom: true, outdoor: false, kitchen: false },
    notes: '100V systeem (50Hz oost / 60Hz west Japan). Aardlekautomaat (漏電遮断器) 15mA. Geen RCD standaard verplicht.',
  },
  CN: {
    name: 'GB 50054 / GB 16895', fullName: 'GB 50054 低压配电设计规范',
    voltage: 220, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. 漏电保护器 (RCD) verplicht in vochtige ruimten.',
  },
  IN: {
    name: 'NBC (NEC India)', fullName: 'National Building Code / IS 732 (India)',
    voltage: 230, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. ELCB/RCCB verplicht in vochtige ruimten.',
  },
  SG: {
    name: 'SS 638', fullName: 'SS 638:2018 (Code of Practice for Electrical Installations)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op BS 7671. RCD verplicht voor stopcontacten ≤32A.',
  },
  HK: {
    name: 'CoP (EMSD)', fullName: 'Code of Practice for Electricity (Wiring) Regulations (HK)',
    voltage: 220, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op BS 7671. RCCB verplicht voor vochtige ruimten.',
  },
  KR: {
    name: 'KEC (전기설비기술기준)', fullName: '전기설비기술기준 (Korean Electrical Code)',
    voltage: 220, freq: 60, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: '60Hz. 누전차단기 (RCCB) verplicht in vochtige ruimten.',
  },
  TW: {
    name: 'NEC (TW adaptation)', fullName: '屋內線路裝置規則 (Taiwan Wiring Regulations)',
    voltage: 110, freq: 60, earthing: 'TN-S',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: null, rcdSensitivity: 5,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: '110V/220V, 60Hz. Gebaseerd op NEC. GFCI in vochtige ruimten.',
  },
  TH: {
    name: 'EIT / MEA Standard', fullName: 'มาตรฐานการติดตั้งทางไฟฟ้า (EIT)',
    voltage: 220, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },
  ID: {
    name: 'PUIL 2011', fullName: 'Persyaratan Umum Instalasi Listrik (PUIL 2011)',
    voltage: 220, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },

  // ── MIDDEN-OOSTEN ─────────────────────────────────────────────────────────────

  AE: {
    name: 'DEWA / ADDC Standards', fullName: 'UAE Electrical Wiring Regulations (IEC based)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op BS 7671 en IEC 60364. RCD verplicht.',
  },
  SA: {
    name: 'SASO / SBC', fullName: 'Saudi Building Code Electrical (SBC 401)',
    voltage: 127, freq: 60, earthing: 'TN-S',
    maxGroupsPerRCD30mA: null, rcdRequired: false, rcdTypeDefault: null, rcdSensitivity: 5,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: '127V/220V, 60Hz. Gebaseerd op NEC. GFCI in vochtige ruimten.',
  },
  IL: {
    name: 'SI 900', fullName: 'תקן ישראלי SI 900 (התקנת מתקנים חשמליים)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },

  // ── AFRIKA ────────────────────────────────────────────────────────────────────

  ZA: {
    name: 'SANS 10142', fullName: 'SANS 10142-1:2017 (Wiring of Premises)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364. Earth Leakage Protection verplicht.',
  },
  NG: {
    name: 'Nigerian Electrical Code', fullName: 'NEC Nigeria (based on BS 7671)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op BS 7671.',
  },
  EG: {
    name: 'EIC / IEC 60364', fullName: 'Egyptian Electrical Code (IEC based)',
    voltage: 220, freq: 50, earthing: 'TT',
    maxGroupsPerRCD30mA: null, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Gebaseerd op IEC 60364.',
  },

  // ── STANDAARD FALLBACK ────────────────────────────────────────────────────────

  DEFAULT: {
    name: 'IEC 60364', fullName: 'IEC 60364 (International Standard)',
    voltage: 230, freq: 50, earthing: 'TN-C-S',
    maxGroupsPerRCD30mA: 8, rcdRequired: true, rcdTypeDefault: 'A', rcdSensitivity: 30,
    requires: { bathroom: true, outdoor: true, kitchen: false },
    notes: 'Internationale standaard IEC 60364. Meeste nationale normen zijn hier op gebaseerd.',
  },
};

// Helper: geef de standaard voor een land terug, met fallback
function getStandard(countryCode) {
  if (!countryCode) return ELECTRICAL_STANDARDS.DEFAULT;
  const cc = countryCode.toUpperCase().trim();
  return ELECTRICAL_STANDARDS[cc] || ELECTRICAL_STANDARDS.DEFAULT;
}

// Visuele groepenkast builder — volledig configureerbaar
// Alle types: hoofdschakelaar, aardlek A/B 2P/4P, RCBO, MCB 1F/3F, PV 1P+N/3F/DC
// Drag-and-drop, labels, merken, leer-wizard

if (!customElements.get('cloudems-groepenkast-card')) {

const BRANDS = ['(geen)','EMAT','ABB','Hager','Schneider Electric','Siemens','Legrand','Eaton','Gewiss','Doepke','Schrack','OEZ','Mennekes','Finder','Niko','Jung','Busch-Jaeger'];

// ── Europese elektrische installatienormen (gebaseerd op HD 60364) ────────────
const EU_NORMS = {
  // Land: { norm, maxGroupsPerRCD, rcdMa, requireRCD, voltageV, notes }
  NL: { norm:'NEN 1010',          maxGroups:4, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇳🇱' },
  BE: { norm:'AREI / RGIE',       maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇧🇪',
        notes:'AREI art. 86: max 8 groepen per 30mA aardlek' },
  DE: { norm:'DIN VDE 0100',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇩🇪' },
  FR: { norm:'NF C 15-100',       maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇫🇷',
        notes:'NF C 15-100 art. 771: max 8 circuits per 30mA' },
  GB: { norm:'BS 7671 (IET 18e)', maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇬🇧' },
  IE: { norm:'IS 10101',          maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇮🇪' },
  AT: { norm:'ÖVE/ÖNORM E 8001', maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇦🇹' },
  CH: { norm:'NIV / NIN 2020',    maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇨🇭' },
  ES: { norm:'REBT ITC-BT',       maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇪🇸' },
  IT: { norm:'CEI 64-8',          maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇮🇹' },
  PT: { norm:'RTIEBT',            maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇵🇹' },
  SE: { norm:'SS-EN 60364',       maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇸🇪' },
  NO: { norm:'NEK 400',           maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇳🇴' },
  DK: { norm:'DS / Stærkstrøm',   maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇩🇰' },
  FI: { norm:'SFS 6000',          maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇫🇮' },
  PL: { norm:'PN-HD 60364',       maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇵🇱' },
  CZ: { norm:'ČSN 33 2000',       maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇨🇿' },
  SK: { norm:'STN 33 2000',       maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇸🇰' },
  HU: { norm:'MSZ HD 60364',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇭🇺' },
  RO: { norm:'PE 155 / I7',       maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇷🇴' },
  BG: { norm:'BDS EN 60364',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇧🇬' },
  GR: { norm:'ELOT HD 60364',     maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇬🇷' },
  HR: { norm:'HRN HD 60364',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇭🇷' },
  SI: { norm:'SIST HD 60364',     maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇸🇮' },
  EE: { norm:'EVS-HD 60364',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇪🇪' },
  LV: { norm:'LVS HD 60364',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇱🇻' },
  LT: { norm:'LST HD 60364',      maxGroups:6, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇱🇹' },
  LU: { norm:'NF C 15-100',       maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇱🇺' },
  MT: { norm:'BS 7671',           maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇲🇹' },
  CY: { norm:'BS 7671',           maxGroups:8, rcdMa:30,  requireRCD:true,  voltage:230, flag:'🇨🇾' },
  // Buiten Europa: geen regels (nog)
  _DEFAULT: { norm:'HD 60364',    maxGroups:8, rcdMa:30,  requireRCD:false, voltage:230, flag:'🌍' },
};
const PHASES = ['L1','L2','L3','3F'];
const AMPS_MAIN = [16,25,32,40,50,63,80,100];
const AMPS_RCD  = [25,40,63,80,100];
const AMPS_MCB  = [6,10,13,16,20,25,32];
const MA_OPTS   = [10,30,100,300,500];
const KAR_OPTS  = ['B','C','D'];
const PC = {L1:'#f97316',L2:'#3b82f6',L3:'#22c55e','3F':'#a855f7',DC:'#4ade80','':'#444'};

// Samengevouwen component definities — elke groep heeft één item met een variant-dropdown
// EMAT standaard defaults: hoofdschakelaar 40A, aardlek 40A/30mA, automaat 16A B-kar
const COMP_DEFS = [
  {group:'Hoofdschakelaar', dot:'#6a6ab0', badge:null,
   variants:[
     {label:'1F (2P)', type:'main_2p', color:'#1e1e2e', modules:2, specs:{amp:AMPS_MAIN, poles:'2P'}, def:{amp:40}},
     {label:'3F (4P)', type:'main_4p', color:'#1e1e2e', modules:4, specs:{amp:AMPS_MAIN, poles:'4P'}, def:{amp:40}},
   ], defaultSpecs:{amp:AMPS_MAIN}
  },
  {group:'Aardlekschakelaar', dot:'#f97316', badge:null,
   variants:[
     {label:'2P Type A', type:'rcd_2p_a', color:'#2a1800', modules:2, dot:'#f97316', specs:{amp:AMPS_RCD, ma:MA_OPTS, rcdType:'A', poles:'2P'}, def:{amp:40, ma:30}},
     {label:'2P Type B', type:'rcd_2p_b', color:'#2a0d00', modules:2, dot:'#ef4444', specs:{amp:AMPS_RCD, ma:MA_OPTS, rcdType:'B', poles:'2P'}, badge:'EV/PV', def:{amp:40, ma:30}},
     {label:'4P Type A', type:'rcd_4p_a', color:'#2a1800', modules:4, dot:'#f97316', specs:{amp:AMPS_RCD, ma:MA_OPTS, rcdType:'A', poles:'4P'}, def:{amp:40, ma:30}},
     {label:'4P Type B', type:'rcd_4p_b', color:'#2a0d00', modules:4, dot:'#ef4444', specs:{amp:AMPS_RCD, ma:MA_OPTS, rcdType:'B', poles:'4P'}, badge:'EV/PV', def:{amp:40, ma:30}},
   ], defaultSpecs:{amp:AMPS_RCD, ma:MA_OPTS}
  },
  {group:'Aardlekautomaat (RCBO)', dot:'#f59e0b', badge:null,
   variants:[
     {label:'1P+N',  type:'rcbo_1pn', color:'#1e1200', modules:2, specs:{amp:AMPS_MCB, ma:[30,100], kar:KAR_OPTS, poles:'1P+N'}, def:{amp:16, ma:30, kar:'B'}},
     {label:'2P',    type:'rcbo_2p',  color:'#1e1200', modules:2, dot:'#fbbf24', specs:{amp:AMPS_MCB, ma:[30,100], kar:KAR_OPTS, poles:'2P'}, def:{amp:16, ma:30, kar:'B'}, badge:'FR/BE'},
     {label:'3P+N',  type:'rcbo_3pn', color:'#1e1200', modules:4, specs:{amp:AMPS_MCB, ma:[30,100], kar:KAR_OPTS, poles:'3P+N'}, def:{amp:16, ma:30, kar:'B'}},
   ], defaultSpecs:{amp:AMPS_MCB, ma:[30,100], kar:KAR_OPTS}
  },
  {group:'Schakelautomaat', dot:'#3b82f6', badge:null,
   variants:[
     {label:'1-fase (1P+N)', type:'mcb_1p',  color:'#0e0e18', modules:1, specs:{amp:AMPS_MCB, kar:KAR_OPTS, phase:PHASES}, def:{amp:16, kar:'B', phase:'L1'}},
     {label:'2-fase (2P)',   type:'mcb_2p',  color:'#0e0e18', modules:2, dot:'#60a5fa', specs:{amp:AMPS_MCB, kar:KAR_OPTS, phase:PHASES}, def:{amp:16, kar:'B', phase:'L1'}, badge:'FR/DE'},
     {label:'1P (UK-stijl)', type:'mcb_1p_uk', color:'#0e0e18', modules:1, dot:'#94a3b8', specs:{amp:AMPS_MCB, kar:['B','C'], phase:PHASES}, def:{amp:16, kar:'B', phase:'L1'}, badge:'UK'},
     {label:'3-fase (3P+N)', type:'mcb_3p',  color:'#0e0e18', modules:3, dot:'#a855f7', specs:{amp:AMPS_MCB, kar:KAR_OPTS, phase:['3F']}, def:{amp:16, kar:'B'}},
   ], defaultSpecs:{amp:AMPS_MCB, kar:KAR_OPTS}
  },
  {group:'PV / Zonne-energie', dot:'#22c55e', badge:'PV',
   variants:[
     {label:'AC 1P+N', type:'pv_1pn', color:'#001808', modules:2, specs:{amp:[6,10,16,20], kar:['C','D'], phase:['L1','L2','L3']}, def:{amp:16, kar:'C', phase:'L1'}},
     {label:'AC 3F',   type:'pv_3p',  color:'#001808', modules:3, specs:{amp:[10,16,20,25], kar:['C','D'], phase:['3F']}, def:{amp:16, kar:'C'}},
   ], defaultSpecs:{amp:[6,10,16,20], kar:['C','D']}
  },
  {group:'Overig', dot:'#888', badge:null,
   variants:[
     {label:'Isolator', type:'isolator', color:'#181818', modules:2, specs:{amp:[16,25,32,40,63], poles:['2P','4P']}, def:{amp:40}},
     {label:'Blinde plaat', type:'blank', color:'#0d0d0d', modules:1, dot:'#222', specs:{}},
   ], defaultSpecs:{}
  },
];

// Helper: pak de actieve variant op basis van de huidige selectie
function _getVariant(grp, variantIdx) {
  return grp.variants[variantIdx] || grp.variants[0];
}

const CSS = `
:host { display: block; font-family: var(--primary-font-family, system-ui, sans-serif); }
* { box-sizing: border-box; margin: 0; padding: 0; }
.app { display: flex; background: #0c0c0c; border-radius: 10px; overflow: hidden; color: #e6edf3; min-height: 600px; height: calc(100vh - 120px); max-height: 1200px; }
/* Sidebar */
.sb { width: 200px; flex-shrink: 0; background: #111; border-right: 1px solid #1a1a1a; overflow-y: auto; display: flex; flex-direction: column; transition: width .2s, opacity .2s; }
.sb.hidden { width: 0; opacity: 0; pointer-events: none; overflow: hidden; border: none; }
.sb-toggle { font-size: 12px; padding: 2px 7px; border-radius: 4px; border: 1px solid #2a2a2a; background: #0d0d0d; color: #888; cursor: pointer; flex-shrink: 0; }
.sb-toggle:hover { border-color: #ef9f27; color: #ef9f27; }
.sb-hd { padding: 9px 10px; background: #0e0e0e; border-bottom: 1px solid #1a1a1a; flex-shrink: 0; }
.sb-hd-t { font-size: 11px; color: #ef9f27; font-weight: 600; }
.sb-hd-s { font-size: 9px; color: #444; margin-top: 2px; }
.sg-t { font-size: 11px; font-weight: 700; color: #3a3a3a; letter-spacing: .07em; text-transform: uppercase; padding: 8px 12px 5px; background: #0d0d0d; border-top: 1px solid #141414; border-bottom: 1px solid #141414; }
.si { padding: 5px 8px 6px; border-bottom: 1px solid #141414; }
.si-nm { font-size: 13px; font-weight: 500; color: #bbb; margin-bottom: 6px; display: flex; align-items: center; gap: 5px; }
.si-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.si-bdg { font-size: 7px; background: #0a1a0a; color: #22c55e; border: 1px solid #0d2a0d; padding: 1px 3px; border-radius: 2px; }
.sr { display: flex; align-items: center; gap: 4px; margin-bottom: 2px; }
.sl { font-size: 12px; color: #555; width: 68px; flex-shrink: 0; }
.ss { background: #0a0a0a; border: 1px solid #1e1e1e; border-radius: 3px; padding: 2px 4px; font-size: 12px; color: #ccc; outline: none; flex: 1; min-width: 0; cursor: pointer; }
.ss:focus { border-color: #ef9f27; }
.si-add { width: 100%; margin-top: 5px; padding: 3px 0; background: #1a1200; border: 1px solid #3a2800; border-radius: 3px; color: #ef9f27; font-size: 13px; cursor: pointer; text-align: center; }
.si-add:hover { background: #221800; }
/* Panel */
.pnl { flex: 1; padding: 12px; overflow: auto; display: flex; flex-direction: column; gap: 8px; }
.loading-overlay { position:absolute; top:0; left:0; right:0; bottom:0; background:rgba(8,8,8,0.85); display:flex; align-items:center; justify-content:center; z-index:50; border-radius:6px; }
.loading-spinner { width:28px; height:28px; border:3px solid #1a1a1a; border-top:3px solid #ef9f27; border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.ph { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ph-t { font-size: 13px; font-weight: 500; flex: 1; }
.ph-s { font-size: 9px; color: #444; margin-top: 1px; }
/* Kast */
.kast { background: #080808; border: 3px solid #222; border-radius: 6px; padding: 12px 14px 22px; position: relative; display: flex; flex-direction: column; gap: 8px; min-width: 200px; align-self: flex-start; width: fit-content; }
.kast-sc { position: absolute; width: 10px; height: 10px; border-radius: 50%; background: #0a0a0a; border: 1.5px solid #252525; }
/* Rail */
.rail { background: #0d0d0d; border: 1px solid #181818; border-radius: 3px; padding: 6px 8px 18px; display: flex; align-items: flex-end; gap: 0; position: relative; min-height: 175px; }
.din { position: absolute; left: 6px; right: 6px; height: 4px; background: #161616; border: 1px solid #111; border-radius: 1px; bottom: 14px; }
.rs { position: absolute; width: 7px; height: 7px; border-radius: 50%; background: #080808; border: 1.5px solid #1e1e1e; bottom: 4px; }
.rs-l { left: 6px; } .rs-r { right: 6px; }
/* Drop zones */
.dz { min-width: 8px; align-self: stretch; border-radius: 2px; flex-shrink: 0; transition: all .1s; }
.dz-over { background: rgba(239,159,39,.1) !important; outline: 1px dashed #ef9f27; }
/* Component */
.comp { position: relative; z-index: 2; cursor: grab; display: flex; flex-direction: column; align-items: center; gap: 0; user-select: none; }
.comp:active { cursor: grabbing; }
.comp-drag { opacity: .25; }
.comp svg { display: block; }
.comp-lbl { font-size: 12px; color: #555; text-align: center; line-height: 1.4; margin-top: 4px; max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.comp-lbl b { color: #777; font-size: 12px; font-weight: 500; display: block; }
.comp-lbl s { font-size: 11px; color: #333; font-style: normal; text-decoration: none; display: block; }
.lbtn { padding: 3px 6px; font-size: 12px; border: 1px solid #1e1e1e; background: #0a0a0a; color: #3a3a3a; border-radius: 3px; cursor: pointer; text-align: center; margin-top: 3px; white-space: nowrap; display: block; }
.lbtn:hover { border-color: #ef9f27; color: #ef9f27; }
.lbtn-ok { border-color: #0d2a0d !important; color: #22c55e !important; background: #060e06 !important; }
/* Add rail */
.add-rail { display: flex; align-items: center; justify-content: center; height: 26px; border: 1.5px dashed #1a1a1a; border-radius: 3px; color: #252525; font-size: 11px; cursor: pointer; transition: all .15s; align-self: flex-start; min-width: 200px; }
.add-rail:hover { border-color: #ef9f27; color: #ef9f27; }
/* Legend */
.leg { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
/* Zoom controls */
.zoom-bar { display: flex; align-items: center; gap: 6px; }
.zoom-btn { width: 26px; height: 26px; border-radius: 5px; border: 1px solid #2a2a2a; background: #0d0d0d; color: #888; font-size: 15px; cursor: pointer; display: flex; align-items: center; justify-content: center; line-height: 1; flex-shrink: 0; }
.zoom-btn:hover { border-color: #ef9f27; color: #ef9f27; }
.zoom-label { font-size: 10px; color: #555; min-width: 32px; text-align: center; }
.kast-wrap { overflow: auto; }
.li { display: flex; align-items: center; gap: 3px; font-size: 9px; color: #444; }
.ld { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
/* Schema panel */
.schema { width: 300px; flex-shrink: 0; background: #0a0a0a; border-left: 1px solid #1a1a1a; display: flex; flex-direction: column; overflow-y: auto; transition: width .2s, opacity .2s; }
.schema.hidden { width: 0; opacity: 0; pointer-events: none; overflow: hidden; border: none; }
.schema-toggle { font-size: 12px; padding: 2px 7px; border-radius: 4px; border: 1px solid #2a2a2a; background: #0d0d0d; color: #888; cursor: pointer; flex-shrink: 0; }
.schema-toggle:hover { border-color: #ef9f27; color: #ef9f27; }
.schema-hd { padding: 9px 10px; background: #0d0d0d; border-bottom: 1px solid #1a1a1a; flex-shrink: 0; display: flex; align-items: center; gap: 6px; }
.schema-hd-t { font-size: 11px; color: #ef9f27; font-weight: 600; flex: 1; }
.schema-hd-s { font-size: 9px; color: #444; }
.schema-body { padding: 10px 8px; flex: 1; overflow-y: auto; }
.schema-warn { background: #2a0a0a; border: 1px solid #5a1a1a; border-radius: 5px; padding: 6px 10px; font-size: 9px; color: #fca5a5; margin-bottom: 8px; }
/* Tree nodes */
.tree-node { margin-bottom: 2px; }
.tree-row { display: flex; align-items: center; gap: 5px; padding: 4px 5px; border-radius: 4px; cursor: pointer; transition: background .1s; position: relative; }
.tree-row:hover { background: #161616; }
.tree-icon { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; border: 1px solid; display: flex; align-items: center; justify-content: center; font-size: 8px; }
.tree-name { font-size: 10px; font-weight: 500; color: #aaa; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tree-phase { font-size: 8px; padding: 1px 4px; border-radius: 3px; flex-shrink: 0; font-weight: 600; }
.tree-load { width: 28px; height: 4px; background: #111; border-radius: 2px; overflow: hidden; flex-shrink: 0; }
.tree-load-fill { height: 100%; border-radius: 2px; }
.tree-warn { font-size: 9px; color: #ef4444; flex-shrink: 0; }
.tree-children { margin-left: 18px; border-left: 1px solid #1e1e1e; padding-left: 6px; }
/* Device rows */
.dev-row { display: flex; align-items: center; gap: 4px; padding: 2px 4px; border-radius: 3px; }
.dev-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.dev-name { font-size: 9px; color: #666; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dev-w { font-size: 9px; color: #555; flex-shrink: 0; }
.dev-on { color: #888 !important; }
.conflict-badge { font-size: 8px; background: #2a1010; color: #fca5a5; border: 1px solid #5a1a1a; border-radius: 3px; padding: 1px 4px; margin-left: auto; }
.assign-btn { font-size: 8px; color: #444; border: 1px solid #1e1e1e; background: #0a0a0a; border-radius: 3px; padding: 1px 4px; cursor: pointer; flex-shrink: 0; }
.assign-btn:hover { border-color: #ef9f27; color: #ef9f27; }

/* Modal */
.modal-bg { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,.75); display: flex; align-items: center; justify-content: center; z-index: 999; }
.modal { background: #161616; border: 1px solid #2a2a2a; border-radius: 10px; padding: 16px; width: 320px; max-width: 95vw; }
.modal-t { font-size: 13px; font-weight: 500; color: #ef9f27; margin-bottom: 12px; }
.mf { display: flex; flex-direction: column; gap: 3px; margin-bottom: 8px; }
.mf label { font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: .04em; }
.mf input, .mf select { background: #0d0d0d; border: 1px solid #2a2a2a; border-radius: 5px; padding: 6px 8px; font-size: 11px; color: #e6edf3; outline: none; width: 100%; }
.mf input:focus, .mf select:focus { border-color: #ef9f27; }
.m-acts { display: flex; gap: 6px; margin-top: 12px; }
.m-save { flex: 1; padding: 7px; background: #ef9f27; border: none; border-radius: 5px; color: #000; font-size: 11px; font-weight: 600; cursor: pointer; }
.m-del { padding: 7px 12px; background: #2a0a0a; border: 1px solid #5a1a1a; border-radius: 5px; color: #fca5a5; font-size: 11px; cursor: pointer; }
.m-can { padding: 7px 12px; background: #161616; border: 1px solid #2a2a2a; border-radius: 5px; color: #555; font-size: 11px; cursor: pointer; }
/* Wizard */
.wiz { background: #141000; border: 1px solid #4a3000; border-radius: 8px; padding: 12px; margin-top: 8px; }
.wiz-t { font-size: 12px; font-weight: 500; color: #fed7aa; margin-bottom: 8px; }
.wiz-step { font-size: 11px; color: #888; margin: 4px 0; display: flex; align-items: center; gap: 6px; }
.wiz-step-active { color: #fed7aa; }
.wiz-acts { display: flex; gap: 6px; margin-top: 10px; }
.wb-p { padding: 6px 14px; background: #ef9f27; border: none; border-radius: 5px; color: #000; font-size: 11px; font-weight: 600; cursor: pointer; }
.wb-s { padding: 6px 12px; background: #161616; border: 1px solid #2a2a2a; border-radius: 5px; color: #666; font-size: 11px; cursor: pointer; }
`;

class CloudEMSGroepenkastCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = {};
    this._rails = [[]];
    this._nc = 0;
    this._dragNode = null;
    this._dragRail = null;
    this._dragIdx  = null;
    this._wizard   = null;
    this._built    = false;
    this._zoom = null;   // null = auto-detectie nog niet gedaan
  }

  setConfig(config) {
    this._config = config || {};
  }

  getCardSize() { return 12; }

  static getConfigElement() {
    return document.createElement('cloudems-groepenkast-card-editor');
  }

  set hass(h) {
    this._hass = h;
    const attr = h?.states?.['sensor.cloudems_groepenkast']?.attributes;
    if (!this._built) { this._buildUI(); this._built = true; }
    // Herstel opgeslagen configuratie uit sensor bij eerste load
    if (attr && attr.nodes && attr.nodes.length > 0 && this._rails.flat().length === 0) {
      this._syncFromSensor(attr);
    }
  }

  _syncFromSensor(attr) {
    // Only sync if rails are empty (first load)
    if (this._rails.flat().length === 0 && attr.nodes && attr.nodes.length > 0) {
      // rails worden aangemaakt op basis van rail_index (zie hieronder)
      // Herstel rail-indeling: position = rail_index * 1000 + node_index
      // Bepaal max rail_index om juiste aantal rails aan te maken
      const sorted = [...attr.nodes].sort((a, b) => (a.position || 0) - (b.position || 0));
      const maxRail = sorted.reduce((mx, n) => {
        const ri = n.rail_index !== undefined ? n.rail_index : Math.floor((n.position || 0) / 1000);
        return Math.max(mx, ri);
      }, 0);
      // Maak de juiste rails aan
      this._rails = Array.from({length: maxRail + 1}, () => []);

      sorted.forEach(n => {
        // card_type is de exacte variant (main_4p, rcd_4p_b etc.)
        // node_type is de generieke backend type (main, rcd, mcb etc.)
        const typeMap = {
          'main': 'main_4p', 'rcd': 'rcd_4p_a', 'rcbo': 'rcbo_1pn',
          'mcb': 'mcb_1p', 'mcb_3f': 'mcb_3p',
        };
        const lookupType = n.card_type || typeMap[n.node_type] || n.node_type;
        const def = this._getDef(lookupType);
        if (!def) return;
        const node = this._makeNode(def, {
          amp:     n.ampere    || 16,
          phase:   n.phase     || 'L1',
          ma:      n.ma        || 30,
          kar:     n.kar       || 'B',
          rcdType: n.rcd_type  || 'A',
          poles:   def.specs?.poles || null,
        });
        node.id          = n.id;
        // Gebruik naam, anders eerste gekoppeld NILM-apparaat als suggestie
        const nilmSuggestion = (!n.name && n.linked_devices?.length > 0)
          ? (n.linked_devices[0] || '') : '';
        node.label       = n.name || '';
        node.nilmSuggest = nilmSuggestion;   // bewaar voor visuele hint
        node.brand       = n.notes || '';
        node.learned     = (n.confidence || 0) > 0;
        node.load        = n.load_pct || 0;
        node.parentRCDId  = n.parent_id || null;
        node.parentMainId = n.parent_main_id || null;
        // Voeg toe aan de juiste rail op basis van opgeslagen rail_index
        const targetRail = n.rail_index !== undefined
          ? n.rail_index
          : Math.floor((n.position || 0) / 1000);
        while (this._rails.length <= targetRail) this._rails.push([]);
        this._rails[targetRail].push(node);
      });
      this._renderKast();
    }
  }

  _getDef(type) {
    for (const g of COMP_DEFS) {
      for (const v of g.variants) {
        if (v.type === type) return { ...v, dot: v.dot || g.dot };
      }
    }
    return null;
  }

  _makeNode(def, specs) {
    this._nc++;
    return {
      id: 'n' + this._nc,
      defType: def.type,
      label: '',
      brand: '',
      phase: specs.phase || (def.specs.phase ? def.specs.phase[0] : '3F'),
      amp: specs.amp || (def.specs.amp ? def.specs.amp[Math.min(1, def.specs.amp.length - 1)] : 16),
      ma: specs.ma || (def.specs.ma ? def.specs.ma[0] : null),
      kar: specs.kar || (def.specs.kar ? def.specs.kar[0] : null),
      rcdType: specs.rcdType || def.specs.rcdType || null,
      poles: specs.poles || def.specs.poles || null,
      modules: def.modules,
      color: def.color,
      dot: def.dot,
      defLabel: def.label,
      learned: false,
      load: 0,
    };
  }

  _totMod(rail) { return rail.reduce((s, n) => s + n.modules, 0); }

  _addNode(node) {
    for (let i = 0; i < this._rails.length; i++) {
      if (this._totMod(this._rails[i]) + node.modules <= 18) {
        this._rails[i].push(node);
        return;
      }
    }
    this._rails.push([node]);
  }

  _buildUI() {
    const root = this.shadowRoot;
    root.innerHTML = '';
    const style = document.createElement('style');
    style.textContent = CSS;
    root.appendChild(style);

    const app = document.createElement('div');
    app.className = 'app';

    // Sidebar
    const sb = document.createElement('div');
    sb.className = 'sb';
    sb.id = 'sidebar-panel';
    const sbhd = document.createElement('div');
    sbhd.className = 'sb-hd';
    sbhd.innerHTML = '<div class="sb-hd-t">⚡ Componenten</div><div class="sb-hd-s">Klik toevoegen of sleep</div>';
    sb.appendChild(sbhd);
    const sbContent = document.createElement('div');
    sbContent.id = 'sb-content';
    this._buildSidebar(sbContent);
    sb.appendChild(sbContent);
    app.appendChild(sb);

    // Panel
    const pnl = document.createElement('div');
    pnl.className = 'pnl';

    const ph = document.createElement('div');
    ph.className = 'ph';
    const phLeft = document.createElement('div');
    const phT = document.createElement('div');
    phT.className = 'ph-t';
    phT.textContent = 'Groepenkast';
    const betaBadge = document.createElement('span');
    betaBadge.textContent = 'BETA';
    betaBadge.style.cssText = 'font-size:9px;background:#2a1800;color:#ef9f27;border:1px solid #ef9f2755;padding:2px 6px;border-radius:4px;font-weight:700;letter-spacing:.06em;margin-left:8px;vertical-align:middle;';
    phT.appendChild(betaBadge);
    const phS = document.createElement('div');
    phS.className = 'ph-s';
    phS.id = 'ph-s';
    phLeft.appendChild(phT);
    phLeft.appendChild(phS);
    ph.appendChild(phLeft);

    // Zoom controls
    const zoomBar = document.createElement('div');
    zoomBar.className = 'zoom-bar';
    const zoomOut = document.createElement('button');
    zoomOut.className = 'zoom-btn';
    zoomOut.textContent = '−';
    zoomOut.title = 'Zoom uit';
    zoomOut.onclick = () => { this._zoom = Math.max(0.5, (this._zoom || 1) - 0.1); this._applyZoom(); };
    const zoomLbl = document.createElement('span');
    zoomLbl.className = 'zoom-label';
    zoomLbl.id = 'zoom-lbl';
    const zoomIn = document.createElement('button');
    zoomIn.className = 'zoom-btn';
    zoomIn.textContent = '+';
    zoomIn.title = 'Zoom in';
    zoomIn.onclick = () => { this._zoom = Math.min(3.0, (this._zoom || 1) + 0.1); this._applyZoom(); };
    const zoomReset = document.createElement('button');
    zoomReset.className = 'zoom-btn';
    zoomReset.title = 'Automatisch formaat';
    zoomReset.textContent = '⊙';
    zoomReset.onclick = () => { this._zoom = null; this._autoZoom(); };
    const printBtn = document.createElement('button');
    printBtn.className = 'zoom-btn';
    printBtn.title = 'Schema afdrukken / opslaan als PDF';
    printBtn.innerHTML = '🖨';
    printBtn.onclick = () => this._printSchema();

    // Sidebar toggle knop
    const sbToggle = document.createElement('button');
    sbToggle.className = 'sb-toggle';
    sbToggle.id = 'sb-toggle-btn';
    sbToggle.title = 'Zijbalk tonen/verbergen';
    sbToggle.textContent = '☰';
    sbToggle.onclick = () => {
      const sp = this.shadowRoot.getElementById('sidebar-panel');
      if (!sp) return;
      const isHidden = sp.classList.toggle('hidden');
      sbToggle.style.color = isHidden ? '#444' : '';
      this._sidebarHidden = isHidden;
    };

    // Schema toggle knop — verbergt/toont schema paneel rechts
    const schemaToggle = document.createElement('button');
    schemaToggle.className = 'schema-toggle';
    schemaToggle.id = 'schema-toggle-btn';
    schemaToggle.title = 'Schema tonen/verbergen';
    schemaToggle.textContent = '📐';
    schemaToggle.onclick = () => {
      const sp = this.shadowRoot.getElementById('schema-panel');
      if (!sp) return;
      const isHidden = sp.classList.toggle('hidden');
      schemaToggle.style.color = isHidden ? '#444' : '';
      this._schemaHidden = isHidden;
    };

    zoomBar.appendChild(sbToggle);
    zoomBar.appendChild(zoomOut);
    zoomBar.appendChild(zoomLbl);
    zoomBar.appendChild(zoomIn);
    zoomBar.appendChild(zoomReset);
    zoomBar.appendChild(printBtn);
    zoomBar.appendChild(schemaToggle);

    // 📷 Foto-herkenning knop
    const photoBtn = document.createElement('button');
    photoBtn.className = 'schema-toggle';
    photoBtn.title = 'Foto van groepenkast analyseren via AI';
    photoBtn.textContent = '📷';
    photoBtn.onclick = () => this._openPhotoRecognition();
    zoomBar.appendChild(photoBtn);
    ph.appendChild(zoomBar);
    pnl.appendChild(ph);

    // Kast wrap voor transform-origin scaling
    const kastWrap = document.createElement('div');
    kastWrap.className = 'kast-wrap';
    kastWrap.id = 'kast-wrap';
    kastWrap.style.position = 'relative';

    // Loading indicator — zichtbaar totdat eerste render klaar is
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading-overlay';
    loadingDiv.id = 'loading-overlay';
    const spinner = document.createElement('div');
    spinner.className = 'loading-spinner';
    loadingDiv.appendChild(spinner);
    kastWrap.appendChild(loadingDiv);

    const kast = document.createElement('div');
    kast.className = 'kast';
    kast.id = 'kast';
    // Corner screws
    [['top:6px;left:6px'],['top:6px;right:6px'],['bottom:12px;left:6px'],['bottom:12px;right:6px']].forEach(s => {
      const sc = document.createElement('div');
      sc.className = 'kast-sc';
      sc.style.cssText = s[0];
      kast.appendChild(sc);
    });
    kastWrap.appendChild(kast);
    pnl.appendChild(kastWrap);

    const addRailBtn = document.createElement('div');
    addRailBtn.className = 'add-rail';
    addRailBtn.id = 'add-rail-btn';
    addRailBtn.textContent = '＋ Rail toevoegen';
    addRailBtn.onclick = () => { if (this._rails.length < 5) { this._rails.push([]); this._renderKast(); } };
    pnl.appendChild(addRailBtn);

    const leg = document.createElement('div');
    leg.className = 'leg';
    leg.id = 'legend';
    pnl.appendChild(leg);

    const wizDiv = document.createElement('div');
    wizDiv.id = 'wiz-area';
    pnl.appendChild(wizDiv);

    app.appendChild(pnl);
    // Schema paneel rechts
    const schema = document.createElement('div');
    schema.className = 'schema';
    schema.id = 'schema-panel';
    const schHd = document.createElement('div');
    schHd.className = 'schema-hd';
    const schT = document.createElement('div');
    schT.className = 'schema-hd-t';
    schT.textContent = '\u{1F4D0} Aansluitschema';
    // Toon norm naam en voltage/freq
    const normSpan = document.createElement('span');
    normSpan.id = 'schema-norm';
    normSpan.style.cssText = 'font-size:8px;color:#444;font-weight:normal;margin-left:8px;';
    const std = this._getStd();
    normSpan.textContent = std.name + ' · ' + std.voltage + 'V';
    schT.appendChild(normSpan);
    const normBadge = document.createElement('span');
    normBadge.id = 'schema-norm-badge';
    normBadge.style.cssText = 'font-size:9px;color:#555;margin-left:6px;font-weight:400;';
    const _n = this._getCountryNorm();
    normBadge.textContent = `${_n.flag} ${_n.norm}`;
    schT.appendChild(normBadge);
    const schS = document.createElement('div');
    schS.className = 'schema-hd-s';
    schS.textContent = 'config + geleerde data';
    schHd.appendChild(schT);
    schHd.appendChild(schS);
    schema.appendChild(schHd);
    const schBody = document.createElement('div');
    schBody.className = 'schema-body';
    schBody.id = 'schema-body';
    schema.appendChild(schBody);
    app.appendChild(schema);
    root.appendChild(app);

    // Modal root
    const mr = document.createElement('div');
    mr.id = 'modal-root';
    root.appendChild(mr);

    // Auto-hide sidebar + schema op small scherm (<750px breed)
    const _ro = new ResizeObserver(entries => {
      const w = entries[0]?.contentRect?.width || 9999;
      const schemaEl  = root.getElementById('schema-panel');
      const schemaTb  = root.getElementById('schema-toggle-btn');
      const sidebarEl = root.getElementById('sidebar-panel');
      const sidebarTb = root.getElementById('sb-toggle-btn');
      if (w < 750) {
        if (!this._schemaHidden) {
          schemaEl?.classList.add('hidden');
          if (schemaTb) schemaTb.style.color = '#444';
          this._schemaHidden = true;
        }
        if (!this._sidebarHidden) {
          sidebarEl?.classList.add('hidden');
          if (sidebarTb) sidebarTb.style.color = '#444';
          this._sidebarHidden = true;
        }
      } else if (w >= 750) {
        if (this._schemaHidden === undefined) {
          schemaEl?.classList.remove('hidden');
        }
        if (this._sidebarHidden === undefined) {
          sidebarEl?.classList.remove('hidden');
        }
      }
    });
    _ro.observe(this);

    this._renderKast();
    this._buildLegend();

    // Herbereken auto-zoom bij resize van het paneel
    if (typeof ResizeObserver !== 'undefined') {
      const pnlEl = pnl;
      new ResizeObserver(() => {
        if (this._zoom === null) this._autoZoom();
      }).observe(pnlEl);
    }
  }

  _autoZoom() {
    // Detecteer beschikbare breedte van het paneel en kies de grootste zoom
    // waarbij de kast nog past. Basis: 40px per module, componenten van 5 modules breed.
    const root = this.shadowRoot;
    if (!root) return;
    const kast = root.getElementById('kast');
    const wrap = root.getElementById('kast-wrap');
    const pnl  = wrap ? wrap.parentElement : null;
    if (!kast || !pnl) return;

    // Beschikbare breedte = pnl breedte min padding
    const availW = pnl.clientWidth - 32;
    const availH = window.innerHeight * 0.55; // max 55vh voor de kast

    // Bereken kastbreedte bij zoom=1
    const maxModules = Math.max(...this._rails.map(r => this._totMod(r)), 5);
    const kastW1 = maxModules * 40 + 60; // 40px/module + kast padding
    const kastH1 = this._rails.length * 175 + 60;

    const zoomW = availW > 0 && kastW1 > 0 ? availW / kastW1 : 1;
    const zoomH = availH > 0 && kastH1 > 0 ? availH / kastH1 : 1;
    this._zoom = Math.min(zoomW, zoomH, 2.5); // nooit groter dan 250%
    this._zoom = Math.max(this._zoom, 0.4);   // nooit kleiner dan 40%
    this._zoom = Math.round(this._zoom * 10) / 10; // snap naar 10%
    this._applyZoom();
  }

  _applyZoom() {
    const root = this.shadowRoot;
    if (!root) return;
    const kast = root.getElementById('kast');
    const wrap = root.getElementById('kast-wrap');
    const lbl  = root.getElementById('zoom-lbl');
    if (!kast || !wrap) return;
    const z = this._zoom || 1;
    kast.style.transform = `scale(${z})`;
    kast.style.transformOrigin = 'top left';
    // Pas wrap hoogte/breedte aan zodat er geen lege ruimte ontstaat
    const rect = kast.getBoundingClientRect();
    // Gebruik scrollWidth/Height voor de unscaled maten
    wrap.style.width  = Math.round(kast.scrollWidth  * z) + 'px';
    wrap.style.height = Math.round(kast.scrollHeight * z) + 'px';
    wrap.style.overflow = 'hidden';
    if (lbl) lbl.textContent = Math.round(z * 100) + '%';
  }

  _buildSidebar(container) {
    container.innerHTML = '';
    COMP_DEFS.forEach(g => {
      const gt = document.createElement('div');
      gt.className = 'sg-t';
      gt.textContent = g.group;
      container.appendChild(gt);

      const si = document.createElement('div');
      si.className = 'si';

      // Naam + badge rij
      const nm = document.createElement('div');
      nm.className = 'si-nm';
      const dot = document.createElement('span');
      dot.className = 'si-dot';
      const activeDot = () => {
        const v = _getVariant(g, parseInt(varSel.value));
        return v.dot || g.dot;
      };
      dot.style.cssText = 'background:' + g.dot + ';border:1px solid ' + g.dot;
      nm.appendChild(dot);
      const nt = document.createElement('span');
      nt.textContent = g.group;
      nm.appendChild(nt);
      if (g.badge) {
        const b = document.createElement('span');
        b.className = 'si-bdg';
        b.textContent = g.badge;
        nm.appendChild(b);
      }
      si.appendChild(nm);

      // Variant dropdown (alleen als er meer dan 1 variant is)
      const varRow = this._mkSR('Type', g.variants.map(v => v.label), g.variants.map((v,i) => i));
      const varSel = varRow.sel;
      si.appendChild(varRow.el);

      // Spec container — wordt opnieuw gebouwd als variant wisselt
      const specContainer = document.createElement('div');
      si.appendChild(specContainer);

      const sv = {};
      const rebuildSpecs = () => {
        specContainer.innerHTML = '';
        Object.keys(sv).forEach(k => delete sv[k]);
        const vi = parseInt(varSel.value);
        const v = _getVariant(g, vi);
        const sp = v.specs || {};
        const df = v.def || {};  // EMAT standaard defaults
        // Update dot kleur
        const d = v.dot || g.dot;
        dot.style.cssText = 'background:' + d + ';border:1px solid ' + d;
        // Update badge
        const existingBadge = nm.querySelector('.si-bdg');
        if (existingBadge) existingBadge.remove();
        const badge = v.badge || g.badge;
        if (badge) {
          const b = document.createElement('span');
          b.className = 'si-bdg';
          b.textContent = badge;
          nm.appendChild(b);
        }
        // Helper: maak select met pre-geselecteerde default waarde
        const mkSRDef = (label, labels, values, defVal) => {
          const r = this._mkSR(label, labels, values);
          if (defVal !== undefined) {
            const idx = values.indexOf(defVal);
            if (idx >= 0) r.sel.selectedIndex = idx;
          }
          return r;
        };
        if (sp.amp) { const r = mkSRDef('Ampère', sp.amp.map(a => a + 'A'), sp.amp, df.amp); sv.amp = r.sel; specContainer.appendChild(r.el); }
        if (sp.kar) { const r = mkSRDef('Kar.', sp.kar.map(k => k + '-kar'), sp.kar, df.kar); sv.kar = r.sel; specContainer.appendChild(r.el); }
        if (sp.ma)  { const r = mkSRDef('Gevoeligheid', sp.ma.map(m => m + 'mA'), sp.ma, df.ma); sv.ma = r.sel; specContainer.appendChild(r.el); }
        if (sp.phase && sp.phase.length > 1) { const r = mkSRDef('Fase', sp.phase, sp.phase, df.phase); sv.phase = r.sel; specContainer.appendChild(r.el); }
      };
      varSel.addEventListener('change', rebuildSpecs);
      rebuildSpecs();

      const btn = document.createElement('button');
      btn.className = 'si-add';
      btn.textContent = '＋ Toevoegen';
      btn.onclick = () => {
        const vi = parseInt(varSel.value);
        const v = _getVariant(g, vi);
        const node = this._makeNode(v, {
          amp:     sv.amp   ? parseInt(sv.amp.value)   : null,
          kar:     sv.kar   ? sv.kar.value              : null,
          ma:      sv.ma    ? parseInt(sv.ma.value)     : null,
          phase:   sv.phase ? sv.phase.value            : null,
          rcdType: v.specs?.rcdType || null,
          poles:   v.specs?.poles   || null,
        });
        this._addNode(node);
        this._registerNodeInBackend(node);
        this._savePanelToHA();
        this._renderKast();
      };
      si.appendChild(btn);
      container.appendChild(si);
    });
  }

  _mkSR(label, labels, values) {
    const row = document.createElement('div');
    row.className = 'sr';
    const lbl = document.createElement('span');
    lbl.className = 'sl';
    lbl.textContent = label;
    row.appendChild(lbl);
    const sel = document.createElement('select');
    sel.className = 'ss';
    labels.forEach((l, i) => {
      const opt = document.createElement('option');
      opt.value = values[i];
      opt.textContent = l;
      sel.appendChild(opt);
    });
    row.appendChild(sel);
    return { el: row, sel };
  }

  _renderKast() {
    const root = this.shadowRoot;
    if (!root) return;
    // Verberg loading indicator direct — ook bij errors daarna
    const _lo = root.getElementById('loading-overlay');
    if (_lo) _lo.style.display = 'none';
    const kast = root.getElementById('kast');
    if (!kast) return;

    while (kast.children.length > 4) kast.removeChild(kast.lastChild);

    let tot = 0;
    this._rails.forEach((rail, ri) => {
      tot += rail.length;
      const re = document.createElement('div');
      re.className = 'rail';
      const w = Math.max(this._totMod(rail), 5) * 40 + 28;
      re.style.width = w + 'px';

      const din = document.createElement('div'); din.className = 'din'; re.appendChild(din);
      const rs1 = document.createElement('div'); rs1.className = 'rs rs-l'; re.appendChild(rs1);
      const rs2 = document.createElement('div'); rs2.className = 'rs rs-r'; re.appendChild(rs2);

      if (rail.length === 0) {
        // Lege rail: één grote dropzone zodat je er makkelijk op kunt droppen
        const emptyDZ = this._mkDZ(ri, 0);
        emptyDZ.style.cssText = 'flex:1;display:flex;align-items:center;justify-content:center;border:1.5px dashed #252525;border-radius:4px;color:#2a2a2a;font-size:10px;cursor:default;margin:4px;';
        emptyDZ.textContent = 'Sleep hier';
        re.appendChild(emptyDZ);
      } else {
        re.appendChild(this._mkDZ(ri, 0));
        rail.forEach((node, ni) => {
          re.appendChild(this._mkCompEl(node, ri, ni));
          re.appendChild(this._mkDZ(ri, ni + 1));
        });
        // Opvulling rechts: vult lege ruimte en is ook een dropzone
        const filler = this._mkDZ(ri, rail.length);
        filler.style.flex = '1';
        re.appendChild(filler);
      }
      kast.appendChild(re);
    });

    const arb = root.getElementById('add-rail-btn');
    if (arb) arb.style.display = this._rails.length < 5 ? 'flex' : 'none';
    // ── Fase-belasting indicator ─────────────────────────────────────────────
    // Bereken totaal per fase op basis van amp-waarden
    let existingFaseBar = root.getElementById('fase-bar');
    if (existingFaseBar) existingFaseBar.remove();

    const phTotals = {L1:0, L2:0, L3:0};
    const allNodesList = this._rails.flat();
    allNodesList.forEach(n => {
      if (n.defType.startsWith('main') || n.defType === 'blank' || n.defType === 'isolator') return;
      const ph = (() => {
        if (n.defType.startsWith('rcd') || n.defType.startsWith('rcbo')) return n.phase;
        // MCB: eigen fase of via parent
        if (n.parentRCDId) {
          const par = allNodesList.find(x => x.id === n.parentRCDId);
          if (par && (par.defType.includes('2p') || par.defType.includes('1pn'))) return par.phase;
        }
        return n.phase;
      })();
      if (ph && phTotals[ph] !== undefined) phTotals[ph] += (n.amp || 0);
    });

    const maxAmp = Math.max(...Object.values(phTotals), 1);
    const PC2 = {L1:'#f97316', L2:'#3b82f6', L3:'#22c55e'};
    const faseBar = document.createElement('div');
    faseBar.id = 'fase-bar';
    faseBar.style.cssText = 'padding:6px 10px 4px;border-top:1px solid #1a1a1a;display:flex;gap:8px;align-items:center;flex-shrink:0;';
    ['L1','L2','L3'].forEach(ph => {
      const amp = phTotals[ph];
      if (amp === 0) return;
      const pct = Math.min(100, (amp / 63) * 100); // 63A = typisch max
      const over = amp > 40;
      const wrap = document.createElement('div');
      wrap.style.cssText = 'display:flex;align-items:center;gap:4px;flex:1;min-width:0;';
      const lbl = document.createElement('span');
      lbl.style.cssText = `font-size:9px;color:${PC2[ph]};font-weight:600;width:16px;flex-shrink:0;`;
      lbl.textContent = ph;
      const bar = document.createElement('div');
      bar.style.cssText = 'flex:1;height:6px;background:#1a1a1a;border-radius:3px;overflow:hidden;';
      const fill = document.createElement('div');
      fill.style.cssText = `height:100%;width:${pct}%;background:${over?'#ef4444':PC2[ph]};border-radius:3px;transition:width .3s;`;
      const val = document.createElement('span');
      val.style.cssText = `font-size:9px;color:${over?'#ef4444':'#444'};width:30px;text-align:right;flex-shrink:0;`;
      val.textContent = amp + 'A';
      bar.appendChild(fill);
      wrap.appendChild(lbl); wrap.appendChild(bar); wrap.appendChild(val);
      faseBar.appendChild(wrap);
    });
    if (Object.values(phTotals).some(v => v > 0)) {
      const kw = root.getElementById('kast-wrap');
      if (kw) kw.appendChild(faseBar);
    }

    // Lege kast hint
    const emptyHint = root.getElementById('kast-empty-hint');
    if (tot === 0) {
      if (!emptyHint) {
        const hint = document.createElement('div');
        hint.id = 'kast-empty-hint';
        hint.style.cssText = 'padding:24px 16px;text-align:center;color:#2a2a2a;font-size:11px;line-height:1.6;pointer-events:none;';
        hint.innerHTML = '<div style="font-size:22px;margin-bottom:8px;">⚡</div>' +
          '<div style="color:#333;font-weight:500;margin-bottom:4px;">Kast is leeg</div>' +
          '<div style="color:#2a2a2a;">Kies een component in de zijbalk<br>en klik <span style="color:#ef9f27">＋ Toevoegen</span></div>';
        kast.appendChild(hint);
      }
    } else if (emptyHint) {
      emptyHint.remove();
    }

    const phs = root.getElementById('ph-s');
    if (phs) phs.textContent = tot + ' componenten · ' + this._rails.length + ' rail' + (this._rails.length !== 1 ? 's' : '');
    this._renderSchema();


    // Auto-zoom: bij eerste render of na structuurwijziging als zoom op auto staat
    requestAnimationFrame(() => {
      if (this._zoom === null) {
        this._autoZoom();
      } else {
        this._applyZoom();
      }
    });
  }

  _mkDZ(ri, idx) {
    const dz = document.createElement('div');
    dz.className = 'dz';
    dz.dataset.ri = ri;
    dz.dataset.idx = idx;
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dz-over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('dz-over'));
    dz.addEventListener('drop', e => {
      e.preventDefault();
      dz.classList.remove('dz-over');
      if (this._dragNode === null) return;
      const fr = this._rails[this._dragRail];
      const node = fr[this._dragIdx];
      fr.splice(this._dragIdx, 1);
      if (fr.length === 0 && this._rails.length > 1) this._rails.splice(this._dragRail, 1);
      let toRi = parseInt(dz.dataset.ri);
      let toIdx = parseInt(dz.dataset.idx);
      if (toRi >= this._rails.length) this._rails.push([]);
      if (toRi === this._dragRail && toIdx > this._dragIdx) toIdx--;
      this._rails[toRi].splice(toIdx, 0, node);
      this._dragNode = this._dragRail = this._dragIdx = null;
      this._savePanelToHA();
      this._renderKast();
    });
    return dz;
  }

  _mkCompEl(node, ri, ni) {
    const isMCB   = this._isMCBType(node.defType);
    const gnMap   = this._buildGroupNumberMap();
    const groupNum = gnMap[node.id] || 0;

    const wrap = document.createElement('div');
    wrap.className = 'comp';
    wrap.draggable = true;
    let _wasDragged = false;
    wrap.addEventListener('dragstart', () => {
      _wasDragged = true;
      this._dragNode = node;
      this._dragRail = ri;
      this._dragIdx = ni;
      setTimeout(() => wrap.classList.add('comp-drag'), 0);
    });
    wrap.addEventListener('dragend', () => {
      wrap.classList.remove('comp-drag');
      if (this._dragNode) this._dragNode = this._dragRail = this._dragIdx = null;
      setTimeout(() => { _wasDragged = false; }, 50);
    });
    // Click op de wrap (niet via drag) → open edit modal
    wrap.addEventListener('click', e => {
      if (_wasDragged) return;
      e.stopPropagation();
      this._openEdit(node);
    });

    const W = node.modules * 40;
    const H = 140;
    const svg = this._drawComp(node, W, H);
    svg.style.cursor = 'pointer';
    // Groepnummer badge op automaten
    if (isMCB && groupNum > 0) {
      const nb = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      nb.setAttribute('x', (W/2).toFixed(0));
      nb.setAttribute('y', '10');
      nb.setAttribute('text-anchor', 'middle');
      nb.setAttribute('font-size', '9');
      nb.setAttribute('font-weight', '700');
      nb.setAttribute('fill', 'rgba(255,255,255,0.45)');
      nb.setAttribute('font-family', 'system-ui');
      nb.textContent = groupNum;
      svg.appendChild(nb);
    }

    // Click afgehandeld door wrap hierboven
    wrap.appendChild(svg);

    const lbl = document.createElement('div');
    lbl.className = 'comp-lbl';
    const b = document.createElement('b');
    const displayLabel = node.label || '';
    const suggestion = (!displayLabel && node.nilmSuggest) ? node.nilmSuggest : '';
    b.textContent = (isMCB && groupNum > 0 ? groupNum + ' · ' : '') + (displayLabel || node.defLabel);
    if (suggestion) {
      b.title = '💡 CloudEMS herkend: ' + suggestion;
      b.style.fontStyle = 'italic';
      b.style.color = '#ef9f2777';
    }
    lbl.appendChild(b);
    if (node.brand && node.brand !== '(geen)') {
      const s = document.createElement('span');
      s.textContent = node.brand;
      s.style.cssText = 'display:block;font-size:8px;color:#555;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      lbl.appendChild(s);
    }
    lbl.style.width = W + 'px';
    wrap.appendChild(lbl);

    const lb = document.createElement('button');
    lb.className = 'lbtn' + (node.learned ? ' lbtn-ok' : '');
    lb.textContent = node.learned ? '✓ geleerd' : 'Leer';
    lb.style.width = W + 'px';
    lb.style.fontSize = '8px';
    lb.addEventListener('click', e => { e.stopPropagation(); this._openWizard(node); });
    wrap.appendChild(lb);

    return wrap;
  }

  _sv(tag) { return document.createElementNS('http://www.w3.org/2000/svg', tag); }
  _sa(el, a) { Object.entries(a).forEach(([k, v]) => el.setAttribute(k, v)); return el; }

  _drawComp(node, W, H) {
    const svg = this._sv('svg');
    this._sa(svg, { width: W, height: H });
    svg.style.overflow = 'visible';

    const isRCD  = node.defType.startsWith('rcd');
    const isRCBO = node.defType.startsWith('rcbo');
    const isPV   = node.defType.startsWith('pv');
    const isMain = node.defType.startsWith('main');
    const isBL   = node.defType === 'blank';
    const isISO  = node.defType === 'isolator';

    // Body
    this._sa(this._sv('rect'), { x:0, y:0, width:W, height:H, fill:node.color, stroke:node.dot+'55', 'stroke-width':'1', rx:'3' });
    svg.appendChild(svg.lastChild || this._sa(this._sv('rect'), { x:0, y:0, width:W, height:H, fill:node.color, stroke:node.dot+'55', 'stroke-width':'1', rx:'3' }));

    // Helper shortcuts
    const R = (x,y,w,h,f,s,rx) => { const e=this._sv('rect'); this._sa(e,{x,y,width:w,height:h,fill:f||'none',stroke:s||'none','stroke-width':'1',rx:rx||'0'}); svg.appendChild(e); return e; };
    const C = (cx,cy,r,f,s) => { const e=this._sv('circle'); this._sa(e,{cx,cy,r,fill:f||'none',stroke:s||'none','stroke-width':'1.5'}); svg.appendChild(e); return e; };
    const T = (x,y,t,sz,f) => { const e=this._sv('text'); this._sa(e,{x,y,'text-anchor':'middle','font-size':sz,fill:f,'font-family':'system-ui'}); e.textContent=t; svg.appendChild(e); return e; };
    const L = (x1,y1,x2,y2,s) => { const e=this._sv('line'); this._sa(e,{x1,y1,x2,y2,stroke:s,'stroke-width':'1'}); svg.appendChild(e); return e; };

    // Draw body first
    R(0,0,W,H,node.color,node.dot+'55',3);

    if (isBL) {
      L(4,H/2,W-4,H/2,'#1a1a1a');
    } else if (isMain) {
      R(W/2-11,8,22,44,'#1e1e2e','#3a3a5a',3);
      R(W/2-7,10,14,20,'#22c55e','none',2);
      R(W/2-7,32,14,14,'#0a0a1a','none',2);
      T(W/2,62,'ON','11px','#22c55e');
      T(W/2,73,node.amp+'A','12px','#ccc');
      T(W/2,82,node.poles||'4P','11px','#444');
    } else if (isRCD || isRCBO) {
      const bBase = node.rcdType === 'B' ? '#ef4444' : '#f97316';
      const PC2 = {'L1':'#f97316','L2':'#3b82f6','L3':'#22c55e'};
      // Fase-fix: gebruik node.phase, fallback op parentMainId fase
      let _rcdPhase = node.phase;
      if (!_rcdPhase && node.parentMainId) {
        const _pm = this._rails.flat().find(n => n.id === node.parentMainId);
        if (_pm && _pm.phase) _rcdPhase = _pm.phase;
      }
      const bc = (_rcdPhase && PC2[_rcdPhase]) ? PC2[_rcdPhase] : bBase;
      R(W/2-9,8,18,32,'#111',bc+'55',3);
      R(W/2-6,10,12,14,bc,'none',2);
      R(W/2-6,26,12,10,'#0a0a0a','none',2);
      C(W/2,50,6,'#111',bc);
      T(W/2,54,'T','11px','#777');
      T(W/2,66,(node.ma||30)+'mA','11px',bc);
      T(W/2,76,node.amp+'A','11px','#999');
      if (node.phase && PC2[node.phase]) T(W-4,10,node.phase,'9px',bc);
      if (node.rcdType === 'B') { R(2,2,20,9,'#3a0a0a','none',2); T(12,9,'TYPE B','11px','#ef4444'); }
      if (isRCBO && node.kar) T(W/2,84,node.kar+'-kar','11px','#555');
    } else if (isPV) {
      const gc = node.defType === 'pv_dc2p' ? '#4ade80' : '#22c55e';
      R(W/2-8,8,16,30,'#001808',gc+'44',3);
      R(W/2-5,10,10,13,gc,'none',2);
      R(W/2-5,25,10,10,'#001008','none',2);
      C(W/2,50,6,'#001808',gc);
      T(W/2,54,'☀','11px',gc);
      if (node.defType === 'pv_dc2p') T(W/2,67,'DC','11px','#4ade80');
      T(W/2,74,node.amp+'A','11px','#999');
      if (node.kar) T(W/2,83,node.kar+'-kar','11px','#555');
    } else if (isISO) {
      R(W/2-10,10,20,36,'#141414','#3a3a3a',3);
      R(W/2-6,14,12,14,'#888','none',2);
      T(W/2,60,node.amp+'A','11px','#888');
      T(W/2,70,'ISO','11px','#555');
    } else if (node.defType === 'mcb_2p') {
      // 2P MCB (FR/DE): twee bredere strepen — fase én nul beveiligd
      const _par2p = node.parentRCDId ? this._rails.flat().find(n => n.id === node.parentRCDId) : null;
      const _ph2 = (_par2p && (_par2p.defType.includes('2p')||_par2p.defType.includes('1pn')))
        ? (_par2p.phase || node.phase) : node.phase;
      const _pc2 = PC[_ph2] || '#60a5fa';
      R(W/2-10,6,20,36,'#0a0a18',_pc2+'44',3);
      R(W/2-8,8,8,14,_pc2,'none',2);
      R(W/2+1,8,6,14,'#4a5568','none',2);
      C(W-5,5,3,_pc2,'none'); C(W-5,13,2,'#4a5568','none');
      T(W/2,56,node.amp+'A','11px','#888');
      T(W/2,66,'2P','11px','#555');
    } else if (node.defType === 'mcb_1p_uk') {
      // UK 1P MCB: slanker, grijsblauwe kleur — alleen fase beveiligd
      const _phuk = node.phase || 'L1';
      const _pcuk = '#94a3b8';
      R(W/2-6,6,12,36,'#0a0a12',_pcuk+'44',3);
      R(W/2-3,8,6,14,_pcuk,'none',2);
      C(W-5,5,2.5,_pcuk,'none');
      T(W/2,56,node.amp+'A','11px','#888');
      T(W/2,66,node.kar+'-kar','11px','#555');
    } else {
      // MCB: bij 2P aardlek altijd de fase van het aardlek gebruiken
      let effPhase = node.phase;
      if (node.parentRCDId) {
        const par = this._rails.flat().find(n => n.id === node.parentRCDId);
        if (par && par.phase && (par.defType.includes('2p') || par.defType.includes('1pn'))) {
          effPhase = par.phase; // 2P aardlek bepaalt de fase
        } else if (par && par.phase && !effPhase) {
          effPhase = par.phase; // fallback als eigen fase leeg
        }
      }
      const pc = PC[effPhase] || '#3b82f6';
      const lc = node.load > .8 ? '#ef4444' : node.load > .6 ? '#eab308' : '#22c55e';
      // Phase dot top-right
      C(W-5,5,3,pc,'none');
      // Toggle
      R(W/2-7,7,14,34,'#0a0a18',pc+'33',3);
      R(W/2-4,9,8,15,pc+'cc','none',2);
      R(W/2-4,26,8,12,'#050508','none',2);
      // Load indicator
      R(W/2-4,47,8,5,'#050505',lc+'77',1);
      // Ampere + kar
      T(W/2,61,node.amp+'A','11px','#888');
      if (node.kar) T(W/2,70,node.kar+'-kar','11px','#555');
    }

    // Clamps top + bottom
    R(3,2,W-6,7,'#080808','#1e1e1e',1);
    R(3,H-9,W-6,7,'#080808','#1e1e1e',1);

    // Brand
    if (node.brand) T(W/2,H-1,node.brand,'11px','#2a2a2a');

    return svg;
  }

  _openPhotoRecognition() {
    const root = this.shadowRoot;
    const mr = root.getElementById('modal-root');
    if (!mr) return;
    mr.innerHTML = '';

    const bg = document.createElement('div'); bg.className = 'modal-bg';
    const modal = document.createElement('div'); modal.className = 'modal';
    modal.style.cssText = 'max-width:480px;width:90%';

    modal.innerHTML = `
      <div class="mh"><span style="font-size:18px">📷</span> Groepenkast herkennen</div>
      <div style="padding:16px;color:#888;font-size:12px;line-height:1.6">
        Maak een foto van je meterkast en CloudEMS herkent de componenten
        automatisch via AI (Claude Vision).
      </div>
      <div style="padding:0 16px 16px">
        <input type="file" id="photo-input" accept="image/*" capture="environment"
          style="display:none">
        <label for="photo-input" style="
          display:block;border:2px dashed #333;border-radius:8px;
          padding:24px;text-align:center;cursor:pointer;color:#555;
          font-size:13px;transition:border-color .2s">
          <div style="font-size:32px;margin-bottom:8px">📸</div>
          Tik om foto te maken of te kiezen
        </label>
        <img id="photo-preview" style="display:none;width:100%;border-radius:8px;margin-top:12px;max-height:200px;object-fit:cover">
        <div id="photo-result" style="margin-top:12px;font-size:11px;color:#888;line-height:1.6"></div>
        <div style="display:flex;gap:8px;margin-top:14px">
          <button id="photo-analyze" class="bsv" style="flex:1;opacity:.4;pointer-events:none">
            🔍 Analyseer
          </button>
          <button onclick="this.closest('.modal-bg').remove()" class="bca">Annuleer</button>
        </div>
      </div>
    `;

    bg.appendChild(modal);
    mr.appendChild(bg);
    bg.addEventListener('click', e => { if (e.target === bg) mr.innerHTML = ''; });

    // File input handler
    const input   = modal.querySelector('#photo-input');
    const preview = modal.querySelector('#photo-preview');
    const result  = modal.querySelector('#photo-result');
    const analyzeBtn = modal.querySelector('#photo-analyze');
    let _b64 = null, _mime = null;

    input.addEventListener('change', async e => {
      const file = e.target.files[0];
      if (!file) return;
      _mime = file.type || 'image/jpeg';
      const reader = new FileReader();
      reader.onload = ev => {
        const dataUrl = ev.target.result;
        _b64 = dataUrl.split(',')[1];
        preview.src = dataUrl;
        preview.style.display = 'block';
        analyzeBtn.style.opacity = '1';
        analyzeBtn.style.pointerEvents = 'auto';
      };
      reader.readAsDataURL(file);
    });

    analyzeBtn.addEventListener('click', async () => {
      if (!_b64) return;
      result.style.color = '#888';
      result.textContent = '⏳ Analyseren... (10-30 seconden)';
      analyzeBtn.disabled = true;

      try {
        const resp = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            model: 'claude-opus-4-5',
            max_tokens: 1500,
            messages: [{
              role: 'user',
              content: [
                {
                  type: 'image',
                  source: { type: 'base64', media_type: _mime, data: _b64 }
                },
                {
                  type: 'text',
                  text: 'Analyseer deze meterkast foto. Geef een JSON array terug met de componenten die je ziet. ' +
                    'Elk component heeft: type (main/rcd/mcb/rcbo/blank), ampere (getal), kar (B/C/D of null), ' +
                    'ma (30/300/500 of null voor aardlekken), poles (1/2/3/4), label (wat het waarschijnlijk is). ' +
                    'Antwoord ALLEEN met de JSON array, geen uitleg.'
                }
              ]
            }]
          })
        });

        if (!resp.ok) throw new Error('API fout: ' + resp.status);
        const data = await resp.json();
        const text = data.content?.[0]?.text || '';

        let components;
        try {
          const jsonMatch = text.match(/\[.*\]/s);
          components = jsonMatch ? JSON.parse(jsonMatch[0]) : null;
        } catch { components = null; }

        if (components && components.length > 0) {
          result.style.color = '#22c55e';
          result.innerHTML = '✅ ' + components.length + ' componenten herkend:<br>' +
            components.map(function(comp) {
              return '• ' + comp.type + ' ' + (comp.ampere||'') + 'A ' + (comp.kar||'') + ' ' + (comp.label||'');
            }).join('<br>');

          // Optie: automatisch toevoegen
          const addBtn = document.createElement('button');
          addBtn.className = 'bsv';
          addBtn.style.cssText = 'width:100%;margin-top:10px';
          addBtn.textContent = '+ Voeg herkende componenten toe';
          addBtn.onclick = () => {
            components.forEach(comp => {
              const defMap = {
                main: 'main_4p', rcd: 'rcd_2p_a', mcb: 'mcb_1p',
                rcbo: 'rcbo_1p', blank: 'blank'
              };
              const defType = defMap[comp.type] || 'mcb_1p';
              const def = this._getDef(defType);
              if (!def) return;
              const node = {
                id:       'photo_' + Date.now() + '_' + Math.random().toString(36).slice(2,6),
                defType, defLabel: def.label,
                amp: comp.ampere || 16, kar: comp.kar || 'B',
                ma: comp.ma || 30, phase: null,
                label: comp.label || '', brand: '', load: 0,
                color: def.color || '#0a0a18', dot: def.dot || '#333',
                modules: def.modules || 1, poles: comp.poles || 1,
                parentRCDId: null, parentMainId: null,
              };
              this._addNode(node);
              this._registerNodeInBackend(node);
            });
            this._renderKast();
            this._savePanelToHA();
            mr.innerHTML = '';
          };
          result.appendChild(addBtn);
        } else {
          result.style.color = '#f97316';
          result.textContent = '⚠ Geen componenten herkend. Probeer een duidelijkere foto.';
        }
      } catch (err) {
        result.style.color = '#ef4444';
        result.textContent = '❌ Fout: ' + err.message;
      }
      analyzeBtn.disabled = false;
    });
  }

  _openEdit(node) {
    const mr = this.shadowRoot.getElementById('modal-root');
    mr.innerHTML = '';
    const bg = document.createElement('div');
    bg.className = 'modal-bg';
    bg.addEventListener('click', e => { if (e.target === bg) mr.innerHTML = ''; });
    const modal = document.createElement('div');
    modal.className = 'modal';

    const title = document.createElement('div');
    title.className = 'modal-t';
    title.innerHTML = '<span style="color:#ef9f27">✏️</span>  ' + (node.label || node.defLabel);
    modal.appendChild(title);

    // ── Verzamel parent-opties EERST (nodig voor fase-lock logica) ───────────
    const allNodes    = this._rails.flat();
    const rcdNodes    = allNodes.filter(n =>
      n.id !== node.id && (n.defType.startsWith('rcd') || n.defType.startsWith('rcbo')));
    const mainNodes   = allNodes.filter(n =>
      n.id !== node.id && n.defType.startsWith('main'));

    const isEditMCB  = this._isMCBType(node.defType);
    const isEditRCD  = node.defType.startsWith('rcd');
    const isEditRCBO = node.defType.startsWith('rcbo');

    const parentRCD  = rcdNodes.find(n => n.id === node.parentRCDId) || null;
    const parentIs2P = parentRCD &&
      (parentRCD.defType.includes('2p') || parentRCD.defType.includes('1pn'));

    // ── Zoek def ─────────────────────────────────────────────────────────────
    const def = this._getDef(node.defType);

    // ── Label ────────────────────────────────────────────────────────────────
    const nilmSug = node.nilmSuggest || '';
    const lblPh   = nilmSug ? `💡 ${nilmSug} (CloudEMS suggestie)` : 'bijv. Keuken verlichting';
    const fLbl    = this._mkF('Label / naam', 'text', node.label || (nilmSug||''), lblPh);
    modal.appendChild(fLbl.wrap);

    // ── Merk ─────────────────────────────────────────────────────────────────
    const fBrnd = this._mkSF('Merk', BRANDS, node.brand || '(geen)');
    modal.appendChild(fBrnd.wrap);

    // ── Ampère ───────────────────────────────────────────────────────────────
    let fAmp = null;
    if (def && def.specs.amp) {
      fAmp = this._mkSF('Ampère', def.specs.amp.map(a => a + 'A'), (node.amp || 16) + 'A');
      modal.appendChild(fAmp.wrap);
    }

    // ── Hoofdschakelaar keuze — voor RCDs en RCBOs ───────────────────────────
    // Hoofdschakelaar keuze — voor RCDs en RCBOs, altijd tonen
    let fMain = null;
    if (isEditRCD || isEditRCBO) {
      const mainOpts   = ['(geen / rechtstreeks op net)', ...mainNodes.map(n => n.label || n.defLabel)];
      const curMain    = mainNodes.find(n => n.id === node.parentMainId);
      const curMainLbl = curMain ? (curMain.label || curMain.defLabel) : '(geen / rechtstreeks op net)';
      fMain = this._mkSF('Achter hoofdschakelaar', mainOpts, curMainLbl);
      modal.appendChild(fMain.wrap);
    }

    // ── Fase ──────────────────────────────────────────────────────────────────
    let fPh = null, fRCDPhase = null;

    if (isEditRCD && (node.defType.includes('2p') || node.defType.includes('1pn'))) {
      // 2P aardlek: fase kiezen
      fRCDPhase = this._mkSF('Fase', ['L1','L2','L3'], node.phase || 'L1');
      modal.appendChild(fRCDPhase.wrap);
    } else if (isEditRCBO) {
      // RCBO: eigen fasekeuze
      if (def && def.specs.phase && def.specs.phase.length > 1) {
        fPh = this._mkSF('Fase', def.specs.phase, node.phase);
        modal.appendChild(fPh.wrap);
      }
    } else if (isEditMCB && def && def.specs.phase && def.specs.phase.length > 1) {
      if (parentIs2P) {
        // Fase locked aan aardlek — toon readonly
        const lockedPhase = parentRCD.phase || node.phase || 'L1';
        node.phase = lockedPhase;
        const wrapF = document.createElement('div'); wrapF.className = 'm-field';
        const lblF  = document.createElement('label'); lblF.textContent = 'FASE'; lblF.className = 'm-lbl';
        const valF  = document.createElement('div');
        valF.style.cssText = 'padding:7px 10px;border:1px solid #1a1a1a;border-radius:5px;font-size:11px;background:#0d0d0d;cursor:not-allowed;';
        const PCP = {L1:'#f97316',L2:'#3b82f6',L3:'#22c55e','3F':'#a855f7'};
        valF.style.color = PCP[lockedPhase] || '#ef9f27';
        valF.innerHTML = `${lockedPhase} <span style="color:#444;font-size:10px">(bepaald door aardlek)</span>`;
        wrapF.appendChild(lblF); wrapF.appendChild(valF);
        modal.appendChild(wrapF);
      } else {
        fPh = this._mkSF('Fase', def.specs.phase, node.phase);
        modal.appendChild(fPh.wrap);
      }
    }

    // ── Aardlek koppeling — alleen voor MCBs ──────────────────────────────────
    let fRCD = null;
    if (isEditMCB && rcdNodes.length > 0) {
      const rcdOpts    = ['(geen / direct op hoofd)', ...rcdNodes.map(n => n.label || n.defLabel)];
      const curParent  = parentRCD ? (parentRCD.label || parentRCD.defLabel) : '(geen / direct op hoofd)';
      fRCD = this._mkSF('Aardlek', rcdOpts, curParent);
      const learnDiv = document.createElement('div');
      learnDiv.style.cssText = 'font-size:9px;color:#555;margin-top:-4px;margin-bottom:8px;padding:0 2px;';
      learnDiv.textContent = 'CloudEMS leert dit automatisch via fase-meting';
      fRCD.wrap.appendChild(learnDiv);
      modal.appendChild(fRCD.wrap);
    }

    // ── Karakteristiek ────────────────────────────────────────────────────────
    let fKar = null;
    if (def && def.specs.kar) {
      fKar = this._mkSF('Karakteristiek', def.specs.kar.map(k => k + '-kar'), (node.kar || 'B') + '-kar');
      modal.appendChild(fKar.wrap);
    }

    // ── Gevoeligheid (mA) ─────────────────────────────────────────────────────
    let fMa = null;
    if (def && def.specs.ma) {
      fMa = this._mkSF('Gevoeligheid', def.specs.ma.map(m => m + 'mA'), (node.ma || 30) + 'mA');
      modal.appendChild(fMa.wrap);
    }

    // ── Belasting % ───────────────────────────────────────────────────────────
    const fLoad = this._mkF('Belasting %', 'number', node.load > 0 ? Math.round(node.load * 100) : '', '0–100');
    modal.appendChild(fLoad.wrap);

    // ── Acties ────────────────────────────────────────────────────────────────
    const acts = document.createElement('div');
    acts.className = 'm-acts';

    const bSave = document.createElement('button');
    bSave.className = 'm-save';
    bSave.textContent = 'Opslaan';
    bSave.onclick = () => {
      node.label = fLbl.inp.value.trim();
      node.brand = fBrnd.sel.value;
      if (fAmp)  node.amp   = parseInt(fAmp.sel.value);
      if (fPh)   node.phase = fPh.sel.value;
      if (fKar)  node.kar   = fKar.sel.value.replace('-kar', '');
      if (fMa)   node.ma    = parseInt(fMa.sel.value);
      if (fRCDPhase) node.phase = fRCDPhase.sel.value;
      if (fLoad.inp.value) node.load = Math.min(1, Math.max(0, parseInt(fLoad.inp.value) / 100));
      if (fRCD) {
        const selLabel = fRCD.sel.value;
        const selRCD   = rcdNodes.find(n => (n.label || n.defLabel) === selLabel);
        node.parentRCDId = selRCD ? selRCD.id : null;
      }
      if (fMain) {
        const selMainLbl = fMain.sel.value;
        const selMain = mainNodes.find(n => (n.label || n.defLabel) === selMainLbl);
        node.parentMainId = selMain ? selMain.id : null;
      }
      mr.innerHTML = '';
      this._saveToHA(node);
      this._renderKast();
    };

    const bDel = document.createElement('button');
    bDel.className = 'm-del';
    bDel.textContent = 'Verwijder';
    bDel.onclick = () => {
      this._rails.forEach(r => { const i = r.indexOf(node); if (i >= 0) r.splice(i, 1); });
      this._rails = this._rails.filter((r, i) => r.length > 0 || i === 0);
      if (this._rails.length === 0) this._rails = [[]];
      mr.innerHTML = '';
      if (this._hass) {
        this._hass.callService('cloudems', 'remove_node', { node_id: node.id }).catch(() => {});
      }
      this._savePanelToHA();
      this._renderKast();
    };

    const bCan = document.createElement('button');
    bCan.className = 'm-can';
    bCan.textContent = 'Annuleer';
    bCan.onclick = () => { mr.innerHTML = ''; };

    acts.appendChild(bSave);
    acts.appendChild(bDel);
    acts.appendChild(bCan);
    modal.appendChild(acts);

    bg.appendChild(modal);
    mr.appendChild(bg);
  }
  _openWizard(node) {
    const wa = this.shadowRoot.getElementById('wiz-area');
    wa.innerHTML = '';
    const wiz = document.createElement('div');
    wiz.className = 'wiz';

    const t = document.createElement('div');
    t.className = 'wiz-t';
    t.textContent = 'Leer-wizard: ' + (node.label || node.defLabel);
    wiz.appendChild(t);

    ['1. Zet groep "' + (node.label || node.defLabel) + '" UIT',
     '2. Wacht 30 seconden (P1 + cloud vertraging)',
     '3. CloudEMS meet vermogensverschil per fase',
     '4. Apparaten die verdwijnen worden aan deze groep gekoppeld'
    ].forEach(txt => {
      const s = document.createElement('div');
      s.className = 'wiz-step';
      s.textContent = txt;
      wiz.appendChild(s);
    });

    const acts = document.createElement('div');
    acts.className = 'wiz-acts';
    const bStart = document.createElement('button');
    bStart.className = 'wb-p';
    bStart.textContent = '▶ Start meting';
    bStart.onclick = () => {
      if (this._hass) {
        this._hass.callService('cloudems', 'start_circuit_learning', { node_id: node.id });
      }
      node.learned = true;
      wa.innerHTML = '';
      this._renderKast();
    };
    const bCan = document.createElement('button');
    bCan.className = 'wb-s';
    bCan.textContent = 'Annuleer';
    bCan.onclick = () => { wa.innerHTML = ''; };
    acts.appendChild(bStart);
    acts.appendChild(bCan);
    wiz.appendChild(acts);
    wa.appendChild(wiz);
  }

  _getCountryNorm() {
    // Lees land uit status of price sensor
    const country = (
      this._hass?.states?.['sensor.cloudems_status']?.attributes?.country ||
      this._hass?.states?.['sensor.cloudems_price']?.attributes?.country ||
      'NL'
    ).toUpperCase().trim();
    return EU_NORMS[country] || EU_NORMS._DEFAULT;
  }

  _isMCBType(defType) {
    return !defType.startsWith('rcd') && !defType.startsWith('main') &&
           !defType.startsWith('rcbo') && defType !== 'blank' && defType !== 'isolator';
  }

  _buildGroupNumberMap() {
    // Bouw een map van node.id → groepnummer, gebaseerd op huidige railsvolgorde
    // Zowel kast als schema gebruiken deze map → altijd synchroon
    const map = {};
    let count = 0;
    this._rails.forEach(rail => {
      rail.forEach(node => {
        if (this._isMCBType(node.defType)) {
          count++;
          map[node.id] = count;
        }
      });
    });
    return map;
  }

  _cardTypeToNodeType(defType) {
    // Vertaal kaart variant type naar backend NodeType
    const map = {
      'main_2p': 'main',   'main_4p': 'main',
      'rcd_2p_a': 'rcd',  'rcd_2p_b': 'rcd',
      'rcd_4p_a': 'rcd',  'rcd_4p_b': 'rcd',
      'rcbo_1pn': 'rcbo', 'rcbo_2p': 'rcbo',  'rcbo_3pn': 'rcbo',
      'mcb_1p': 'mcb',    'mcb_2p': 'mcb',    'mcb_1p_uk': 'mcb',  'mcb_3p': 'mcb_3f',
      'pv_1pn': 'mcb',    'pv_3p': 'mcb_3f',
      'isolator': 'mcb',  'blank': 'mcb',
    };
    return map[defType] || 'mcb';
  }

  _registerNodeInBackend(node) {
    // Registreer nieuw toegevoegde node in backend via add_circuit_node
    // Geeft node zijn definitieve backend-ID (zelfde als kaart-ID)
    if (!this._hass) return;
    this._hass.callService('cloudems', 'add_circuit_node', {
      id:             node.id,
      name:           node.label || '',
      node_type:      this._cardTypeToNodeType(node.defType),
      card_type:      node.defType,
      ampere:         node.amp,
      phase:          node.phase || '',
      kar:            node.kar || 'B',
      ma:             node.ma || 30,
      rcd_type:       node.rcdType || '',
      notes:          node.brand || '',
      parent_id:      node.parentRCDId || '',
      parent_main_id: node.parentMainId || '',
      rail_index:     (() => {
        for (let ri = 0; ri < this._rails.length; ri++) {
          if (this._rails[ri].includes(node)) return ri;
        }
        return this._rails.length - 1;
      })(),
    }).catch(() => {});
  }

  _savePanelToHA() {
    // Sla volledige kastconfiguratie op — wordt aangeroepen na elke structuurwijziging
    if (!this._hass) return;
    const nodes = [];
    this._rails.forEach((rail, ri) => {
      rail.forEach((node, ni) => {
        // parent_id: handmatig gezet parentRCDId heeft prioriteit, anders positie-afleiding
        const parentId = node.parentRCDId || node.parentMainId || '';
        // Encode rail + positie: rail_index * 1000 + node_index
        // Zodat herstel na herstart de juiste rail weet
        nodes.push({
          id:           node.id,
          parent_id:    parentId,
          parent_main_id: node.parentMainId || '',
          position:     ri * 1000 + ni,
          rail_index:   ri,
        });
      });
    });
    this._hass.callService('cloudems', 'save_circuit_panel', { nodes }).catch(() => {});
  }

  _saveToHA(node) {
    if (!this._hass) return;
    try {
      this._hass.callService('cloudems', 'update_circuit_node', {
        node_id:        node.id,
        name:           node.label,
        brand:          node.brand,
        ampere:         node.amp,
        phase:          node.phase,
        kar:            node.kar,
        ma:             node.ma,
        rcd_type:       node.rcdType,
        card_type:      node.defType,
        parent_id:      node.parentRCDId || '',
        parent_main_id: node.parentMainId || '',
      }).catch(() => {});
    } catch (e) {}
  }

  _mkF(label, type, val, ph) {
    const wrap = document.createElement('div');
    wrap.className = 'mf';
    const lbl = document.createElement('label');
    lbl.textContent = label;
    wrap.appendChild(lbl);
    const inp = document.createElement('input');
    inp.type = type;
    inp.value = val || '';
    if (ph) inp.placeholder = ph;
    wrap.appendChild(inp);
    return { wrap, inp };
  }

  _mkSF(label, opts, selected) {
    const wrap = document.createElement('div');
    wrap.className = 'mf';
    const lbl = document.createElement('label');
    lbl.textContent = label;
    wrap.appendChild(lbl);
    const sel = document.createElement('select');
    opts.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o;
      opt.textContent = o || '(geen)';
      if (String(o) === String(selected)) opt.selected = true;
      sel.appendChild(opt);
    });
    wrap.appendChild(sel);
    return { wrap, sel };
  }

  _buildLegend() {
    const leg = this.shadowRoot.getElementById('legend');
    if (!leg) return;
    leg.innerHTML = '';
    [{c:'#f97316',l:'L1'},{c:'#3b82f6',l:'L2'},{c:'#22c55e',l:'L3'},{c:'#a855f7',l:'3F'},
     {c:'#f97316',l:'Aardlek A'},{c:'#ef4444',l:'Aardlek B (EV/PV)'},{c:'#22c55e',l:'PV AC'}
    ].forEach(it => {
      const li = document.createElement('div');
      li.className = 'li';
      const d = document.createElement('span');
      d.className = 'ld';
      d.style.background = it.c;
      li.appendChild(d);
      li.appendChild(document.createTextNode(it.l));
      leg.appendChild(li);
    });
  }

  // ── Live norm check op huidige rails ────────────────────────────────────────


  _getCountry() {
    const h = this._hass;
    if (!h) return 'NL';
    const st = h.states['sensor.cloudems_status'];
    if (st?.attributes?.country) return st.attributes.country.toUpperCase();
    const pr = h.states['sensor.cloudems_price'];
    if (pr?.attributes?.country) return pr.attributes.country.toUpperCase();
    return 'NL';
  }

  _getStd() {
    const cc = this._getCountry();
    return ELECTRICAL_STANDARDS[cc] || ELECTRICAL_STANDARDS.DEFAULT;
  }


  _checkNEN1010Live() {
    const warnings = [];
    const allNodes = this._rails.flat();
    if (allNodes.length === 0) return warnings;

    const std = this._getStd();
    const normName = std.name;
    const maxPerRCD = std.maxGroupsPerRCD30mA;

    const mains = allNodes.filter(n => n.defType.startsWith('main'));
    const rcds  = allNodes.filter(n => n.defType.startsWith('rcd'));
    const mcbs  = allNodes.filter(n =>
      !n.defType.startsWith('rcd') && !n.defType.startsWith('main') &&
      !n.defType.startsWith('rcbo') && n.defType !== 'blank' && n.defType !== 'isolator');

    // Geen hoofdschakelaar
    if (!mains.length) {
      warnings.push({ severity:'red', message:'Geen hoofdschakelaar',
        detail:`Een groepenkast vereist een hoofdschakelaar. (${normName})` });
    }

    // Tel MCBs per aardlek — alleen als norm een max heeft
    if (maxPerRCD) {
      const rcdCount = {};
      rcds.forEach(r => { rcdCount[r.id] = 0; });
      mcbs.forEach(n => {
        // Alleen tellen als parent een aardlekSCHAKELAAR is, niet een RCBO
        const par = allNodes.find(x => x.id === n.parentRCDId);
        if (par && par.defType.startsWith('rcd') && !par.defType.startsWith('rcbo')
            && rcdCount[par.id] !== undefined) {
          rcdCount[par.id]++;
        }
      });
      rcds.forEach(rcd => {
        const cnt = rcdCount[rcd.id] || 0;
        if (cnt > maxPerRCD) {
          warnings.push({
            severity: 'orange',
            message: `Te veel groepen op aardlek "${rcd.label || rcd.defLabel}"`,
            detail: `${cnt} groepen — max ${maxPerRCD} per ${std.rcdSensitivity||30}mA aardlek (${normName}). RCBO's tellen niet mee.`,
            _rcdId: rcd.id,
          });
        }
      });
    }

    // Groepen zonder aardlek
    if (std.rcdRequired) {
      const unprotected = mcbs.filter(n => !n.parentRCDId);
      if (unprotected.length > 0) {
        warnings.push({
          severity: 'orange',
          message: `${unprotected.length} groep(en) zonder aardlekbeveiliging`,
          detail: `Koppel elke groep aan een aardlekschakelaar. (${normName})`,
        });
      }
    }

    return warnings;
  }

  // ── Print / PDF export ───────────────────────────────────────────────────────

  _printSchema() {
    const std = this._getStd();
    const root = this.shadowRoot;
    const svgEl = root?.getElementById('schema-body')?.querySelector('svg');
    if (!svgEl) return;

    const svgData = new XMLSerializer().serializeToString(svgEl);
    const svgBlob = new Blob([svgData], {type:'image/svg+xml'});
    const url = URL.createObjectURL(svgBlob);

    // Open in nieuw venster voor afdrukken
    const win = window.open('', '_blank');
    if (!win) return;
    const now = new Date().toLocaleDateString('nl-NL');
    win.document.write(`<!DOCTYPE html><html><head>
      <title>Installatieschema Groepenkast — ${now}</title>
      <style>
        body { margin:20px; font-family:sans-serif; background:#fff; color:#000; }
        h2 { font-size:16px; margin-bottom:4px; }
        .meta { font-size:11px; color:#666; margin-bottom:16px; }
        svg { max-width:100%; filter:invert(1); background:#fff; }
        @media print { body { margin:10mm; } h2 { font-size:14px; } }
      </style>
    </head><body>
      <h2>Installatieschema Groepenkast</h2>
      <div class="meta">${std.fullName || std.name} &bull; Gegenereerd door CloudEMS &bull; ${now}</div>
      <img src="${url}" style="max-width:100%;"/>
    </body></html>`);
    win.document.close();
    setTimeout(() => { win.print(); URL.revokeObjectURL(url); }, 500);
  }

  // ── Schema rendering ────────────────────────────────────────────────────────

  _getParentRCD(node, ri) {
    // Geeft de RCD links van de node op dezelfde rail terug (meest rechts)
    const rail = this._rails[ri] || [];
    const idx = rail.indexOf(node);
    for (let i = idx - 1; i >= 0; i--) {
      if (rail[i].defType.startsWith('rcd') || rail[i].defType.startsWith('rcbo')) return rail[i];
    }
    return null;
  }

  _buildHierarchy() {
    // Bouw boom: { node, ri, ni, children:[] }
    // Prioriteit: node.parentRCDId (handmatig gekoppeld) > positie op rail
    const roots = [];
    const rcdMap = new Map(); // rcd.id → treeNode
    const allTN  = new Map(); // node.id → treeNode

    // Stap 1: maak alle treeNodes aan
    this._rails.forEach((rail, ri) => {
      rail.forEach((node, ni) => {
        const tn = { node, ri, ni, children: [] };
        allTN.set(node.id, tn);
        if (node.defType.startsWith('rcd') || node.defType.startsWith('rcbo')) {
          rcdMap.set(node.id, tn);
        }
      });
    });

    // Stap 2: koppel nodes aan parent
    // Vind de (eerste) hoofdschakelaar — aardlekken hangen daar altijd onder
    const mainNodes = [...allTN.values()].filter(tn => tn.node.defType.startsWith('main'));
    const firstMain = mainNodes[0] || null;

    this._rails.forEach((rail, ri) => {
      rail.forEach((node, ni) => {
        const tn = allTN.get(node.id);
        if (node.defType.startsWith('main')) {
          // Hoofdschakelaar: hangt onder parentMainId als die gezet is (serie-schakeling)
          const parentMainTN = node.parentMainId ? allTN.get(node.parentMainId) : null;
          if (parentMainTN) {
            parentMainTN.children.push(tn);
          } else {
            roots.unshift(tn);
          }
        } else if (node.defType.startsWith('rcd')) {
          // RCD: hangt onder parentMainId of eerste hoofdschakelaar
          const explicitMain = node.parentMainId ? allTN.get(node.parentMainId) : null;
          const parentMain   = explicitMain || firstMain;
          if (parentMain) {
            parentMain.children.push(tn);
          } else {
            roots.push(tn);
          }
        } else if (!node.defType.startsWith('rcbo')) {
          // MCB: gebruik handmatige parentRCDId als gezet, anders positie op rail
          const explicitParent = node.parentRCDId && rcdMap.has(node.parentRCDId)
            ? rcdMap.get(node.parentRCDId) : null;
          const posParent = (() => {
            const p = this._getParentRCD(node, ri);
            return p && rcdMap.has(p.id) ? rcdMap.get(p.id) : null;
          })();
          // Fallback: als geen RCD op eigen rail, zoek eerste RCD op andere rails
          // (bijv. automaten op Rail 1, aardlekken op Rail 2)
          const crossRailParent = (!explicitParent && !posParent) ? (() => {
            for (let ri2 = 0; ri2 < this._rails.length; ri2++) {
              if (ri2 === ri) continue;
              for (const cand of this._rails[ri2]) {
                if ((cand.defType.startsWith('rcd') || cand.defType.startsWith('rcbo'))
                    && rcdMap.has(cand.id)) {
                  return rcdMap.get(cand.id);
                }
              }
            }
            return null;
          })() : null;
          const parent = explicitParent || posParent || crossRailParent;
          if (parent) {
            tn.parentNode = parent.node;
            parent.children.push(tn);
          } else {
            roots.push(tn);
          }
        } else {
          // RCBO: zelf ook als leaf behandelen onder bovenliggende RCD
          const posParent = (() => {
            const p = this._getParentRCD(node, ri);
            return p && rcdMap.has(p.id) ? rcdMap.get(p.id) : null;
          })();
          if (posParent) posParent.children.push(tn);
          else roots.push(tn);
        }
      });
    });

    return roots;
  }

  _getLearnedDevices(nodeId) {
    // Lees NILM devices voor dit circuit uit sensor data
    const nilm = this._hass?.states?.['sensor.cloudems_nilm_status']?.attributes;
    if (!nilm) return [];
    const all = nilm.devices || nilm.nilm_devices || [];
    return all.filter(d => d.circuit_id === nodeId || d.group_id === nodeId);
  }

  _hasPhaseConflict(node) {
    // Controleer of geleerde fase afwijkt van ingestelde fase
    if (!node.phase || node.phase === '3F') return false;
    const groepenkast = this._hass?.states?.['sensor.cloudems_groepenkast']?.attributes;
    if (!groepenkast) return false;
    const saved = (groepenkast.nodes || []).find(n => n.id === node.id);
    if (!saved || !saved.phase_learned) return false;
    return saved.phase_learned !== node.phase;
  }

  _renderSchema() {
    const root = this.shadowRoot;
    if (!root) return;
    const body = root.getElementById('schema-body');
    if (!body) return;
    body.innerHTML = '';

    // Toon landspecifieke normnaam in header
    const std = this._getStd();
    const schHd = root.getElementById('schema-hd-s');
    if (schHd) schHd.textContent = std.name;

    // NEN 1010 live waarschuwingen bovenaan
    const nen = this._hass?.states?.['sensor.cloudems_groepenkast']?.attributes;
    const findings = nen?.nen1010_findings || [];
    const liveWarnings = this._checkNEN1010Live();
    const allWarnings = [...liveWarnings,
      ...findings.filter(f => f.severity === 'red'),
      ...findings.filter(f => f.severity === 'orange').slice(0, 2)];
    allWarnings.forEach(w => {
      const wd = document.createElement('div');
      wd.className = 'schema-warn';
      const icon = w.severity === 'red' ? '🔴' : '🟠';
      wd.innerHTML = `<b>${icon} ${w.message||w.code}</b><br><span style="color:#888">${w.detail||''}</span>`;
      body.appendChild(wd);
    });

    const allNodes = this._rails.flat();
    if (allNodes.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding:20px 12px;font-size:10px;color:#333;text-align:center;line-height:1.6;';
      empty.innerHTML = '<div style="font-size:18px;margin-bottom:6px;">📐</div><div style="color:#2a2a2a;">Schema verschijnt zodra je componenten toevoegt</div>';
      body.appendChild(empty);
      return;
    }

    // ── Bouw installatieschema als SVG ladder-diagram ─────────────────────────
    // Lay-out constanten
    const COL_BUS  = 28;   // x van de verticale bus
    const COL_COMP = 52;   // x midden van component symbolen
    const COL_LINE = 130;  // x start van horizontale draad naar belasting
    const COL_LOAD = 134;  // x start label box
    const LOAD_W   = 110;  // breedte label box
    const LOAD_H   = 18;   // hoogte label box
    const ROW_H    = 30;   // hoogte per MCB rij
    const COMP_H   = 36;   // hoogte per RCD/hoofd sectie
    const SYM_W    = 28;   // breedte component symbool
    const SYM_H    = 22;   // hoogte component symbool

    // Groepnummer map — synchroon met kast weergave
    const gnMap = this._buildGroupNumberMap();

    // Bereken totale SVG hoogte
    let totalH = 20; // top margin
    const mains = allNodes.filter(n => n.defType.startsWith('main'));
    totalH += mains.length * (COMP_H + 8);

    // Bouw hiërarchie
    const hierarchy = this._buildHierarchy();

    // Tel rijen
    const countRows = (nodes) => {
      let rows = 0;
      nodes.forEach(tn => {
        const isMCB = !tn.node.defType.startsWith('rcd') && !tn.node.defType.startsWith('main') && !tn.node.defType.startsWith('rcbo');
        if (isMCB || tn.node.defType.startsWith('rcbo')) {
          rows++;
        } else if (tn.node.defType.startsWith('rcd')) {
          rows += COMP_H / ROW_H;
          rows += countRows(tn.children);
        }
      });
      return rows;
    };
    hierarchy.forEach(tn => {
      if (tn.node.defType.startsWith('main')) totalH += COMP_H + 6;
      else if (tn.node.defType.startsWith('rcd')) {
        totalH += COMP_H + 8;
        totalH += tn.children.length * ROW_H + 8;
      } else {
        totalH += ROW_H;
      }
    });
    totalH += 20;

    const SVG_W = COL_LOAD + LOAD_W + 10;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', SVG_W);
    svg.setAttribute('height', totalH);
    svg.style.cssText = 'display:block;overflow:visible;';

    const PC = {L1:'#f97316',L2:'#3b82f6',L3:'#22c55e','3F':'#a855f7',DC:'#4ade80','':'#6b7280'};
    const C_WIRE = '#4a5568';
    const C_TEXT = '#9ca3af';
    const C_DIM  = '#374151';
    const C_WARN = '#ef4444';

    const el = (tag, attrs={}) => {
      const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([k,v]) => e.setAttribute(k,v));
      return e;
    };
    const line = (x1,y1,x2,y2,clr=C_WIRE,w=1.5) => el('line',{x1,y1,x2,y2,stroke:clr,'stroke-width':w,'stroke-linecap':'round'});
    const rect = (x,y,w,h,fill='none',stroke=C_WIRE,rx=2,sw=1) => el('rect',{x,y,width:w,height:h,fill,stroke,'stroke-width':sw,rx});
    const txt = (x,y,t,fill=C_TEXT,size=9,anchor='start',fw='normal') => {
      const e = el('text',{x,y,'text-anchor':anchor,'font-size':size,fill,'font-family':'system-ui','font-weight':fw});
      e.textContent = t; return e;
    };

    // ── Symbool tekenfuncties ─────────────────────────────────────────────────

    // Hoofdschakelaar: rechthoek met 2 verticale lijnen (open kontakten)
    const drawMain = (cx, cy, node) => {
      const x = cx - SYM_W/2, y = cy - SYM_H/2;
      svg.appendChild(rect(x, y, SYM_W, SYM_H, '#1e1e2e', '#6a6ab0', 3, 1.5));
      // Twee parallelle open contacten
      svg.appendChild(line(cx-6, y+4, cx-6, y+SYM_H-4, '#22c55e', 2));
      svg.appendChild(line(cx+6, y+4, cx+6, y+SYM_H-4, '#22c55e', 2));
      // Label
      svg.appendChild(txt(cx, cy+SYM_H/2+10, `${node.amp}A ${node.poles||''}`, C_DIM, 8, 'middle'));
    };

    // Aardlekschakelaar: rechthoek + test-cirkel
    const drawRCD = (cx, cy, node) => {
      const x = cx - SYM_W/2, y = cy - SYM_H/2;
      const bc = node.rcdType === 'B' ? '#ef4444' : '#f97316';
      svg.appendChild(rect(x, y, SYM_W, SYM_H, '#2a1800', bc, 3, 1.5));
      // Test-knop cirkel
      svg.appendChild(el('circle',{cx,cy:cy-2,r:5,fill:'none',stroke:bc,'stroke-width':1.5}));
      svg.appendChild(txt(cx, cy-2+3, 'T', bc, 7, 'middle'));
      // mA label
      svg.appendChild(txt(cx, cy+SYM_H/2+10, `${node.amp}A ${node.ma||30}mA`, C_DIM, 8, 'middle'));
    };

    // RCBO: combinatie
    const drawRCBO = (cx, cy, node) => {
      const x = cx - SYM_W/2, y = cy - SYM_H/2;
      svg.appendChild(rect(x, y, SYM_W, SYM_H, '#1e1200', '#f59e0b', 3, 1.5));
      svg.appendChild(el('circle',{cx,cy:cy-3,r:4,fill:'none',stroke:'#f59e0b','stroke-width':1.5}));
      svg.appendChild(txt(cx, cy+SYM_H/2+10, `${node.amp}A`, C_DIM, 8, 'middle'));
    };

    // MCB: rechthoek met schuine lijn (schakelaar symbool)
    const drawMCB = (cx, cy, node) => {
      const x = cx - SYM_W/2, y = cy - SYM_H/2;
      const phColor = PC[node.phase] || C_WIRE;
      svg.appendChild(rect(x, y, SYM_W, SYM_H, '#0e0e18', phColor, 2, 1.5));
      // Schuine lijn = schakelaar
      svg.appendChild(line(cx-6, cy+4, cx+5, cy-5, phColor, 1.5));
      svg.appendChild(el('circle',{cx:cx-6,cy:cy+4,r:2,fill:phColor}));
    };

    // Label box rechts
    const drawLoadBox = (y, node, groupNum) => {
      const cy = y + LOAD_H/2;
      svg.appendChild(rect(COL_LOAD, y, LOAD_W, LOAD_H, '#0a0a0a', C_DIM, 2, 1));
      const label = node.label || '';
      const numStr = groupNum > 0 ? `${groupNum}` : '';
      if (numStr) {
        svg.appendChild(rect(COL_LOAD, y, 16, LOAD_H, '#1a1a2a', C_DIM, 2, 1));
        svg.appendChild(txt(COL_LOAD+8, y+LOAD_H-5, numStr, '#6b7280', 8, 'middle', '600'));
      }
      const textX = COL_LOAD + (numStr ? 20 : 6);
      svg.appendChild(txt(textX, y+LOAD_H-5, label || '—', label ? C_TEXT : C_DIM, 9));
    };

    // ── Render loop ──────────────────────────────────────────────────────────
    let curY = 16;

    // Bovenste bus lijn
    svg.appendChild(line(COL_BUS, curY, COL_BUS, totalH - 16, C_WIRE, 2));

    const renderNode = (tn) => {
      const { node } = tn;
      const isMain  = node.defType.startsWith('main');
      const isRCD   = node.defType.startsWith('rcd');
      const isRCBO  = node.defType.startsWith('rcbo');
      const isMCB   = !isMain && !isRCD && !isRCBO &&
                      node.defType !== 'blank' && node.defType !== 'isolator';

      if (isMain) {
        const cy = curY + COMP_H/2;
        // Aftakking van bus naar component
        svg.appendChild(line(COL_BUS, cy, COL_COMP - SYM_W/2, cy, C_WIRE, 1.5));
        drawMain(COL_COMP, cy, node);
        // Verticale lijn verder
        svg.appendChild(line(COL_COMP, cy + SYM_H/2, COL_COMP, cy + COMP_H/2 + 4, C_WIRE, 1.5));
        curY += COMP_H + 6;

      } else if (isRCD) {
        const cy = curY + COMP_H/2;
        svg.appendChild(line(COL_BUS, cy, COL_COMP - SYM_W/2, cy, C_WIRE, 1.5));
        drawRCD(COL_COMP, cy, node);
        // Verticale rail voor MCBs
        const railTop = cy + SYM_H/2 + 2;
        const railBot = railTop + tn.children.length * ROW_H;
        svg.appendChild(line(COL_COMP, railTop, COL_COMP, railBot, C_WIRE, 1.5));
        curY += COMP_H + 4;
        tn.children.forEach(child => renderNode(child));
        curY += 8;

      } else if (isRCBO) {
        const cy = curY + ROW_H/2;
        svg.appendChild(line(COL_COMP, cy, COL_COMP + SYM_W/2, cy, C_WIRE, 1));
        drawRCBO(COL_COMP + SYM_W/2 + SYM_W/2, cy, node);
        svg.appendChild(line(COL_COMP + SYM_W + 4, cy, COL_LINE, cy, C_WIRE, 1));
        drawLoadBox(cy - LOAD_H/2, node, gnMap[node.id] || 0);
        curY += ROW_H;

      } else if (isMCB) {
        const cy = curY + ROW_H/2;
        // Erven fase van parent als de MCB zelf geen fase heeft
        let effPhase = node.phase;
        if ((!effPhase || effPhase === '') && tn.parentNode) {
          effPhase = tn.parentNode.phase || '';
        }
        const phColor = PC[effPhase] || C_WIRE;
        svg.appendChild(line(COL_COMP, cy, COL_COMP + SYM_W/2, cy, phColor, 1));
        drawMCB(COL_COMP + SYM_W, cy, node);
        svg.appendChild(line(COL_COMP + SYM_W + SYM_W/2, cy, COL_LINE, cy, phColor, 1));
        drawLoadBox(cy - LOAD_H/2, node, gnMap[node.id] || 0);
        curY += ROW_H;

      } else if (node.defType === 'isolator') {
        const cy = curY + ROW_H/2;
        svg.appendChild(line(COL_COMP, cy, COL_LINE, cy, C_DIM, 1));
        drawLoadBox(cy - LOAD_H/2, node, 0);
        curY += ROW_H;
      }
    };

    hierarchy.forEach(tn => renderNode(tn));
    // Losse nodes die niet in hiërarchie zitten
    const inHierarchy = new Set(hierarchy.flatMap(tn => [tn.node.id, ...tn.children.map(c => c.node.id)]));
    allNodes.forEach(node => {
      if (!inHierarchy.has(node.id)) {
        const fake = { node, children: [] };
        renderNode(fake);
      }
    });

    body.appendChild(svg);
  }
  _openAssignDialog(node, ri) {
    const mr = this.shadowRoot.getElementById('modal-root');
    mr.innerHTML = '';
    const bg = document.createElement('div');
    bg.className = 'modal-bg';
    bg.addEventListener('click', e => { if (e.target === bg) mr.innerHTML = ''; });
    const modal = document.createElement('div');
    modal.className = 'modal';

    const title = document.createElement('div');
    title.className = 'modal-t';
    title.textContent = '⚙ Koppeling: ' + (node.label || node.defLabel);
    modal.appendChild(title);

    // Info tekst
    const info = document.createElement('div');
    info.style.cssText = 'font-size:10px;color:#666;margin-bottom:12px;line-height:1.5;';
    info.textContent = 'Geef aan op welke aardlek en fase dit circuit aangesloten is. CloudEMS controleert dit automatisch en waarschuwt als de meting afwijkt.';
    modal.appendChild(info);

    // Fase selectie
    const fPh = this._mkSF('Fase', ['L1','L2','L3','3F'], node.phase || 'L1');
    modal.appendChild(fPh.wrap);

    // Aardlek selectie
    const rcdOptions = ['(geen / direct op hoofd)'];
    const rcdNodes = [];
    this._rails.forEach(rail => {
      rail.forEach(n => {
        if (n.defType.startsWith('rcd') || n.defType.startsWith('rcbo')) {
          rcdOptions.push(n.label || n.defLabel);
          rcdNodes.push(n);
        }
      });
    });
    const parent = this._getParentRCD(node, ri);
    const parentLabel = parent ? (parent.label || parent.defLabel) : '(geen / direct op hoofd)';
    const fRCD = this._mkSF('Aardlek', rcdOptions, parentLabel);
    modal.appendChild(fRCD.wrap);

    // Conflict melding als aanwezig
    if (this._hasPhaseConflict(node)) {
      const w = document.createElement('div');
      w.style.cssText = 'background:#2a1010;border:1px solid #5a1a1a;border-radius:5px;padding:8px;font-size:10px;color:#fca5a5;margin-bottom:8px;';
      w.textContent = '⚠ CloudEMS heeft een andere fase geleerd dan hier ingesteld. Controleer de bekabeling of pas de fase aan.';
      modal.appendChild(w);
    }

    const acts = document.createElement('div');
    acts.className = 'm-acts';
    const bSave = document.createElement('button');
    bSave.className = 'm-save';
    bSave.textContent = 'Opslaan';
    bSave.onclick = () => {
      node.phase = fPh.sel.value;
      // Verplaats node naar juist aardlek-groep (update parentId)
      const selRCDLabel = fRCD.sel.value;
      const selRCD = rcdNodes.find(n => (n.label || n.defLabel) === selRCDLabel);
      node.parentRCDId = selRCD ? selRCD.id : null;
      mr.innerHTML = '';
      this._saveToHA(node);
      this._renderKast();
    };
    const bCan = document.createElement('button');
    bCan.className = 'm-can';
    bCan.textContent = 'Annuleer';
    bCan.onclick = () => { mr.innerHTML = ''; };
    acts.appendChild(bSave);
    acts.appendChild(bCan);
    modal.appendChild(acts);
    bg.appendChild(modal);
    mr.appendChild(bg);
  }
}

customElements.define('cloudems-groepenkast-card', CloudEMSGroepenkastCard);

// Editor stub
if (!customElements.get('cloudems-groepenkast-card-editor')) {
  class GKEditor extends HTMLElement {
    setConfig(c) { this._config = c; }
    get _hass() { return null; }
  }
  customElements.define('cloudems-groepenkast-card-editor', GKEditor);
}

} // end if !customElements.get
