import time
from pathlib import Path
from typing import Dict, Any, Union

import numpy as np
import pandas as pd

from .preprocessing import load_input_document, preprocess_image


class OCRPipeline:

    def __init__(self):
        """
        Initialize the OCR components.
        """

        # These will use the PaddleOCR models from your notebook.
        from paddleocr import (
            LayoutDetection,
            TableStructureRecognition,
            TextRecognition
        )

        self.layout_engine = LayoutDetection()
        self.structure_engine = TableStructureRecognition()
        self.rec_engine = TextRecognition()


    def detect_tables(self, image: np.ndarray):
        """
        Detect table regions in the document.
        """

        results = list(self.layout_engine.predict(image))

        tables = []

        for result in results:

            data = result if isinstance(result, dict) else result

            # Keep only table regions
            # Exact result parsing can be adapted to your PaddleOCR output.
            if isinstance(data, dict):
                boxes = data.get("boxes", [])

                for box in boxes:
                    if box.get("label", "").lower() == "table":
                        tables.append(box)

        return tables


    def recognize_table_structure(
        self,
        table_image: np.ndarray
    ) -> Dict[str, Any]:
        """
        Detect table cells and recover table structure.
        """

        results = list(
            self.structure_engine.predict(table_image)
        )

        if not results:
            return {
                "cells": [],
                "structure": [],
                "structure_score": 0.0,
                "num_cells": 0
            }

        result = results[0]

        raw_bboxes = result.get("bbox", [])
        structure = result.get("structure", [])
        score = float(
            result.get("structure_score", 0.0)
        )

        h, w = table_image.shape[:2]

        cells = []

        for i, box in enumerate(raw_bboxes):

            pts = np.array(box).reshape(-1, 2)

            xmin = max(0, int(np.min(pts[:, 0])))
            ymin = max(0, int(np.min(pts[:, 1])))
            xmax = min(w, int(np.max(pts[:, 0])))
            ymax = min(h, int(np.max(pts[:, 1])))

            cells.append({
                "cell_idx": i,
                "bbox": [xmin, ymin, xmax, ymax],
                "polygon": pts.tolist(),
                "cx": (xmin + xmax) / 2,
                "cy": (ymin + ymax) / 2,
                "width": xmax - xmin,
                "height": ymax - ymin
            })

        return {
            "cells": cells,
            "structure": structure,
            "structure_score": score,
            "num_cells": len(cells)
        }


    def ocr_cell(
        self,
        image: np.ndarray,
        bbox,
        padding: int = 3
    ) -> Dict[str, Any]:
        """
        Perform OCR on one table cell.
        """

        h, w = image.shape[:2]

        x1 = max(0, bbox[0] - padding)
        y1 = max(0, bbox[1] - padding)
        x2 = min(w, bbox[2] + padding)
        y2 = min(h, bbox[3] + padding)

        crop = image[y1:y2, x1:x2]

        if crop.size == 0:
            return {
                "text": "",
                "score": 0.0
            }

        try:
            results = list(
                self.rec_engine.predict(crop)
            )

            if results:

                result = results[0]

                return {
                    "text": result.get(
                        "rec_text", ""
                    ).strip(),

                    "score": float(
                        result.get(
                            "rec_score", 0.0
                        )
                    )
                }

        except Exception:
            pass

        return {
            "text": "",
            "score": 0.0
        }


    def ocr_cells(
        self,
        image: np.ndarray,
        cells
    ):
        """
        Perform OCR on all detected cells.
        """

        results = []

        for cell in cells:

            ocr_result = self.ocr_cell(
                image,
                cell["bbox"]
            )

            cell_result = cell.copy()

            cell_result["text"] = ocr_result["text"]
            cell_result["score"] = ocr_result["score"]

            results.append(cell_result)

        return results


    def reconstruct_table(
        self,
        cells
    ) -> pd.DataFrame:
        """
        Reconstruct a table from cell positions.
        """

        if not cells:
            return pd.DataFrame()

        # Sort cells by Y then X
        cells = sorted(
            cells,
            key=lambda c: (c["cy"], c["cx"])
        )

        rows = []
        current_row = [cells[0]]
        current_y = cells[0]["cy"]

        median_height = np.median(
            [c["height"] for c in cells]
        )

        tolerance = 0.5 * median_height

        for cell in cells[1:]:

            if abs(cell["cy"] - current_y) <= tolerance:

                current_row.append(cell)

                current_y = np.mean(
                    [c["cy"] for c in current_row]
                )

            else:

                rows.append(
                    sorted(
                        current_row,
                        key=lambda c: c["cx"]
                    )
                )

                current_row = [cell]
                current_y = cell["cy"]

        rows.append(
            sorted(
                current_row,
                key=lambda c: c["cx"]
            )
        )

        table = [
            [cell["text"] for cell in row]
            for row in rows
        ]

        if not table:
            return pd.DataFrame()

        max_columns = max(
            len(row) for row in table
        )

        table = [
            row + [""] * (max_columns - len(row))
            for row in table
        ]

        columns = [
            value.strip()
            if value.strip()
            else f"Col_{i + 1}"
            for i, value in enumerate(table[0])
        ]

        return pd.DataFrame(
            table[1:],
            columns=columns
        )


    def process(
        self,
        file_path: Union[str, Path],
        page_number: int = 0,
        dpi: int = 300
    ) -> Dict[str, Any]:

        start_time = time.time()

        # 1. Load document
        image, info = load_input_document(
            file_path,
            page_number=page_number,
            dpi=dpi
        )

        print(
            f"[1/5] Loaded: {info}"
        )

        # 2. Preprocessing
        image = preprocess_image(image)

        print("[2/5] Preprocessing completed")

        # 3. Table detection
        tables = self.detect_tables(image)

        print(
            f"[3/5] Tables detected: {len(tables)}"
        )

        if not tables:
            return {
                "image": image,
                "tables": [],
                "cells": [],
                "dataframe": pd.DataFrame(),
                "processing_time": time.time() - start_time
            }

        # First / dominant table
        table = tables[0]

        coordinate = table.get(
            "coordinate",
            table.get("bbox")
        )

        x1, y1, x2, y2 = map(
            int,
            coordinate
        )

        table_image = image[
            y1:y2,
            x1:x2
        ]

        # 4. Table structure
        structure = self.recognize_table_structure(
            table_image
        )

        print(
            f"[4/5] Cells detected: "
            f"{structure['num_cells']}"
        )

        # Convert cell coordinates
        for cell in structure["cells"]:

            cell["bbox"][0] += x1
            cell["bbox"][1] += y1
            cell["bbox"][2] += x1
            cell["bbox"][3] += y1

            cell["cx"] += x1
            cell["cy"] += y1

        # 5. OCR + reconstruction
        cells = self.ocr_cells(
            image,
            structure["cells"]
        )

        dataframe = self.reconstruct_table(
            cells
        )

        print(
            f"[5/5] OCR completed: "
            f"{len(cells)} cells"
        )

        return {
            "image": image,
            "tables": tables,
            "cells": cells,
            "structure": structure,
            "dataframe": dataframe,
            "processing_time": (
                time.time() - start_time
            )
        }


# Create one reusable pipeline
ocr_pipeline = OCRPipeline()