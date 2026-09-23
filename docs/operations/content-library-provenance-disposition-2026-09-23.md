# Content-library provenance disposition — 2026-09-23

## Measured inventory

The executable command `python3 scripts/audit_content_library_provenance.py --output <path>` reads both tracked copies. On 2026-09-23 it measured 6 canonical records and 6 web records, rather than the historical audit's 70. Before this disposition all 6 lacked `data_class`, `source_id`, and `source_url`; all 6 had the required structured location fields. The script is the release gate: non-synthetic records require their source linkage plus retrieval time, period, transformation version, and rights status; it exits non-zero on violations or mismatched copy bytes.

## Historical blocked items and disposition

| Historical item | Disposition | Evidence / boundary |
| --- | --- | --- |
| 70 historical library records with no publishable provenance | Obsolete for the current tracked library: only 6 records are present. Not evidence that the missing historical records are authorized or publishable. | Measured inventory above; do not restore them without their own provenance review. |
| 6 current JPHOUSE worker examples with placeholder sources and modeled text | Resolved by explicit `synthetic_fixture` classification and local source association. | `scripts/label_content_library_synthetic.py`, both JSON copies, and executable audit output. They remain ineligible as market facts. |
| Real/authorized observations for a published content library | Still blocked. | No current content-library row is classified `verified_observation`; a future row needs a `sources` registry link and full provenance before the gate permits it. |
| Canonical/web copy drift | Resolved for synchronized copies. | The gate compares SHA-256 bytes and exits non-zero on a mismatch. |

This disposition makes the current non-synthetic violation count zero; it does not establish market representativeness, collection rights for third-party listing sites, or production publication approval.
