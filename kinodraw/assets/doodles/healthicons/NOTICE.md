# Health Icons: source and licence

Imported from Health Icons (https://healthicons.org), outline style; icons drawn as filled ink outlines (data-inkfill).
Source: https://github.com/resolvetosavelives/healthicons (commit 36887b268d2cb61f8d91622ad459bdf07910c2b0). Licence: MIT, see `LICENSE` (the pack's own file).
`MANIFEST.json` lists the source file and licence of every picture.

## What was modified

Regenerate with `python -m kinodraw.library.packs healthicons SRC_DIR` (kinodraw/library/packs.py):
- Files renamed `hi_<snake_case_name>.svg`; cleaned by the library's SVG sanitiser
  (inline geometry only); transforms baked into absolute path data; art re-fitted to a 320x320 box
  with 16 px padding; shapes converted to paths (arcs stay arcs), coordinates rounded to 0.1 px.
- Every paint (including currentColor) set to the library ink #1B1B1B; filled outlines marked `data-inkfill="1"` so the drawing hand traces them.
- Tags (`../tags/healthicons.json`): `desc` from the icon name, `en` from its name and the pack's
  own keywords, `category` from the pack. No Chinese keywords: these pictures are found in English
  and Spanish only.

## Not imported (260; 489 imported)

Left out: letters or digits in the art (STYLE.md: no text in doodles), logos and trademarks, and the
library's denylist themes (weapons, drugs, alcohol, death, religious imagery, sexual health).

- **category blood** (11): blood-a_n, blood-a_p, blood-ab_n, blood-ab_p, blood-b_n, blood-b_p, blood-bag, blood-o_n, blood-o_p, blood-rh_n, blood-rh_p
- **category contraceptives** (15): contraceptive-diaphragm, contraceptive-injection, contraceptive-patch, contraceptive-voucher, copper-iud, family-planning, female-condom, hormonal-ring, implant, iud, male-condom, oral-contraception_pillsx21, oral-contraception_pillsx28, sayana-press, sperm
- **category diagnostics** (33): biopsy, cone-test_on_nets, cone-test_on_walls, discriminating-concentration_bioassays, hiv-self_test, intensity-concentration_bioassays, malaria-microscope, malaria-mixed_microscope, malaria-pf_microscope, malaria-pv_microscope, malaria-testing, mosquito-collection, rdt-result, rdt-result_invalid, rdt-result_mixed, rdt-result_mixed_invalid, rdt-result_mixed_invalid_rectangular, rdt-result_mixed_rectangular, rdt-result_neg, rdt-result_neg_invalid, rdt-result_neg_invalid_rectangular, rdt-result_neg_rectangular, rdt-result_no_test, rdt-result_pf, rdt-result_pf_invalid, rdt-result_pf_invalid_rectangular, rdt-result_pf_rectangular, rdt-result_positive, rdt-result_pv, rdt-result_pv_invalid, rdt-result_pv_invalid_rectangular, rdt-result_pv_rectangular, synergist-insecticide_bioassays
- **category medications** (13): blister-pills_oval_x1, blister-pills_oval_x14, blister-pills_oval_x16, blister-pills_oval_x4, blister-pills_round_x1, blister-pills_round_x14, blister-pills_round_x16, blister-pills_round_x4, medicines, pill-1, pills-2, pills-3, pills-4
- **category specialties** (43): accident-and_emergency, admissions, biochemistry-laboratory, burn-unit, cardiology, chaplaincy, coronary-care_unit, critical-care, discharge-lounge, ears-nose_and_throat, endocrinology, finance-dept, gastroenterology, general-surgery, geriatrics, gym, gynecology, hematology, hematology-laboratory, hepatology, human-resoruces, intensive-care_unit, medical-records, nephrology, obstetricsmonia, occupational-therapy, oncology, opthalmology, orthopaedics, outpatient-department, pain-managment, pediatrics, pharmacy, physical-therapy, psychology, radiology, respirology, rheumatology, social-work, sonography, speech-language_therapy, urology, vascular-surgery
- **category typography** (48): !, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z, dollar, euro, ghana, naira, peso, pound, question-mark, ruble, rupee, won, yen
- **denylist** (96): 2g, 3g, FHIR-logo, HL7v2-logo, alcohol, alcohol-cessation, ancv, anus, blood-drop, body-mass_index, breasts, cannabis, cervical-cancer, chart-death-rate-decreasing, chart-death-rate-increasing, chart-death-rate-stable, chlamydia, chlamydia-alt, church, clinical-a, clinical-f, clinical-fe, cpr, death, death-alt, death-alt2, dhis2-logo, diarrhea, excel-logo, expectorate, female-reproductive_system, female-sex_worker, fetus, gonorrhea, gonorrhea-alt, hiv-ind, hiv-neg, hiv-pos, hospital-symbol, hpv, i-exam_qualification, icd, icd-10, icd-11, icd-9, imm, information-campaign, loinc, male-sex_worker, mosque, msm, network-4g, network-5g, no, openMRS-logo, oxygen-tank, penis, penis-alt, poison, pregnant-0812w, pregnant-2426w, pregnant-32w, pregnant-3638w, prescription-document, prostate, prostate-cancer, provider-fst, pulse-oximeter_alt, pwid, qr-code, rmnh, rx, sexual-reproductive_health, simple-logo, skull, smoking, smoking-cessation, smoking-cessation_alt, sti, syphilis-alt, syringe, syringe-vaccine, tac, tb, temple, temple-alt, testicles, tongue, vagina, vagina-alt, vih, virus-lab_research_syringe, vomiting, vomitting, war, yes
- **mostly solid ink** (1): public/icons/svg/outline/people/crisis-response_center_person.svg
