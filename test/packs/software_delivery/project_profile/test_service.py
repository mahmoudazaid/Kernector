"""profile_project composition fixes (#387 / PR #428 review)."""

from __future__ import annotations

from packs.software_delivery.project_profile.limits import MAX_PROFILE_DIAGNOSTICS
from packs.software_delivery.project_profile.service import profile_project


def test_shared_relative_paths_attribute_by_content_hash() -> None:
    profile = profile_project(
        [
            {
                "component": "web",
                "files": [
                    {
                        "path": "components/Button.tsx",
                        "content": "export const A=1\n",
                    }
                ],
            },
            {
                "component": "admin",
                "files": [
                    {
                        "path": "components/Button.tsx",
                        "content": "export const B=2\n",
                    }
                ],
            },
        ]
    )
    by_label = {component.label: component for component in profile.components}
    web_paths = [item.path for item in by_label["web"].reusable_components]
    admin_paths = [item.path for item in by_label["admin"].reusable_components]
    assert web_paths == ["components/Button.tsx"]
    assert admin_paths == ["components/Button.tsx"]
    assert (
        by_label["web"].reusable_components[0].content_hash
        != by_label["admin"].reusable_components[0].content_hash
    )


def test_diagnostics_capped_after_extractor_merge() -> None:
    files = [
        {
            "path": f"resources/k{i}.resource",
            "content": (
                "*** Keywords ***\n"
                "${dynamic} Keyword One\n    No Operation\n"
                "${dynamic} Keyword Two\n    No Operation\n"
                "${dynamic} Keyword Three\n    No Operation\n"
                "${dynamic} Keyword Four\n    No Operation\n"
                "${dynamic} Keyword Five\n    No Operation\n"
            ),
        }
        for i in range(30)
    ]
    profile = profile_project([{"component": "tests", "files": files}])
    assert len(profile.diagnostics) <= MAX_PROFILE_DIAGNOSTICS
