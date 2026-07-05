from __future__ import annotations

import logging
from typing import Any

import streamlit as st
from Bio.Blast import NCBIWWW, NCBIXML
from Bio.Data import CodonTable
from Bio.Seq import Seq
from Bio.SeqUtils import seq3
from Bio.SeqUtils.ProtParam import ProteinAnalysis


# ============================================================
# CONFIGURATION
# ============================================================

LOGGER = logging.getLogger(__name__)

VALID_DNA_BASES = frozenset({"A", "T", "G", "C"})

VALID_PROTEIN_SYMBOLS = frozenset(
    {
        "A", "C", "D", "E", "F",
        "G", "H", "I", "K", "L",
        "M", "N", "P", "Q", "R",
        "S", "T", "V", "W", "Y"
    }
)


# ============================================================
# GENETIC CODE HELPERS
# ============================================================

def get_genetic_code_table(table: int = 1):
    """
    Returns a valid Biopython DNA codon table.

    Parameters
    ----------
    table:
        NCBI genetic code table number.

    Returns
    -------
    Bio.Data.CodonTable.CodonTable
        The selected codon table.

    Raises
    ------
    ValueError
        If the table number is invalid.
    """
    try:
        table_number = int(table)
        return CodonTable.unambiguous_dna_by_id[table_number]

    except (TypeError, ValueError, KeyError) as error:
        raise ValueError(
            f"Unsupported genetic code table: {table}."
        ) from error


def get_genetic_code_name(table: int = 1) -> str:
    """
    Returns the descriptive name of a genetic code table.
    """
    genetic_code = get_genetic_code_table(table)

    if genetic_code.names:
        return genetic_code.names[0]

    return f"Genetic Code Table {table}"


# ============================================================
# DNA CLEANING AND VALIDATION
# ============================================================

def get_cleaning_report(sequence: str | None) -> dict[str, Any]:
    """
    Cleans a DNA sequence while recording everything removed.

    The function:
    - removes FASTA header lines;
    - removes whitespace;
    - removes digits;
    - removes formatting symbols;
    - records invalid alphabetic characters;
    - preserves only A, T, G, and C in the cleaned sequence.

    Invalid biological letters are reported so that the interface
    can warn the student instead of silently accepting them.

    Parameters
    ----------
    sequence:
        Original DNA input.

    Returns
    -------
    dict
        Detailed sequence-cleaning information.
    """
    original_sequence = str(sequence or "")

    lines = original_sequence.splitlines()

    fasta_headers = []
    sequence_lines = []

    for line in lines:
        if line.strip().startswith(">"):
            fasta_headers.append(line.strip())
        else:
            sequence_lines.append(line)

    sequence_body = "\n".join(sequence_lines)

    cleaned_characters = []
    invalid_letter_details = []

    whitespace_removed = 0
    digits_removed = 0
    symbols_removed = 0
    invalid_letters_removed = 0

    for position, character in enumerate(sequence_body, start=1):
        uppercase_character = character.upper()

        if uppercase_character in VALID_DNA_BASES:
            cleaned_characters.append(uppercase_character)

        elif character.isspace():
            whitespace_removed += 1

        elif character.isdigit():
            digits_removed += 1

        elif character.isalpha():
            invalid_letters_removed += 1

            invalid_letter_details.append(
                {
                    "character": uppercase_character,
                    "position": position
                }
            )

        else:
            symbols_removed += 1

    cleaned_sequence = "".join(cleaned_characters)

    unique_invalid_letters = sorted(
        {
            item["character"]
            for item in invalid_letter_details
        }
    )

    incomplete_base_count = len(cleaned_sequence) % 3
    complete_codon_count = len(cleaned_sequence) // 3

    total_removed = (
        whitespace_removed
        + digits_removed
        + symbols_removed
        + invalid_letters_removed
    )

    return {
        "original_sequence": original_sequence,
        "sequence_without_fasta_header": sequence_body,
        "cleaned_sequence": cleaned_sequence,

        "original_length": len(original_sequence),
        "cleaned_length": len(cleaned_sequence),

        "fasta_headers_removed": len(fasta_headers),
        "fasta_header_content": fasta_headers,

        "whitespace_removed": whitespace_removed,
        "digits_removed": digits_removed,
        "symbols_removed": symbols_removed,
        "invalid_letters_removed": invalid_letters_removed,
        "total_characters_removed": total_removed,

        "invalid_letters": unique_invalid_letters,
        "invalid_letter_details": invalid_letter_details,

        "complete_codon_count": complete_codon_count,
        "incomplete_base_count": incomplete_base_count,

        "has_invalid_letters": bool(unique_invalid_letters),
        "is_empty_after_cleaning": not bool(cleaned_sequence)
    }


