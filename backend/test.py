from pathlib import Path
import json

from .pipeline import run_pipeline


PDF_PATH = Path("data/raw/AUSTCOLD.pdf")


def main():
    print(f"Testing PDF: {PDF_PATH}")

    if not PDF_PATH.exists():
        raise FileNotFoundError(
            f"Test PDF not found: {PDF_PATH}"
        )

    result = run_pipeline(
        pdf_path=PDF_PATH,
        ocr_pipeline=None,
        max_workers=4,
        dpi=300,
        min_text_length=50,
    )

    # Stage 1
    stage_1 = result["stage_1"]

    print("\n----------- STAGE 1 -----------")
    print(f"Method: {stage_1['path']}")
    print(f"Candidates: {stage_1['total_candidates']}")

    for section in stage_1["candidates"]:
        print(
            f"  [{section['section_id']}] "
            f"{section['title']} "
            f"(pages {section['start_page']}-{section['end_page']})"
        )

    # Stage 2
    stage_2 = result["stage_2"]

    print("\n----------- STAGE 2 -----------")
    print(
        f"Selected: "
        f"{len(stage_2['selected_section_ids'])}"
    )

    print("Selected section IDs:")

    for section_id in stage_2["selected_section_ids"]:
        print(f"  - {section_id}")

    # Stage 3
    stage_3 = result["stage_3"]

    print("\n----------- STAGE 3 -----------")
    print(
        f"Sections processed: "
        f"{stage_3['total_sections']}"
    )

    for item in stage_3["results"]:
        print(
            f"\n  {item.get('section_id')} "
            f"- {item.get('title')}"
        )

        if item.get("error"):
            print(f"  ERROR: {item['error']}")
        else:
            print(
                f"  Extraction methods: "
                f"{item.get('extraction_methods')}"
            )

            print("  LLM result:")
            print(
                json.dumps(
                    item.get("llm_result"),
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

    # Optional full JSON
    output_path = Path("pipeline_result.json")

    output_path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        f"\nFull result saved to: {output_path}"
    )


if __name__ == "__main__":
    main()