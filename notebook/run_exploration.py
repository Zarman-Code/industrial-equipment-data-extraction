"""
Standalone script version of 01_pdf_exploration.ipynb
Runs all 7 analysis questions and prints results.
"""
import os, re, sys, warnings
from pathlib import Path
from collections import Counter, defaultdict

import pdfplumber
import pypdfium2 as pdfium

warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR     = PROJECT_ROOT / 'data' / 'raw'
PDF_AUSTCOLD = DATA_DIR / 'AUSTCOLD.pdf'
PDF_MYCOM    = DATA_DIR / 'MYCOM Operating and Maintenance Manual Refrigeration Unit (1).pdf'
PDFS = {'AUSTCOLD': PDF_AUSTCOLD, 'MYCOM': PDF_MYCOM}

TEXT_CHAR_THRESHOLD = 20

# ── helpers ─────────────────────────────────────────────────────────────────
def classify_pages(pdf_path, sample_size=30):
    doc = pdfium.PdfDocument(str(pdf_path))
    total = len(doc)
    step  = max(1, total // sample_size)
    indices = list(range(0, total, step))[:sample_size]
    results = []
    for i in indices:
        txt = doc[i].get_textpage().get_text_range().strip()
        results.append({'page': i+1, 'chars': len(txt), 'is_scanned': len(txt) < TEXT_CHAR_THRESHOLD})
    doc.close()
    ratio   = sum(r['is_scanned'] for r in results) / len(results)
    overall = 'SCANNED' if ratio > 0.5 else ('MIXED' if ratio > 0.1 else 'TEXT-BASED')
    return total, results, overall, ratio

def extract_full_text(pdf_path, max_pages=60):
    doc = pdfium.PdfDocument(str(pdf_path))
    n   = min(len(doc), max_pages)
    text = ''
    for i in range(n):
        text += doc[i].get_textpage().get_text_range()
    doc.close()
    return text

def find_tables(pdf_path, max_pages=80):
    found = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i in range(min(len(pdf.pages), max_pages)):
            for t_idx, table in enumerate(pdf.pages[i].extract_tables()):
                rows = [r for r in table if any(c for c in r if c and str(c).strip())]
                if len(rows) >= 2:
                    found.append({'page': i+1, 'rows': len(rows), 'cols': max(len(r) for r in rows),
                                  'header': rows[0], 'sample': rows[1] if len(rows)>1 else []})
    return found

PATTERNS = {
    'Model / Serial':  re.compile(r'(?:model|serial|s/?n|item|part)\s*[:#.\-]?\s*([A-Z0-9\-/]{3,})', re.I),
    'Numeric + Unit':  re.compile(r'\b(\d+\.?\d*)\s*(kW|kPa|bar|RPM|Hz|V|A|°C|°F|kg|L|cfm|m³|psig|psi|hp|kJ|MPa)\b', re.I),
    'Section Heading': re.compile(r'^\s{0,4}(\d{1,2}\.?\d*\.?\d*\.?\s+[A-Z][^\n]{5,60})$', re.M),
    'Key-Value pair':  re.compile(r'^\s*([A-Za-z][\w\s/()]{2,40})\s*[:\-]\s*(.{1,80})$', re.M),
    'Refrigerant':     re.compile(r'\b(R-?\d{2,4}[A-Z]?|ammonia|NH3|CO2|HFC|HCFC)\b', re.I),
    'Temperature':     re.compile(r'(?:temperature|temp|suction|discharge)\s*[:#]?\s*(-?\d+\.?\d*\s*°?[CF])', re.I),
    'Pressure':        re.compile(r'(?:pressure|press)\s*[:#]?\s*(\d+\.?\d*\s*(?:kPa|bar|psi|psig|MPa))', re.I),
    'Capacity/Power':  re.compile(r'(?:capacity|power|rating|output|load)\s*[:#]?\s*(\d+\.?\d*\s*(?:kW|TR|tons|hp))', re.I),
}

# ── MAIN ─────────────────────────────────────────────────────────────────────
print('\n' + '='*70)
print('  PDF EXPLORATION & STRUCTURE ANALYSIS')
print('='*70)

# ── File check ────────────────────────────────────────────────────────────
print('\n0. File inventory')
for name, path in PDFS.items():
    mb = path.stat().st_size / 1_048_576
    print(f'   {"✅" if path.exists() else "❌"}  {name}: {mb:.1f} MB')

# ── Q1 + Q2 ──────────────────────────────────────────────────────────────
print('\nQ1 & Q2 — Classification + Page count')
page_cls = {}
for name, path in PDFS.items():
    total, page_data, overall, ratio = classify_pages(path)
    page_cls[name] = (total, page_data, overall)
    print(f'   {name:<12}  {total:>5} pages  scanned={ratio*100:.1f}%  → {overall}')

# ── Q3 ───────────────────────────────────────────────────────────────────
print('\nQ3 — Text extraction quality (first 60 pages)')
full_texts = {}
for name, path in PDFS.items():
    ft = extract_full_text(path, 60)
    full_texts[name] = ft
    words = len(ft.split())
    chars = len(ft)
    print(f'   {name:<12}  chars={chars:,}  words={words:,}')

# ── Q4 ───────────────────────────────────────────────────────────────────
print('\nQ4 — Table detection (first 80 pages)')
all_tables = {}
for name, path in PDFS.items():
    tables = find_tables(path, 80)
    all_tables[name] = tables
    print(f'   {name:<12}  {len(tables)} table(s) found')
    for i, t in enumerate(tables[:8]):
        print(f'      Table {i+1}:  p.{t["page"]}  {t["rows"]}r × {t["cols"]}c  header={[str(h)[:20] for h in t["header"]]}')

# ── Q5 ───────────────────────────────────────────────────────────────────
print('\nQ5 — Document structure patterns')
doc_analysis = {}
for name, path in PDFS.items():
    ft = full_texts[name]
    hits = defaultdict(list)
    for label, pat in PATTERNS.items():
        for m in pat.finditer(ft):
            hits[label].append(m.group(0).strip()[:80])
    seen = set(); headings = []
    for h in hits['Section Heading']:
        if h not in seen:
            headings.append(h); seen.add(h)
    doc_analysis[name] = (hits, headings)
    print(f'\n   {name}')
    for label in PATTERNS:
        print(f'     {label:<22} {len(hits[label]):>6,} hits')
    print(f'   Section headings (sample):')
    for h in headings[:15]:
        print(f'     • {h.strip()}')

# ── Q6 ───────────────────────────────────────────────────────────────────
print('\nQ6 — Structural similarity')
names = list(PDFS.keys())
a, b  = names[0], names[1]
clsA, clsB = page_cls[a][2], page_cls[b][2]
hA = len(doc_analysis[a][1])
hB = len(doc_analysis[b][1])
heading_ratio = min(hA, hB) / max(hA + hB, 1)
both_tables   = len(all_tables[a]) > 0 and len(all_tables[b]) > 0
same_class    = clsA == clsB

print(f'   Same type?          {same_class}  ({clsA} vs {clsB})')
print(f'   Both have tables?   {both_tables}')
print(f'   Heading ratio:      {heading_ratio:.2f}')
if same_class and both_tables and heading_ratio > 0.3:
    verdict = 'STRUCTURALLY SIMILAR → unified pipeline recommended'
elif same_class:
    verdict = 'SAME TYPE, DIFFERENT LAYOUT → separate parsers may be needed'
else:
    verdict = 'STRUCTURALLY DIFFERENT → different approaches required'
print(f'   Verdict: {verdict}')

# ── Q7 ───────────────────────────────────────────────────────────────────
EXTRACTION_SCHEMA = {
    'Identification':       ['model_number','serial_number','item_number','manufacturer','document_title','document_date'],
    'Refrigeration Circuit':['refrigerant_type','refrigerant_charge_kg','compressor_type','compressor_model',
                             'cooling_capacity_kW','suction_temp_degC','discharge_temp_degC',
                             'suction_pressure_kPa','discharge_pressure_kPa','operating_speed_RPM','COP'],
    'Electrical':           ['supply_voltage_V','frequency_Hz','power_input_kW','full_load_current_A','motor_model'],
    'Physical':             ['weight_operating_kg','dimensions_L_mm','dimensions_W_mm','dimensions_H_mm','oil_type','oil_charge_L'],
    'Operating Limits':     ['ambient_temp_min_degC','ambient_temp_max_degC','design_pressure_kPa','test_pressure_kPa'],
    'Maintenance':          ['oil_change_interval_h','filter_change_interval','alarm_high_pressure_kPa',
                             'alarm_low_pressure_kPa','alarm_high_temp_degC','safety_cutout_pressure_kPa'],
}
total_fields = sum(len(v) for v in EXTRACTION_SCHEMA.values())
print(f'\nQ7 — Extraction schema: {total_fields} fields across {len(EXTRACTION_SCHEMA)} categories')
for cat, fields in EXTRACTION_SCHEMA.items():
    print(f'   {cat}: {", ".join(fields)}')

print('\n' + '='*70)
print('  ✅  Analysis complete.')
print('='*70)