def clean_dna(sequence: str | None) -> str:
    """
    Returns a cleaned uppercase DNA sequence containing only A, T, G, and C.

    This function is kept for compatibility with the existing application.
    Use get_cleaning_report() when the interface must display what was removed.
    """
    return get_cleaning_report(sequence)["cleaned_sequence"]


def validate_dna(sequence: str | None) -> bool:
    """
    Checks whether a sequence is non-empty and contains only A, T, G, and C.

    The function does not clean the sequence automatically.
    """
    if not sequence:
        return False

    normalized_sequence = str(sequence).upper()

    return all(
        base in VALID_DNA_BASES
        for base in normalized_sequence
    )


def get_validation_result(sequence: str | None) -> dict[str, Any]:
    """
    Returns a detailed validation result suitable for the user interface.
    """
    if not sequence:
        return {
            "valid": False,
            "message": "No DNA sequence was provided.",
            "invalid_characters": []
        }

    normalized_sequence = str(sequence).upper()

    invalid_characters = sorted(
        {
            character
            for character in normalized_sequence
            if character not in VALID_DNA_BASES
        }
    )

    if invalid_characters:
        return {
            "valid": False,
            "message": (
                "The DNA sequence contains unsupported characters: "
                + ", ".join(invalid_characters)
            ),
            "invalid_characters": invalid_characters
        }

    return {
        "valid": True,
        "message": "The DNA sequence contains only valid nucleotide bases.",
        "invalid_characters": []
    }


# ============================================================
# CODON MAPPING AND TRANSLATION
# ============================================================

def split_into_codons(sequence: str | None) -> dict[str, Any]:
    """
    Splits a valid DNA sequence into complete codons and remaining bases.
    """
    normalized_sequence = str(sequence or "").upper()

    if normalized_sequence and not validate_dna(normalized_sequence):
        raise ValueError(
            "The DNA sequence contains characters other than A, T, G, and C."
        )

    complete_length = len(normalized_sequence) - (
        len(normalized_sequence) % 3
    )

    codons = [
        normalized_sequence[index:index + 3]
        for index in range(0, complete_length, 3)
    ]

    remainder = normalized_sequence[complete_length:]

    return {
        "codons": codons,
        "remainder": remainder,
        "complete_length": complete_length,
        "complete_codon_count": len(codons),
        "incomplete_base_count": len(remainder)
    }


def build_codon_mapping(
    sequence: str | None,
    table: int = 1
) -> list[dict[str, Any]]:
    """
    Builds a student-friendly codon-to-amino-acid mapping.

    Each row contains:
    - codon number;
    - nucleotide positions;
    - DNA codon;
    - amino-acid symbol;
    - three-letter amino-acid name;
    - biological role.

    Incomplete final bases are included as a separate row.
    """
    normalized_sequence = str(sequence or "").upper()

    if not normalized_sequence:
        return []

    if not validate_dna(normalized_sequence):
        raise ValueError(
            "Codon mapping requires a DNA sequence containing only "
            "A, T, G, and C."
        )

    genetic_code = get_genetic_code_table(table)
    codon_information = split_into_codons(normalized_sequence)

    mapping = []

    for codon_index, codon in enumerate(
        codon_information["codons"],
        start=1
    ):
        nucleotide_start = ((codon_index - 1) * 3) + 1
        nucleotide_end = nucleotide_start + 2

        amino_acid_symbol = str(
            Seq(codon).translate(
                table=int(table),
                to_stop=False
            )
        )

        if codon in genetic_code.stop_codons:
            amino_acid_name = "Stop"
            biological_role = "Stop codon"

        elif codon in genetic_code.start_codons:
            amino_acid_name = seq3(amino_acid_symbol)
            biological_role = "Start codon"

        else:
            amino_acid_name = seq3(amino_acid_symbol)
            biological_role = "Amino acid codon"

        mapping.append(
            {
                "Codon Number": codon_index,
                "Nucleotide Position": (
                    f"{nucleotide_start}-{nucleotide_end}"
                ),
                "Codon": codon,
                "Amino Acid Symbol": amino_acid_symbol,
                "Amino Acid Name": amino_acid_name,
                "Role": biological_role
            }
        )

    remainder = codon_information["remainder"]

    if remainder:
        remainder_start = (
            codon_information["complete_length"] + 1
        )

        remainder_end = len(normalized_sequence)

        mapping.append(
            {
                "Codon Number": (
                    codon_information["complete_codon_count"] + 1
                ),
                "Nucleotide Position": (
                    f"{remainder_start}-{remainder_end}"
                ),
                "Codon": remainder,
                "Amino Acid Symbol": "-",
                "Amino Acid Name": "Incomplete codon",
                "Role": "Not translated"
            }
        )

    return mapping


