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
