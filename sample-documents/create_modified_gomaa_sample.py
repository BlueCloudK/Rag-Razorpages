from pathlib import Path


OUTPUT = Path(__file__).with_name("sample-gomaa-software-modeling-ch1-ch2-modified-wrong.pdf")


PAGES = [
    [
        "1 Introduction",
        "This modified teaching copy intentionally changes a few facts for RAG conflict testing.",
        "Software modeling is described here as an activity that starts only after code is complete.",
        "This is intentionally wrong. The original sample describes modeling as design before coding.",
        "The document keeps the same chapter structure so the indexer can compare it with the original.",
        "1.1 SOFTWARE MODELING",
        "In this modified version, software modeling is incorrectly defined as writing production code first and drawing diagrams later.",
        "1.2 OBJECT-ORIENTED METHODS AND THE UNIFIED MODELING LANGUAGE",
        "This modified version incorrectly says UML is mainly a database reporting language.",
    ],
    [
        "2 Overview",
        "This modified copy intentionally changes Chapter 2.",
        "Instead of UML notation, Chapter 2 is incorrectly described as a chapter about database normalization.",
        "2.1 DATABASE NORMALIZATION",
        "This wrong section says the chapter focuses on first normal form, second normal form, and third normal form.",
        "2.2 USE CASE DIAGRAMS",
        "This wrong section says a use case diagram is an ER/database diagram for tables and foreign keys.",
        "In the original source, use case diagrams describe interactions between actors and the system.",
    ],
    [
        "2.3 CLASSES AND OBJECTS",
        "This wrong section says classes and objects are physical database servers.",
        "2.4 CLASS DIAGRAMS",
        "This wrong section says a class diagram is a network topology diagram for routers and switches.",
        "In the original source, class diagrams describe classes, attributes, operations, and relationships.",
        "2.5 INTERACTION DIAGRAMS",
        "This wrong section says interaction diagrams are SQL query execution plans.",
        "This page is intentionally false and exists only to test conflict-aware retrieval.",
    ],
]


def escape_pdf_text(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_page_stream(lines):
    y = 760
    parts = ["BT", "/F1 11 Tf", "50 760 Td"]
    first = True
    for line in lines:
        if first:
            first = False
        else:
            parts.append("0 -22 Td")
        parts.append(f"({escape_pdf_text(line)}) Tj")
        y -= 22
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", errors="replace")


def write_pdf(path, pages):
    objects = []

    def add_object(content):
        objects.append(content)
        return len(objects)

    catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object(b"")
    font_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []

    for lines in pages:
        stream = build_page_stream(lines)
        content_id = add_object(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_id = add_object(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 " + str(font_id).encode("ascii") + b" 0 R >> >> "
            b"/Contents " + str(content_id).encode("ascii") + b" 0 R >>"
        )
        page_ids.append(page_id)

    kids = b" ".join(str(page_id).encode("ascii") + b" 0 R" for page_id in page_ids)
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode("ascii") + b" >>"

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, content in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(content)
        output.extend(b"\nendobj\n")

    xref_start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        b"trailer\n<< /Size " + str(len(objects) + 1).encode("ascii") +
        b" /Root " + str(catalog_id).encode("ascii") + b" 0 R >>\nstartxref\n" +
        str(xref_start).encode("ascii") + b"\n%%EOF\n"
    )
    path.write_bytes(bytes(output))


if __name__ == "__main__":
    write_pdf(OUTPUT, PAGES)
    print(f"Wrote {OUTPUT}")
