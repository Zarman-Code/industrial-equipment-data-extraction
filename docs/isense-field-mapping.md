# i-Sense Field Mapping

This document describes the fields, available values, and workflow required to create an asset in the i-Sense platform.

The objective is to identify the target i-Sense data model and establish the mapping between information extracted from technical equipment PDFs and the fields required to create an i-Sense asset.

---

## 1. Asset Creation Workflow

The current asset creation workflow is:

```text
Assets
  │
  ▼
Create a new asset
  │
  ▼
Choose asset type
  │
  ├── Industrial
  │
  └── Generic
  │
  ▼
Enter asset information
  │
  ▼
Asset Diagram
  │
  ▼
Save
```

The current project focuses on the **Industrial** asset workflow.

---

## 2. Industrial Asset Fields

The Industrial asset creation form currently contains the following fields:

| Field                  | Required | Input Type    | Available Values / Format |
|------------------------|:--------:|---------------|---------------------------|
| Family                 | Yes      | Dropdown      | See Family values         |
| Asset Name             | Yes      | Text          | Free text                 |
| Ref                    | Yes      | Text          | Free text                 |
| Entity                 | Yes      | Dropdown      | Demo Interns              |
| Class                  | Yes      | Dropdown      | AA, A, B, C, AA-Site      |
| Structure              | Yes      | Dropdown      | Rigid, Flexible           |
| Group                  | Yes      | Dropdown      | See Group values          |
| Power                  | Yes      | Input         | Numeric                   |
| Outlier                | Yes      | Numeric input | Numeric                   |
| Measurement Point Type | Yes      | Selection     | Manual, Online            |
| Asset Picture          | No       | File upload   | Image                     |
| Asset Diagram          | Yes      | Diagram/upload| Image/diagram             |


---

# 3. Family

The Family field is represented by:

```html
<select name="family_id">
```

The platform uses numeric IDs internally.

### Relevant family values

| ID | Family                  |
| -: | ----------------------- |
|  1 | Default                 |
| 15 | Groupe Turboalternateur |
| 17 | Motopompe (new)         |
| 25 | Turboalternateur Old    |
| 26 | Turbosoufflante Old     |
| 27 | Motoventilateur (new)   |
| 28 | Agitator (new)          |
| 31 | Broyeurs                |
| 32 | Tube sécheur            |
| 33 | Granulateur             |
| 34 | Concasseur              |
| 35 | Convoyeur               |
| 36 | Compresseur             |
| 37 | Groupe Turbosoufflante  |
| 38 | Pompe à vide            |
| 40 | Banc D'Essai            |

The platform also contains numerous test/development families. These should **not automatically be considered valid production families**.

Examples include:

```text
sub asset 1
test elch
sub asset 2
Test MMS
TEST FAMILY
Turbosouflante test
Family test
Test Family AAQ
Asset familly 23-07
TEST ASSET FAM
aaaaaaa
hhhhhh
...
```

### Automation consideration

The PDF extraction pipeline should not blindly select a Family based only on string similarity.

Instead:

```text
PDF equipment information
        │
        ▼
Equipment classification
        │
        ▼
Allowed family mapping
        │
        ▼
i-Sense family_id
```

For example:

```text
"Motopompe"
     ↓
"Motopompe (new)"
     ↓
family_id = 17
```

The family mapping should eventually be stored in a dedicated configuration file rather than hard-coded throughout the application.

---

# 4. Entity

The Entity field is represented by:

```html
<select name="entity_id">
```

The currently available entity is:

|  ID | Entity       |
| --: | ------------ |
| 123 | Demo Interns |

At the current stage, there is only one available option.

### Automation consideration

The current i-Sense environment provides a single Entity:

- **ID:** `123`
- **Name:** `Demo Interns`

This appears to be the entity associated with the internship/demo environment. 
It should not be treated as information extracted from the equipment PDF.

If the project confirms that all assets created by this application must belong
to this entity, the Entity can be treated as a project-level configuration
parameter.

For example:

```python
ISENSE_ENTITY_ID = 123

---

# 5. Class

The Class field is represented by:

```html
<select name="class_id">
```

Available values:

| ID | Class   |
| -: | ------- |
|  5 | AA-Site |
|  1 | AA      |
|  2 | A       |
|  3 | B       |
|  4 | C       |

### Automation consideration

The Class value should only be assigned automatically if the required information can be determined from the PDF.

The PDF should first be analyzed to determine whether it contains:

- an explicit Class value;
- information that can be used to derive the Class;
- or no information related to Class.

If the Class cannot be determined from the PDF, the application should not guess a value. Instead, the field should be flagged for manual completion or the asset creation should be prevented until a valid value is provided.

---

# 6. Structure

The Structure field is represented by:

```html
<select name="structure">
```

Available values:

| ID | Structure |
| -: | --------- |
|  1 | Rigid     |
|  2 | Flexible  |

This appears to describe a structural/mechanical characteristic rather than an equipment category.

### Automation consideration

The source PDF should be checked to determine whether the equipment documentation explicitly contains this information.

If it does not, this value should probably come from predefined business rules or user configuration rather than being guessed by the extraction model.

---

# 7. Group

The Group field is represented by:

```html
<select name="group_id">
```

Available values:

| ID | Group           |
| -: | --------------- |
|  1 | Groupe I F P3   |
|  2 | Broyeurs        |
|  3 | Groupe I F P2   |
|  4 | Groupe I F P1   |
|  5 | Groupe I R P1   |
|  6 | Groupe I R P2   |
|  7 | Groupe I R P3   |
|  8 | Groupe II F P1  |
|  9 | Groupe II F P2  |
| 10 | Groupe II F P3  |
| 11 | Groupe II R P1  |
| 12 | Groupe II R P2  |
| 13 | Groupe II R P3  |
| 14 | Groupe III F P1 |
| 15 | Groupe III F P2 |
| 16 | Groupe III F P3 |
| 17 | Groupe III R P1 |
| 18 | Groupe III R P2 |
| 19 | Groupe III R P3 |
| 20 | Groupe IV F P1  |
| 21 | Groupe IV F P2  |
| 22 | Groupe IV F P3  |
| 24 | Groupe IV R P2  |
| 25 | Groupe IV R P3  |
| 26 | GTA             |
| 27 | SALLE GROUP     |
| 28 | arwa group      |

### Automation consideration

The Group is likely to be determined from equipment/site organization rather than directly from a generic equipment description.

This field therefore requires investigation of the source PDFs and existing i-Sense assets before defining an automatic mapping.

---

# 8. Asset Name

The Asset Name field is mandatory and accepts free text.

The field is represented in the interface as:

```html
<input name="name" type="text">
```

The value should likely be extracted from the equipment designation/name in the source PDF.

Normalization may be required to handle:

* capitalization;
* extra spaces;
* abbreviations;
* punctuation;
* inconsistent naming conventions.

---

# 9. Reference

The Ref field is mandatory and accepts free text.

The field is represented as:

```html
<input name="ref" type="text">
```

Possible representations in the PDF may include:

* equipment reference;
* equipment tag;
* asset number;
* identification number;
* technical reference.

### Automation consideration

If a clear equipment reference is present in the PDF, it can be extracted and entered directly into the Ref field.

For example:

```text
PDF:
    Equipment reference = PMP-101

        ↓

Extracted value:
    PMP-101

        ↓

i-Sense:
    Ref = PMP-101
```

The application should not invent or generate a reference if no valid reference can be identified in the PDF.

If multiple possible identifiers are found, the application should flag the field for validation rather than automatically choosing one without an established rule.

---

# 10. Power

The Power field is mandatory and accepts free text.

The field is represented as:

```html
<input name="powerRange" type="text">
```

Although the field is related to power, the HTML indicates that i-Sense accepts the value as text, rather than explicitly requiring a numeric input.

Automation consideration

The source PDF should be analyzed to determine:

* whether power is provided;
* how it is represented;
* which unit is used;
* whether multiple power values are provided;
* whether a conversion is necessary.

Example normalization:

```text
PDF:
    Power = 15 kW

        ↓

Normalized value:
    15

        ↓

i-Sense:
    Power = 15
```

If the PDF contains:

```text
15000 W
```

the extraction layer may need to convert:

```text
15000 W → 15 kW
```

---

# 11. Outlier

The Outlier field is mandatory and accepts a numeric value.

The field is represented as:

```html
<input name="outlier_detection" type="number">
```

The interface placeholder describes the value as:

```
Enter outlier threshold...
```

This indicates that the field represents an outlier detection threshold, but the meaning and appropriate value have not yet been established.

### Automation consideration

Since the PDFs are the only source of equipment information, the PDF should be analyzed to determine whether it contains a value corresponding to this threshold.

At this stage, we do not assume that the threshold can be extracted from the PDF.

Possible situations are:

```text
PDF contains an explicit threshold
        ↓
Extract and validate the value
```

or:

```text
PDF does not contain a threshold
        ↓
Cannot determine automatically
        ↓
