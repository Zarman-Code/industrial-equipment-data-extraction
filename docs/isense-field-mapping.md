# i-Sense Field Mapping

This document describes the workflow and fields required to create an asset in the i-Sense platform.

The objective is to identify the information required by i-Sense and establish how this information can be obtained and transformed from the source equipment PDFs.

---

## 1. Asset Creation Workflow

The asset creation process currently follows these steps:

```text
Assets
  │
  ▼
Create a new asset
  │
  ▼
Choose the asset type
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

For this project, the **Industrial** asset type is the primary workflow to investigate.

---

## 2. Asset Information Form

The Industrial asset creation form contains the following fields:

| Field                  | Required | Type         | PDF Source       | Transformation / Notes                             |
| ---------------------- | :------: | ------------ | ---------------- | -------------------------------------------------- |
| Family                 |    Yes   | Dropdown     | To be determined | Must identify the corresponding family             |
| Asset Name             |    Yes   | Text         | To be determined | May correspond to equipment designation/name       |
| Ref                    |    Yes   | Text         | To be determined | Equipment reference may be available in the PDF    |
| Entity                 |    Yes   | Dropdown     | To be determined | Requires mapping to an i-Sense entity              |
| Class                  |    Yes   | Dropdown     | To be determined | Requires mapping to an i-Sense class               |
| Structure              |    Yes   | Dropdown     | To be determined | Requires mapping to an i-Sense structure           |
| Group                  |    Yes   | Dropdown     | To be determined | Requires mapping to an i-Sense group               |
| Power                  |    Yes   | Numeric/Text | To be determined | Unit and expected format need to be investigated   |
| Outlier                |    Yes   | Numeric      | To be determined | Outlier threshold; source needs to be investigated |
| Measurement point type |    Yes   | Selection    | To be determined | Manual or Online                                   |
| Asset Picture          |    No*   | Image upload | To be determined | May require an image from the source documentation |

---

## 3. Asset Type

When selecting **Create a new asset**, i-Sense first asks the user to choose an asset type:

* Industrial
* Generic

The current project focuses on **Industrial assets**.

The Generic asset workflow should be investigated later if the source documents contain assets that cannot be represented using the Industrial workflow.

---

## 4. Asset Picture

The asset creation form provides an **Asset Picture** section.

The interface provides options for:

* 3D
* Asset Picture
* Image upload

The project should determine whether equipment images are available in the source PDFs and whether they should be extracted and uploaded to i-Sense.

This feature is considered secondary to the extraction of structured equipment information.

---

## 5. Asset Diagram

After entering the asset information, i-Sense provides an **Asset Diagram** step.

The interface currently allows the user to:

* create a new diagram;
* upload a diagram;
* save the asset without necessarily creating a diagram, depending on the platform workflow.

The relationship between equipment information in the PDF and the Asset Diagram should be investigated separately.

At this stage, diagram generation is **outside the primary scope** of the PDF-to-i-Sense data-entry pipeline.

---

## 6. PDF → i-Sense Mapping

The final mapping will connect three representations of the same equipment:

```text
Source PDF
    │
    ▼
Extracted Equipment Data
    │
    ▼
Normalized Internal Schema
    │
    ▼
i-Sense Fields
```

For example:

```text
PDF
│
├── Equipment designation
├── Reference
├── Manufacturer
├── Power
└── Location
        │
        ▼
Internal equipment schema
        │
        ▼
i-Sense
│
├── Asset Name
├── Ref
├── Power
├── Entity
├── Structure
└── Group
```

The exact mapping will be determined after examining the contents of the source PDFs and the available values in the i-Sense dropdown fields.

---

## 7. Fields Requiring Further Investigation

The following fields require additional exploration:

### Family

Determine:

* available family values;
* whether the family can be inferred from the PDF;
* whether it is fixed for a particular equipment category.

### Entity

Determine:

* available entities;
* whether an entity corresponds to a physical site, organization, or another concept;
* whether the value can be extracted from the PDF.

### Class

Determine:

* available classes;
* whether the class corresponds to the equipment type;
* whether automatic mapping is possible.

### Structure

Determine:

* available structures;
* relationship with the equipment location or hierarchy.

### Group

Determine:

* available groups;
* whether the group can be inferred from the source document.

### Power

Determine:

* expected unit;
* accepted format;
* whether decimal values are accepted;
* whether the PDF provides the same unit.

### Outlier

Determine:

* what the threshold represents;
* its unit;
* how the value should be calculated or obtained;
* whether it is available in the source documentation.

### Measurement Point Type

The current interface provides two options:

* Manual
* Online

The appropriate value should be determined from the equipment and its monitoring configuration.

---

## 8. Information Still Needed

Before implementing the automated data-entry process, the following information should be documented:

* [ ] Available Family values
* [ ] Available Entity values
* [ ] Available Class values
* [ ] Available Structure values
* [ ] Available Group values
* [ ] Power unit and format
* [ ] Meaning and unit of Outlier
* [ ] Conditions for selecting Manual vs Online
* [ ] Whether Asset Picture is required
* [ ] Whether Asset Diagram is required
* [ ] Whether existing assets can be edited automatically
* [ ] Whether assets can be imported in bulk
* [ ] Whether i-Sense provides an API
* [ ] Whether the platform provides an export/import mechanism

---

## 9. Automation Target

The final automation should aim to transform:

```text
Technical PDF
      │
      ▼
Equipment Information Extraction
      │
      ▼
Data Normalization
      │
      ▼
Data Validation
      │
      ▼
i-Sense Field Mapping
      │
      ▼
Create Industrial Asset
      │
      ▼
Verify Created Asset
```

The automation should not directly submit unvalidated information. Extracted values should first be checked against the expected i-Sense fields and allowed values.
