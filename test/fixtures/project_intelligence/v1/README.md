# Project Intelligence fixture v1 — Part A0 (profile evidence)

Profile-evidence subset for [#387](https://github.com/mahmoudazaid/Kernector/issues/387) Phase A,
[#429](https://github.com/mahmoudazaid/Kernector/issues/429) automation framework extension,
and [#371](https://github.com/mahmoudazaid/Kernector/issues/371) Part A0.

**In scope here:** technology-profile files, profile variants, and
`gold/profile_proj.yaml` with client-declared component labels.

**Out of scope:** Jira/PAY decoys, relationships gold, evaluation runner, and
the rest of `#371` Part A (blocked by `#370`).

A0 multi-component sample still centers on **Robot Framework** (`proj-tests`) and
**Playwright** (`proj-e2e`). Additional #429 detector coverage uses offline
inline fixtures in
`test/packs/software_delivery/project_profile/test_automation_frameworks.py`
and `test_framework_matrix.py` (Cypress, Selenium, Pytest, JUnit, TestNG,
Appium, Cucumber, multi-role coexistence / conflict).