Manual input / project-defined value
```

The application should not invent an outlier threshold.

Before automating this field, the project should establish:

* what the threshold represents;
* its unit, if applicable;
* whether it is equipment-specific;
* whether it is explicitly documented in the source PDFs;
* whether a project-defined default exists.

Until this is established, the Outlier field should be treated as undetermined rather than automatically populated.

---

# 12. Measurement Point Type

The Measurement Point Type field is mandatory.

The interface currently provides two options:

```text
Manual
Online
```

The HTML indicates that:

``` text
Manual → selected by default
Online → currently disabled
```

The relevant form values are:

```text
Manual → is_manual = 1
Online → is_manual = 0
```

### Automation consideration

At the current stage, Manual is the only enabled option in the observed i-Sense environment.

Therefore, the automation should treat this as a platform/environment setting rather than attempt to classify the equipment automatically.

---

# 13. Asset Picture

The interface provides an Asset Picture section with:

* 3D
* Asset Picture
* image upload

### Automation consideration

If an equipment image is available in the PDF, image extraction could potentially be added to the pipeline:

```text
PDF
 │
 ├── Extract text
 │
 └── Extract equipment image
             │
             ▼
        i-Sense Asset
```

Image extraction is currently considered secondary to structured data extraction.

---

# 14. Asset Diagram

Asset Diagram is mandatory for the assets being created.

After the main asset information is entered, i-Sense provides an Asset Diagram step.

The interface allows:

* creating a new diagram;
* uploading a diagram;
* saving the asset.

### Automation consideration

The PDFs should first be examined to determine whether relevant diagrams are available.

If suitable diagrams exist, they could potentially be extracted and associated with the asset.

---

# 15. Source-to-Target Architecture

The project should maintain an intermediate representation between the PDF and i-Sense.

```text
                 SOURCE
                   │
                   ▼
            Technical PDF
                   │
                   ▼
          PDF Information
             Extraction
                   │
                   ▼
        ┌─────────────────────┐
        │ Internal Equipment  │
        │       Schema        │
        └──────────┬──────────┘
                   │
                   ▼
          Normalization
                   │
                   ▼
             Validation
                   │
                   ▼
        i-Sense-specific fields
                   │
                   ▼
          User Confirmation
                   │
                   ▼
              i-Sense
```

The Internal Equipment Schema is important because it represents what was actually extracted from the PDF.

For example:

```JSON
{
    "asset_name": "...",
    "reference": "...",
    "power": "...",
    "manufacturer": "...",
    "model": "..."
}
```

Then the i-Sense integration can transform this information into the format required by the platform.

This prevents the PDF extraction code from being tightly coupled to the i-Sense interface.

---

# 17. Next Investigation Steps

The following information should be collected before implementing the automated data-entry process:

### i-Sense exploration

- [x] Identify Industrial asset type
- [x] Identify mandatory asset fields
- [x] Identify Family values and IDs
- [x] Identify Entity values and IDs
- [x] Identify Class values and IDs
- [x] Identify Structure values and IDs
- [x] Identify Group values and IDs
- [x] Identify Measurement Point Type options
- [x] Determine that Online is currently disabled

### PDF analysis

- [ ] Identify equipment name/designation
- [ ] Identify equipment reference/tag
- [ ] Identify equipment type/category
- [ ] Identify power and unit
- [ ] Identify classification information
- [ ] Identify structure-related information
- [ ] Identify group/site information
- [ ] Identify outlier-related information
- [ ] Identify monitoring information
- [ ] Identify equipment images
- [ ] Identify equipment diagrams

### Mapping and validation

- [ ] Compare PDF fields with i-Sense fields
- [ ] Define normalization rules
- [ ] Define valid mappings
- [ ] Identify fields requiring manual validation
- [ ] Define missing-value handling
- [ ] Define project-level configuration

### i-Sense integration

- [ ] Explore existing asset editing
- [ ] Investigate Export Data
- [ ] Investigate import capabilities
- [ ] Investigate API availability
- [ ] Confirm the correct demo/test environment
- [ ] Test asset creation manually before automation
* [ ] Compare i-Sense fields with the two source PDFs

---

# 18. Important Automation Principle

The application should distinguish between information **extracted from the
source PDFs** and values that are **required by the i-Sense platform but may
not be available in the PDFs**.

The PDFs are the only source of equipment information for this project.

Therefore, every i-Sense field should be classified into one of three cases:

### 1. Information available in the PDF

```text
PDF
 │
 ▼
Extract
 │
 ▼
Normalize
 │
 ▼
i-Sense field
```

### 2. Information derivable from the PDF

```text
PDF information
       │
       ▼
Classification / mapping rule
       │
       ▼
i-Sense value
```

This should only be done when an explicit and validated rule exists.

### 3. Information not available in the PDF

```text
PDF
 │
 └── Information unavailable
             │
             ▼
       Manual input
       or confirmed
       configuration
```

The system should never invent a value simply because an i-Sense field is
mandatory.

Unknown or ambiguous values should be flagged for validation before the asset
is submitted to i-Sense.