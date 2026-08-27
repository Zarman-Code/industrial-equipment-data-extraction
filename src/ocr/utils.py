import re
from typing import Dict, Any

import pandas as pd


def normalize_text(text: str) -> str:
    """
    Normalize OCR text.
    """

    if not text:
        return ""

    text = str(text)

    # Replace special spaces and characters
    text = (
        text
        .replace("\u00a0", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )

    # Normalize temperature
    text = text.replace("°C", " C")
    text = text.replace("deg C", " C")

    # Convert decimal comma to decimal point
    text = re.sub(
        r"(\d+),(\d+)",
        r"\1.\2",
        text
    )

    # Remove multiple spaces
    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the reconstructed OCR table.
    """

    if df.empty:
        return df

    df_clean = df.map(
        lambda value:
            re.sub(r"\s+", " ", str(value)).strip()
            if pd.notnull(value)
            else ""
    )

    # Remove completely empty rows
    df_clean = df_clean.loc[
        ~(df_clean == "").all(axis=1)
    ]

    # Remove completely empty columns
    df_clean = df_clean.loc[
        :,
        ~(df_clean == "").all(axis=0)
    ]

    return df_clean.reset_index(drop=True)


def extract_equipment_fields(
    df: pd.DataFrame,
    free_text_corpus: str = ""
) -> Dict[str, Dict[str, Any]]:
    """
    Extract equipment specifications from OCR text.
    """

    # Build searchable text corpus
    lines = []

    if not df.empty:

        for column in df.columns:

            lines.append(str(column))

            for value in df[column]:

                lines.append(
                    f"{column} : {value}"
                )

                lines.append(
                    str(value)
                )

    if free_text_corpus:
        lines.append(free_text_corpus)

    full_text = "\n".join(lines)
    full_text = normalize_text(full_text)

    # Field extraction rules
    field_rules = {

        "manufacturer": {
            "patterns": [
                r"(?:Manufacturer|Brand|Mfr|Fabricant|Hersteller|Constructeur)"
                r"\s*[:=]?\s*([A-Za-z0-9&.\- ]+)",

                r"\b(SIEMENS(?:\s+AG)?|ABB|SCHNEIDER\s+ELECTRIC|"
                r"WEG|LEROY[- ]SOMER|GRUNDFOS|SEW[- ]EURODRIVE|"
                r"ATLAS\s+COPCO|DANFOSS|EATON)\b"
            ],
            "unit": ""
        },

        "model": {
            "patterns": [
                r"(?:Motor\s*Type|Type\s*Code|Model|Type|Ref|Catalog\s*No)"
                r"\s*[:=]?\s*([A-Za-z0-9\-_/]{4,30})",

                r"\b([0-9][A-Z0-9]{3,}-[A-Z0-9]{3,}-[A-Z0-9]{3,})\b"
            ],
            "unit": ""
        },

        "serial_number": {
            "patterns": [
                r"(?:Serial\s*No|Serial\s*Number|S/N|SN|N°\s*Série|Matr)"
                r"\s*[:=]?\s*([A-Za-z0-9\-_/]{5,30})",

                r"\b(SN[- ][0-9A-Za-z\-]+)\b"
            ],
            "unit": ""
        },

        "power": {
            "patterns": [
                r"([0-9]+(?:\.[0-9]+)?\s*(?:kW|HP|MW|kVA|W))",

                r"(?:Rated\s*Power|Power|Pn|Puissance)"
                r"\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?\s*"
                r"(?:kW|HP|MW|kVA|W)?)"
            ],
            "unit": "kW"
        },

        "voltage": {
            "patterns": [
                r"([0-9]{2,4}\s*(?:/[0-9]{2,4})?\s*(?:V|kV|VAC|VDC))",

                r"(?:Rated\s*Voltage|Voltage|Un|Tension)"
                r"\s*[:=]?\s*([0-9]{2,4}\s*"
                r"(?:/[0-9]{2,4})?\s*V?)"
            ],
            "unit": "V"
        },

        "frequency": {
            "patterns": [
                r"([0-9]{2,3}(?:\.[0-9]+)?\s*Hz)",

                r"(?:Frequency|Freq|fn|Fréquence)"
                r"\s*[:=]?\s*([0-9]{2,3}(?:\.[0-9]+)?\s*Hz?)"
            ],
            "unit": "Hz"
        },

        "current": {
            "patterns": [
                r"([0-9]+(?:\.[0-9]+)?\s*"
                r"(?:/[0-9]+(?:\.[0-9]+)?)?\s*A)\b",

                r"(?:Rated\s*Current|Current|In|Courant|Intensité)"
                r"\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?\s*A?)"
            ],
            "unit": "A"
        },

        "speed": {
            "patterns": [
                r"([0-9]{3,5}\s*(?:RPM|rpm|1/min|tr/min|min-1))",

                r"(?:Rated\s*Speed|Speed|n|Vitesse)"
                r"\s*[:=]?\s*([0-9]{3,5})"
            ],
            "unit": "RPM"
        },

        "efficiency_class": {
            "patterns": [
                r"\b(IE[1-4](?:\s*Premium)?(?:\s*\([0-9.]+\s*%\))?)\b",

                r"(?:Efficiency\s*Class|Rendement)"
                r"\s*[:=]?\s*([A-Za-z0-9\s%().]+)"
            ],
            "unit": ""
        },

        "protection_degree": {
            "patterns": [
                r"\b(IP\s*[0-9]{2}(?:\s*/\s*IP\s*[0-9]{2})?)\b",

                r"(?:Protection|Degree|IP)"
                r"\s*[:=]?\s*(IP\s*[0-9]{2})"
            ],
            "unit": ""
        },

        "insulation_class": {
            "patterns": [
                r"(?:Insulation\s*Class|Classe\s*Isolement|Isol)"
                r"\s*[:=]?\s*([A-Za-z0-9\s()]+)",

                r"\b(Class\s*1[358]0(?:\s*\([A-Z]\))?)\b"
            ],
            "unit": ""
        },

        "weight": {
            "patterns": [
                r"([0-9]+(?:\.[0-9]+)?\s*(?:kg|lbs|g|tonnes))",

                r"(?:Total\s*Weight|Weight|Masse|Poids)"
                r"\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?\s*kg?)"
            ],
            "unit": "kg"
        },

        "operating_pressure": {
            "patterns": [
                r"([0-9]+(?:\.[0-9]+)?\s*(?:bar|psi|MPa|kPa))",

                r"(?:Operating\s*Pressure|Pressure|Pression)"
                r"\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?\s*bar?)"
            ],
            "unit": "bar"
        }
    }

    extracted = {}

    for field, rule in field_rules.items():

        found_value = None

        for pattern in rule["patterns"]:

            match = re.search(
                pattern,
                full_text,
                re.IGNORECASE
            )

            if match:
                found_value = match.group(1).strip()
                break

        if found_value:

            extracted[field] = {
                "raw_value": found_value,
                "normalized_value": normalize_text(
                    found_value
                ),
                "unit": rule["unit"],
                "confidence": 0.95
            }

        else:

            extracted[field] = {
                "raw_value": None,
                "normalized_value": None,
                "unit": rule["unit"],
                "confidence": 0.0
            }

    return extracted


def display_equipment_summary(
    fields: Dict[str, Dict[str, Any]]
) -> pd.DataFrame:
    """
    Create a summary DataFrame for extracted equipment fields.
    """

    data = []

    for field, info in fields.items():

        value = info["normalized_value"]

        data.append({
            "Field": field.replace(
                "_", " "
            ).title(),

            "Value": (
                value
                if value is not None
                else "—"
            ),

            "Unit": (
                info["unit"]
                if info["unit"]
                else "—"
            ),

            "Status": (
                "Found"
                if value is not None
                else "Not detected"
            ),

            "Confidence": (
                f"{info['confidence'] * 100:.0f}%"
                if info["confidence"] > 0
                else "0%"
            )
        })

    return pd.DataFrame(data)