def translate_dna(
    sequence: str | None,
    table: int = 1,
    to_stop: bool = True
) -> str:
    """
    Translates a DNA sequence into a protein sequence.

    Only complete three-base codons are translated. Any remaining
    one or two bases at the end are excluded from translation and
    should be reported separately in the interface.

    Parameters
    ----------
    sequence:
        Valid DNA sequence.
    table:
        NCBI genetic code table number.
    to_stop:
        When True, translation stops at the first stop codon.

    Returns
    -------
    str
        Translated protein sequence.

    Raises
    ------
    ValueError
        If the sequence is empty, invalid, or the table is unsupported.
    """
    normalized_sequence = str(sequence or "").upper()

    if not normalized_sequence:
        return ""

    if not validate_dna(normalized_sequence):
        raise ValueError(
            "Translation requires a DNA sequence containing only "
            "A, T, G, and C."
        )

    get_genetic_code_table(table)

    codon_information = split_into_codons(normalized_sequence)

    complete_sequence = normalized_sequence[
        :codon_information["complete_length"]
    ]

    if len(complete_sequence) < 3:
        return ""

    translated_protein = Seq(complete_sequence).translate(
        table=int(table),
        to_stop=to_stop
    )

    return str(translated_protein)


# ============================================================
# PROTEIN ANALYSIS
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_protein_details(
    protein_seq: str | None
) -> dict[str, Any] | None:
    """
    Calculates protein properties and provides student-friendly explanations.
    """
    normalized_protein = "".join(
        str(protein_seq or "").split()
    ).upper()

    normalized_protein = normalized_protein.replace("*", "")

    if not normalized_protein:
        return None

    invalid_symbols = sorted(
        {
            symbol
            for symbol in normalized_protein
            if symbol not in VALID_PROTEIN_SYMBOLS
        }
    )

    if invalid_symbols:
        raise ValueError(
            "The protein sequence contains unsupported amino-acid "
            f"symbols: {', '.join(invalid_symbols)}"
        )

    analysed_sequence = ProteinAnalysis(normalized_protein)

    molecular_weight = round(
        analysed_sequence.molecular_weight(),
        2
    )

    isoelectric_point = round(
        analysed_sequence.isoelectric_point(),
        2
    )

    instability_index = round(
        analysed_sequence.instability_index(),
        2
    )

    aromaticity = round(
        analysed_sequence.aromaticity(),
        4
    )

    gravy = round(
        analysed_sequence.gravy(),
        4
    )

    if instability_index < 40:
        stability_classification = "Potentially stable"

        stability_interpretation = (
            "The instability index is below 40. This suggests that "
            "the translated protein may be stable under laboratory "
            "conditions."
        )

    else:
        stability_classification = "Potentially unstable"

        stability_interpretation = (
            "The instability index is 40 or higher. This suggests "
            "that the translated protein may be unstable under "
            "laboratory conditions."
        )

    if gravy > 0:
        gravy_interpretation = (
            "The positive GRAVY value suggests that the protein has "
            "a relatively hydrophobic character."
        )

    elif gravy < 0:
        gravy_interpretation = (
            "The negative GRAVY value suggests that the protein has "
            "a relatively hydrophilic character."
        )

    else:
        gravy_interpretation = (
            "The GRAVY value is approximately zero, suggesting a "
            "balance between hydrophobic and hydrophilic residues."
        )

    return {
        "sequence_length": {
            "value": len(normalized_protein),
            "unit": "amino acids",
            "desc": (
                "The number of amino-acid residues in the translated "
                "protein sequence."
            )
        },

        "molecular_weight": {
            "value": molecular_weight,
            "unit": "Da",
            "desc": (
                "The estimated mass of the protein. Molecular weight "
                "can support protein identification during laboratory "
                "procedures such as SDS-PAGE."
            )
        },

        "isoelectric_point": {
            "value": isoelectric_point,
            "unit": "pH",
            "desc": (
                "The estimated pH at which the protein has no overall "
                "electrical charge. This value is useful when planning "
                "protein separation and purification procedures."
            ),
            "interpretation": (
                f"The protein is predicted to have a net charge of "
                f"approximately zero at pH {isoelectric_point}."
            )
        },

        "instability_index": {
            "value": instability_index,
            "classification": stability_classification,
            "desc": (
                "An estimate of protein stability under laboratory "
                "conditions. Values below 40 are generally interpreted "
                "as potentially stable."
            ),
            "interpretation": stability_interpretation
        },

        "aromaticity": {
            "value": aromaticity,
            "desc": (
                "The relative frequency of aromatic amino acids "
                "phenylalanine, tryptophan, and tyrosine."
            )
        },

        "gravy": {
            "value": gravy,
            "desc": (
                "The Grand Average of Hydropathy estimates the overall "
                "hydrophobic or hydrophilic character of the protein."
            ),
            "interpretation": gravy_interpretation
        }
    }


# ============================================================
# OPEN READING FRAME IDENTIFICATION
# ============================================================

def find_orfs(
    sequence: str | None,
    table: int = 1,
    include_reverse_strand: bool = False
) -> list[dict[str, Any]]:
    """
    Finds complete open reading frames in all three forward reading frames.

    Reverse-strand analysis can optionally be enabled.

    An ORF begins with a valid start codon for the selected genetic
    code table and ends at the first in-frame stop codon.

    Returns
    -------
    list of dict
        ORFs sorted from longest to shortest.
    """
    normalized_sequence = str(sequence or "").upper()

    if not normalized_sequence:
        return []

    if not validate_dna(normalized_sequence):
        raise ValueError(
            "ORF identification requires a DNA sequence containing "
            "only A, T, G, and C."
        )

    genetic_code = get_genetic_code_table(table)

    start_codons = set(genetic_code.start_codons)
    stop_codons = set(genetic_code.stop_codons)

    strands = [
        {
            "name": "Forward",
            "sequence": normalized_sequence
        }
    ]

    if include_reverse_strand:
        strands.append(
            {
                "name": "Reverse complement",
                "sequence": str(
                    Seq(normalized_sequence).reverse_complement()
                )
            }
        )

    identified_orfs = []

    for strand_information in strands:
        strand_name = strand_information["name"]
        strand_sequence = strand_information["sequence"]

        for frame in range(3):
            position = frame

            while position <= len(strand_sequence) - 3:
                codon = strand_sequence[
                    position:position + 3
                ]

                if codon not in start_codons:
                    position += 3
                    continue

                stop_position = position + 3
                complete_orf_found = False

                while stop_position <= len(strand_sequence) - 3:
                    stop_codon = strand_sequence[
                        stop_position:stop_position + 3
                    ]

                    if stop_codon in stop_codons:
                        orf_sequence = strand_sequence[
                            position:stop_position + 3
                        ]

                        protein_sequence = str(
                            Seq(orf_sequence).translate(
                                table=int(table),
                                to_stop=True
                            )
                        )

                        identified_orfs.append(
                            {
                                "strand": strand_name,
                                "reading_frame": frame + 1,
                                "start_position": position + 1,
                                "end_position": stop_position + 3,
                                "start_codon": codon,
                                "stop_codon": stop_codon,
                                "nucleotide_length": len(
                                    orf_sequence
                                ),
                                "amino_acid_length": len(
                                    protein_sequence
                                ),
                                "orf_sequence": orf_sequence,
                                "protein_sequence": protein_sequence
                            }
                        )

                        complete_orf_found = True
                        break

                    stop_position += 3

                if complete_orf_found:
                    position = stop_position + 3
                else:
                    position += 3

    identified_orfs.sort(
        key=lambda item: item["nucleotide_length"],
        reverse=True
    )

    return identified_orfs


def find_orf(
    sequence: str | None,
    table: int = 1
) -> str | None:
    """
    Returns the longest complete ORF sequence.

    This function keeps compatibility with the existing application,
    which expects either one DNA sequence or None.
    """
    identified_orfs = find_orfs(
        sequence=sequence,
        table=table,
        include_reverse_strand=False
    )

    if not identified_orfs:
        return None

    return identified_orfs[0]["orf_sequence"]


# ============================================================
# EDUCATIONAL INTERPRETATION
# ============================================================

def interpret_analysis_results(
    protein_details: dict[str, Any] | None
) -> list[str]:
    """
    Produces simple educational interpretations of protein properties.
    """
    if not protein_details:
        return [
            "No protein properties are available because no valid "
            "protein sequence was generated."
        ]

    interpretations = []

    molecular_weight = protein_details[
        "molecular_weight"
    ]["value"]

    isoelectric_point = protein_details[
        "isoelectric_point"
    ]["value"]

    instability_index = protein_details[
        "instability_index"
    ]["value"]

    interpretations.append(
        f"The predicted molecular weight of the protein is "
        f"{molecular_weight} Da."
    )

    interpretations.append(
        f"The predicted isoelectric point is pH "
        f"{isoelectric_point}. At approximately this pH, the protein "
        f"is expected to have no overall electrical charge."
    )

    if instability_index < 40:
        interpretations.append(
            f"The instability index is {instability_index}, which is "
            f"below 40. The protein may therefore be stable under "
            f"laboratory conditions."
        )
    else:
        interpretations.append(
            f"The instability index is {instability_index}, which is "
            f"40 or higher. The protein may therefore be unstable "
            f"under laboratory conditions."
        )

    interpretations.append(
        protein_details["gravy"]["interpretation"]
    )

    return interpretations


# ============================================================
# STUDENT REPORT GENERATION
# ============================================================

def create_student_report(
    analysis: dict[str, Any]
) -> str:
    """
    Generates a downloadable plain-text student analysis report.

    Expected analysis keys can include:
    - original_sequence
    - cleaned_sequence
    - codon_table
    - codon_table_name
    - protein_sequence
    - molecular_weight
    - isoelectric_point
    - instability_index
    - aromaticity
    - gravy
    - orf
    - blast_title
    - blast_identity
    - blast_accession
    - interpretations
    """
    original_sequence = analysis.get(
        "original_sequence",
        "Not available"
    )

    cleaned_sequence = analysis.get(
        "cleaned_sequence",
        "Not available"
    )

    codon_table = analysis.get(
        "codon_table",
        "Not available"
    )

    codon_table_name = analysis.get(
        "codon_table_name",
        "Not available"
    )

    protein_sequence = analysis.get(
        "protein_sequence",
        "Not available"
    )

    molecular_weight = analysis.get(
        "molecular_weight",
        "Not available"
    )

    isoelectric_point = analysis.get(
        "isoelectric_point",
        "Not available"
    )

    instability_index = analysis.get(
        "instability_index",
        "Not available"
    )

    aromaticity = analysis.get(
        "aromaticity",
        "Not available"
    )

    gravy = analysis.get(
        "gravy",
        "Not available"
    )

    orf_result = analysis.get(
        "orf",
        "No complete open reading frame was identified."
    )

    blast_title = analysis.get(
        "blast_title",
        "BLAST analysis was not performed."
    )

    blast_identity = analysis.get(
        "blast_identity",
        "Not available"
    )

    blast_accession = analysis.get(
        "blast_accession",
        "Not available"
    )

    interpretations = analysis.get(
        "interpretations",
        []
    )

    if isinstance(interpretations, list):
        interpretation_text = "\n".join(
            f"- {interpretation}"
            for interpretation in interpretations
        )
    else:
        interpretation_text = str(interpretations)

    return f"""
DNA WORKSTATION STUDENT ANALYSIS REPORT
=======================================

1. ORIGINAL DNA SEQUENCE
------------------------
{original_sequence}


2. CLEANED DNA SEQUENCE
-----------------------
{cleaned_sequence}


3. SELECTED GENETIC CODE
------------------------
Table Number : {codon_table}
Table Name   : {codon_table_name}


4. TRANSLATED PROTEIN SEQUENCE
------------------------------
{protein_sequence}


5. PROTEIN PROPERTIES
---------------------
Molecular Weight  : {molecular_weight} Da
Isoelectric Point : {isoelectric_point}
Instability Index : {instability_index}
Aromaticity       : {aromaticity}
GRAVY             : {gravy}


6. OPEN READING FRAME
---------------------
{orf_result}


7. BLAST RESULT
---------------
Matched Record       : {blast_title}
Identity Percentage  : {blast_identity}
Accession Number     : {blast_accession}


8. EDUCATIONAL INTERPRETATION
-----------------------------
{interpretation_text}


This report was generated by the DNA Workstation for educational use
by undergraduate bioinformatics students.
""".strip()


# ============================================================
# NCBI BLAST
# ============================================================

@st.cache_data(show_spinner=False, ttl=1800)
def blast_sequence(
    sequence: str | None
) -> dict[str, Any]:
    """
    Submits a valid DNA sequence to NCBI BLAST and returns the best match.

    Short sequences use parameters that are more suitable for
    short-query nucleotide searches.
    """
    cleaning_report = get_cleaning_report(sequence)

    if cleaning_report["has_invalid_letters"]:
        return {
            "error": (
                "The sequence contains invalid biological letters: "
                + ", ".join(
                    cleaning_report["invalid_letters"]
                )
                + ". Correct the sequence before performing BLAST."
            )
        }

    clean_query = cleaning_report["cleaned_sequence"]

    if not clean_query:
        return {
            "error": (
                "The sequence is empty after cleaning. Enter a valid "
                "DNA sequence before performing BLAST."
            )
        }

    if not validate_dna(clean_query):
        return {
            "error": (
                "BLAST requires a DNA sequence containing only "
                "A, T, G, and C."
            )
        }

    if len(clean_query) < 11:
        return {
            "error": (
                "The sequence is too short for a meaningful BLAST "
                "search. Enter at least 11 nucleotides."
            )
        }

    result_handle = None

    try:
        if len(clean_query) < 40:
            result_handle = NCBIWWW.qblast(
                program="blastn",
                database="nt",
                sequence=clean_query,
                expect=1000,
                word_size=7,
                megablast=False,
                format_type="XML"
            )

        else:
            result_handle = NCBIWWW.qblast(
                program="blastn",
                database="nt",
                sequence=clean_query,
                megablast=False,
                format_type="XML"
            )

        blast_record = NCBIXML.read(result_handle)

        if (
            blast_record
            and hasattr(blast_record, "alignments")
            and blast_record.alignments
        ):
            alignment = blast_record.alignments[0]

            if alignment.hsps:
                hsp = alignment.hsps[0]

                if hsp.align_length > 0:
                    identity_percentage = (
                        hsp.identities
                        / hsp.align_length
                    ) * 100
                else:
                    identity_percentage = 0.0

                query_coverage = (
                    hsp.align_length
                    / len(clean_query)
                ) * 100

                query_coverage = min(
                    query_coverage,
                    100.0
                )

                return {
                    "title": alignment.title,
                    "identity": round(
                        identity_percentage,
                        2
                    ),
                    "accession": alignment.accession,
                    "alignment_length": hsp.align_length,
                    "query_coverage": round(
                        query_coverage,
                        2
                    ),
                    "e_value": hsp.expect,
                    "query_length": len(clean_query)
                }

        return {
            "error": (
                "No significant database alignment was found. "
                "Try using a longer DNA sequence or verify that the "
                "sequence is biologically meaningful."
            )
        }

    except Exception as error:
        LOGGER.exception(
            "An error occurred during the NCBI BLAST request."
        )

        return {
            "error": (
                "The NCBI BLAST service could not complete the request. "
                "This may be caused by an internet connection problem, "
                "an NCBI service delay, or a request timeout."
            ),
            "technical_details": str(error)
        }

    finally:
        if result_handle is not None:
            try:
                result_handle.close()
            except Exception:
                LOGGER.warning(
                    "The BLAST result handle could not be closed."
                )